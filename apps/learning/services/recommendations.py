"""Turn persisted learner state into the next recommendation and persist the decision."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max

from apps.catalog.constants import FORMAT_FAMILIES
from apps.catalog.models import Challenge
from apps.core.timeutils import day_bounds, user_zone
from apps.engine.scheduling import review_urgency
from apps.engine.selection import (
    CandidateChallenge,
    ChallengeHistory,
    SelectionRequest,
    SkillContext,
    select_challenge,
)
from apps.evaluation.registry import unavailable_kinds

from ..models import AttemptEvaluation, LearningAttempt, LearningEvent, LearningSession, Recommendation
from .planning import GoalContext, goal_context
from .snapshot import LearnerSnapshot

logger = logging.getLogger(__name__)

RECENT_WINDOW = timedelta(days=60)
STRUGGLE_WINDOW = timedelta(days=14)


@dataclass(frozen=True)
class SkillEvidenceSummary:
    recent_scores: tuple[float, ...]
    recent_failures: int
    top_misconception: str | None


def preferences(profile) -> tuple[frozenset[str], frozenset[str]]:
    kinds: set[str] = set()
    tags: set[str] = set()
    for family in profile.preferred_formats or []:
        data = FORMAT_FAMILIES.get(family)
        if data:
            kinds.update(str(k) for k in data["kinds"])
            tags.update(data["tags"])
    return frozenset(kinds), frozenset(tags)


def evidence_summaries(user, now: datetime) -> dict[int, SkillEvidenceSummary]:
    """Recent scores, failure counts and most common misconception per primary skill."""
    rows = (
        AttemptEvaluation.objects.filter(attempt__user=user, attempt__submitted_at__gte=now - RECENT_WINDOW)
        .order_by("attempt__submitted_at")
        .values_list("attempt__challenge__skill_id", "score", "passed", "misconceptions", "attempt__submitted_at")
    )
    scores: dict[int, list[float]] = defaultdict(list)
    failures: Counter = Counter()
    misconceptions: dict[int, Counter] = defaultdict(Counter)
    labels: dict[str, str] = {}
    for skill_id, score, passed, items, submitted_at in rows:
        scores[skill_id].append(score)
        if now - submitted_at <= STRUGGLE_WINDOW:
            if not passed:
                failures[skill_id] += 1
            for item in items or []:
                misconceptions[skill_id][item["code"]] += 1
                labels[item["code"]] = item["label"]
    summaries = {}
    for skill_id in set(scores) | set(failures):
        common = misconceptions[skill_id].most_common(1)
        top = labels[common[0][0]] if common and common[0][1] >= 1 else None
        summaries[skill_id] = SkillEvidenceSummary(tuple(scores[skill_id][-5:]), failures[skill_id], top)
    return summaries


def challenge_histories(user, challenge_ids: list[int]) -> dict[int, ChallengeHistory]:
    rows = (
        LearningAttempt.objects.filter(user=user, challenge_id__in=challenge_ids)
        .values("challenge_id")
        .annotate(n=Count("id"), last=Max("submitted_at"), best=Max("evaluation__score"))
    )
    return {
        r["challenge_id"]: ChallengeHistory(attempts=r["n"], last_attempted_at=r["last"], best_score=r["best"])
        for r in rows
    }


def build_skill_contexts(
    context: GoalContext, snapshot: LearnerSnapshot, summaries: dict[int, SkillEvidenceSummary], day_end: datetime
) -> dict[int, SkillContext]:
    contexts = {}
    empty = SkillEvidenceSummary((), 0, None)
    for skill_id, relevance in context.relevance.items():
        skill = snapshot.skills.get(skill_id)
        if skill is None:
            continue
        state = snapshot.state(skill_id)
        summary = summaries.get(skill_id, empty)
        stored = snapshot.masteries.get(skill_id)
        contexts[skill_id] = SkillContext(
            skill_id=skill_id,
            name=skill.name,
            difficulty=skill.difficulty,
            mean=state.mean,
            evidence_count=state.evidence_count,
            urgency=review_urgency(snapshot.reviews.get(skill_id), snapshot.now, day_end),
            goal_relevance=relevance,
            dependency_importance=context.dependency_importance.get(skill_id, 0.0),
            readiness=snapshot.readiness(skill_id),
            recent_scores=summary.recent_scores,
            recent_failures=summary.recent_failures,
            top_misconception=summary.top_misconception,
            last_practiced_at=stored.last_practiced_at if stored else None,
            blocking_for=context.blocking_for.get(skill_id, ()),
            is_focus_skill=skill_id in context.focus_ids,
            milestone_title=context.milestone_titles.get(skill_id),
            in_current_milestone=skill_id in context.current_milestone_ids,
        )
    return contexts


def create_recommendation(session: LearningSession, *, now: datetime) -> Recommendation | None:
    """Select and persist the next recommendation for a session (or None if nothing fits)."""
    user = session.user
    goal = session.goal
    if goal is None:
        return None
    snapshot = LearnerSnapshot.load(user, now=now, level=goal.experience_level)
    context = goal_context(goal, snapshot)
    zone = user_zone(user)
    _, day_end = day_bounds(session.local_date, zone)

    existing = list(session.recommendations.select_related("challenge"))
    used_minutes = sum(r.challenge.estimated_minutes for r in existing if r.status != Recommendation.Status.SKIPPED)
    skills_today = Counter(r.challenge.skill_id for r in existing if r.status != Recommendation.Status.SKIPPED)

    challenges = list(
        Challenge.objects.published()
        .filter(skill_id__in=context.universe)
        .only(
            "id", "skill_id", "kind", "difficulty", "estimated_minutes", "tags", "is_diagnostic", "current_version_id"
        )
    )
    candidates = [
        CandidateChallenge(
            challenge_id=c.id,
            version_id=c.current_version_id,
            skill_id=c.skill_id,
            kind=c.kind,
            difficulty=c.difficulty,
            minutes=c.estimated_minutes,
            tags=frozenset(c.tags or []),
            is_diagnostic=c.is_diagnostic,
        )
        for c in challenges
    ]
    histories = challenge_histories(user, [c.id for c in challenges])
    summaries = evidence_summaries(user, now)
    skill_contexts = build_skill_contexts(context, snapshot, summaries, day_end)
    kinds, tags = preferences(user.profile)
    engine = settings.SKILLFORGE_ENGINE
    position = len(existing) + 1
    request = SelectionRequest(
        seed=f"{user.pk}:{session.local_date.isoformat()}:{position}",
        now=now,
        minutes_remaining=max(0, session.minutes_budget - used_minutes),
        preferred_kinds=kinds,
        preferred_tags=tags,
        difficulty_preference=user.profile.difficulty_preference,
        excluded_challenge_ids=frozenset(r.challenge_id for r in existing),
        skills_recommended_today=skills_today,
        unavailable_kinds=unavailable_kinds(),
        weights=dict(engine["SELECTION_WEIGHTS"]),
        exploration_rate=engine["EXPLORATION_RATE"],
        top_k=engine["TOP_K"],
        path_name=goal.path.name if goal.path_id else None,
    )
    selection = select_challenge(candidates, skill_contexts, histories, request)
    if selection is None:
        logger.info("recommendation.none_eligible", extra={"user_id": user.pk, "session_id": session.pk})
        return None

    scored = selection.scored
    data = dict(selection.explanation.data)
    data.update(
        {
            "skill_id": scored.skill.skill_id,
            "priority": scored.priority,
            "modifiers": scored.modifiers,
            "target_difficulty": scored.target_difficulty,
            "goal_relevance": round(scored.skill.goal_relevance, 3),
        }
    )
    try:
        with transaction.atomic():
            recommendation = Recommendation.objects.create(
                session=session,
                user=user,
                challenge_id=scored.candidate.challenge_id,
                challenge_version_id=scored.candidate.version_id,
                position=position,
                reason_code=selection.explanation.code,
                reason_text=selection.explanation.text[:300],
                reason_data=data,
                score=scored.score,
                strategy_version=selection.strategy_version,
                is_review=scored.skill.urgency > 0,
                explored=selection.explored,
            )
            LearningEvent.objects.create(
                user=user,
                event_type=LearningEvent.Type.RECOMMENDATION_CREATED,
                goal=goal,
                skill_id=scored.skill.skill_id,
                payload={"recommendation_id": recommendation.pk, "reason": selection.explanation.code},
            )
    except IntegrityError:
        # A concurrent request filled this slot first; use theirs.
        return session.recommendations.filter(position=position).first()
    return recommendation
