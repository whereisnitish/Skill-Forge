"""Apply an evaluated attempt to mastery, review scheduling, plans and milestones.

Called inside the evaluation transaction with the attempt row locked. Each
write is guarded by a uniqueness constraint (SkillEvidence per attempt+skill,
ReviewRecord per attempt), so a retried task can never apply evidence twice.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from django.utils import timezone

from apps.catalog.models import Skill
from apps.engine.mastery import MasteryState, Observation, get_model
from apps.engine.scheduling import get_scheduler

from ..models import (
    AttemptEvaluation,
    LearningAttempt,
    LearningEvent,
    LearningGoal,
    Recommendation,
    ReviewRecord,
    ReviewSchedule,
    SkillEvidence,
    SkillMastery,
)
from .snapshot import mastery_state_from_row, review_state_from_row

SECONDARY_SKILL_WEIGHT = 0.4


def _level_for(attempt: LearningAttempt) -> str:
    if attempt.goal_id:
        return attempt.goal.experience_level
    return attempt.user.profile.experience_level


def _save_mastery(row: SkillMastery | None, user_id: int, skill: Skill, state: MasteryState) -> SkillMastery:
    fields = {
        "alpha": state.alpha,
        "beta": state.beta,
        "prior_alpha": state.prior_alpha,
        "prior_beta": state.prior_beta,
        "evidence_count": state.evidence_count,
        "success_count": state.success_count,
        "delayed_successes": state.delayed_successes,
        "formats_seen": sorted(state.formats_seen),
        "last_practiced_at": state.last_practiced_at,
        "mean_at_update": state.mean,
        "model_version": state.model_version,
    }
    if row is None:
        return SkillMastery.objects.create(user_id=user_id, skill=skill, **fields)
    for key, value in fields.items():
        setattr(row, key, value)
    row.save()
    return row


def update_mastery(attempt: LearningAttempt, evaluation: AttemptEvaluation) -> list[SkillEvidence]:
    model = get_model()
    challenge = attempt.challenge
    level = _level_for(attempt)
    targets = [(challenge.skill, 1.0)] + [
        (skill, SECONDARY_SKILL_WEIGHT) for skill in challenge.secondary_skills.filter(is_active=True)
    ]
    created: list[SkillEvidence] = []
    for skill, weight in targets:
        if SkillEvidence.objects.filter(attempt=attempt, skill=skill).exists():
            continue
        row = SkillMastery.objects.select_for_update().filter(user_id=attempt.user_id, skill=skill).first()
        state = mastery_state_from_row(row) if row else model.prior(level, skill.difficulty)
        before = model.current(state, attempt.submitted_at)
        new_state, detail = model.update(
            state,
            Observation(
                score=evaluation.score,
                challenge_difficulty=challenge.difficulty,
                skill_difficulty=skill.difficulty,
                kind=challenge.kind,
                occurred_at=attempt.submitted_at,
                hints_used=attempt.hints_used,
                hints_available=attempt.hints_available,
                solution_revealed=attempt.solution_revealed,
                weight=weight,
            ),
        )
        _save_mastery(row, attempt.user_id, skill, new_state)
        evidence = SkillEvidence.objects.create(
            user_id=attempt.user_id,
            skill=skill,
            attempt=attempt,
            weight=weight,
            score=evaluation.score,
            mastery_before=round(before.mean, 4),
            mastery_after=round(new_state.mean, 4),
            std_after=round(new_state.std, 4),
            detail=asdict(detail),
            model_version=model.version,
        )
        created.append(evidence)
        LearningEvent.objects.create(
            user_id=attempt.user_id,
            event_type=LearningEvent.Type.MASTERY_UPDATED,
            skill=skill,
            attempt=attempt,
            payload={"before": evidence.mastery_before, "after": evidence.mastery_after, "weight": weight},
        )
    return created


def update_review_schedule(attempt: LearningAttempt, evaluation: AttemptEvaluation) -> ReviewRecord | None:
    if ReviewRecord.objects.filter(attempt=attempt).exists():
        return None
    skill = attempt.challenge.skill
    row = ReviewSchedule.objects.select_for_update().filter(user_id=attempt.user_id, skill=skill).first()
    if row is None and attempt.is_diagnostic and not evaluation.passed:
        # A missed placement question means "not learned yet", not "forgotten":
        # the path will teach it; don't flood tomorrow with reviews.
        return None
    scheduler = get_scheduler()
    state, decision = scheduler.schedule(
        review_state_from_row(row) if row else None,
        score=evaluation.score,
        now=attempt.submitted_at,
        base_interval_days=skill.review_interval_days,
        hints_used=attempt.hints_used,
        solution_revealed=attempt.solution_revealed,
    )
    fields = {
        "interval_days": state.interval_days,
        "ease": state.ease,
        "repetitions": state.repetitions,
        "lapses": state.lapses,
        "due_at": state.due_at,
        "last_reviewed_at": state.last_reviewed_at,
        "last_score": state.last_score,
        "algorithm_version": state.algorithm_version,
    }
    if row is None:
        row = ReviewSchedule.objects.create(user_id=attempt.user_id, skill=skill, **fields)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
        row.save()
    record = ReviewRecord.objects.create(
        schedule=row,
        attempt=attempt,
        outcome=decision.outcome,
        quality=decision.quality,
        previous_interval_days=decision.previous_interval_days,
        previous_due_at=decision.previous_due_at,
        new_interval_days=decision.new_interval_days,
        new_due_at=decision.new_due_at,
        reviewed_at=attempt.submitted_at,
    )
    LearningEvent.objects.create(
        user_id=attempt.user_id,
        event_type=LearningEvent.Type.REVIEW_SCHEDULED,
        skill=skill,
        attempt=attempt,
        payload={"outcome": decision.outcome, "interval_days": decision.new_interval_days},
    )
    return record


def resolve_recommendation(attempt: LearningAttempt, now: datetime) -> None:
    if attempt.recommendation_id:
        Recommendation.objects.filter(pk=attempt.recommendation_id, status=Recommendation.Status.PENDING).update(
            status=Recommendation.Status.COMPLETED, resolved_at=now
        )


def apply_learning_updates(
    attempt: LearningAttempt, evaluation: AttemptEvaluation, *, now: datetime | None = None
) -> None:
    now = now or timezone.now()
    attempt = LearningAttempt.objects.select_related("challenge__skill", "goal", "user__profile").get(pk=attempt.pk)
    update_mastery(attempt, evaluation)
    update_review_schedule(attempt, evaluation)
    resolve_recommendation(attempt, now)

    from .achievements import check_achievements
    from .milestones import check_milestones

    check_achievements(attempt, evaluation, now=now)
    goal = attempt.goal
    if goal is not None and goal.status == LearningGoal.Status.ACTIVE:
        check_milestones(goal, now=now)
