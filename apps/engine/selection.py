"""Challenge selection — strategy `weighted-priority-v1`.

1. Eligibility constraints are applied first (prerequisites, availability of an
   evaluator, already-planned challenges, very recent repeats).
2. Each remaining candidate gets a priority from a configurable weighted sum::

       priority = 0.35·weakness + 0.25·review_urgency
                + 0.20·goal_relevance + 0.20·dependency_importance

   which is then adjusted for difficulty fit, format preference, history,
   variety within the day and the remaining time budget.
3. Controlled variation: with a small probability an unmeasured skill is probed
   ("discover gaps"); otherwise the pick is a weighted draw among the top-k.
   The random source is seeded from the user, day and slot, so a given plan is
   reproducible and stable across page reloads, yet varies day to day.

The weights are an initial heuristic, not a validated scientific formula.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .difficulty import difficulty_fit, target_difficulty
from .eligibility import Readiness
from .explain import Explanation, ExplanationContext, explain

STRATEGY_VERSION = "weighted-priority-v1"
DEFAULT_WEIGHTS = {
    "weakness": 0.35,
    "review_urgency": 0.25,
    "goal_relevance": 0.20,
    "dependency_importance": 0.20,
}
RECENT_REPEAT_WINDOW = timedelta(hours=20)
FOCUS_BOOST = 1.5  # skills the learner explicitly prioritised on their goal


@dataclass(frozen=True)
class CandidateChallenge:
    challenge_id: int
    version_id: int
    skill_id: int
    kind: str
    difficulty: int
    minutes: int
    tags: frozenset[str] = field(default_factory=frozenset)
    is_diagnostic: bool = False


@dataclass(frozen=True)
class ChallengeHistory:
    attempts: int = 0
    last_attempted_at: datetime | None = None
    best_score: float | None = None


@dataclass(frozen=True)
class SkillContext:
    skill_id: int
    name: str
    difficulty: int
    mean: float
    evidence_count: int
    urgency: float
    goal_relevance: float
    dependency_importance: float
    readiness: Readiness
    recent_scores: tuple[float, ...] = ()
    recent_failures: int = 0
    top_misconception: str | None = None
    last_practiced_at: datetime | None = None
    blocking_for: tuple[str, ...] = ()
    is_focus_skill: bool = False
    milestone_title: str | None = None
    in_current_milestone: bool = False


@dataclass(frozen=True)
class SelectionRequest:
    seed: str
    now: datetime
    minutes_remaining: int
    preferred_kinds: frozenset[str] = field(default_factory=frozenset)
    preferred_tags: frozenset[str] = field(default_factory=frozenset)
    difficulty_preference: str = "balanced"
    excluded_challenge_ids: frozenset[int] = field(default_factory=frozenset)
    skills_recommended_today: Counter = field(default_factory=Counter)
    unavailable_kinds: frozenset[str] = field(default_factory=frozenset)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    exploration_rate: float = 0.15
    top_k: int = 3
    path_name: str | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: CandidateChallenge
    skill: SkillContext
    priority: float
    score: float
    components: dict[str, float]
    modifiers: dict[str, float]
    target_difficulty: float


@dataclass(frozen=True)
class Selection:
    scored: ScoredCandidate
    explanation: Explanation
    strategy_version: str = STRATEGY_VERSION
    explored: bool = False


def _rng(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))  # noqa: S311 - reproducible sampling, not security


def _eligible(
    candidate: CandidateChallenge,
    skill: SkillContext | None,
    history: ChallengeHistory,
    request: SelectionRequest,
) -> bool:
    if skill is None or not skill.readiness.ready:
        return False
    if candidate.kind in request.unavailable_kinds:
        return False
    if candidate.challenge_id in request.excluded_challenge_ids:
        return False
    return not (history.last_attempted_at and request.now - history.last_attempted_at < RECENT_REPEAT_WINDOW)


def score_candidate(
    candidate: CandidateChallenge,
    skill: SkillContext,
    history: ChallengeHistory,
    request: SelectionRequest,
) -> ScoredCandidate:
    weights = request.weights
    components = {
        "weakness": 1.0 - skill.mean,
        "review_urgency": skill.urgency,
        "goal_relevance": skill.goal_relevance,
        "dependency_importance": skill.dependency_importance,
    }
    contributions = {key: weights.get(key, 0.0) * value for key, value in components.items()}
    priority = sum(contributions.values())

    target = target_difficulty(skill.mean, skill.recent_scores, request.difficulty_preference)
    modifiers: dict[str, float] = {"difficulty_fit": difficulty_fit(candidate.difficulty, target)}

    if request.preferred_kinds or request.preferred_tags:
        preferred = candidate.kind in request.preferred_kinds or bool(candidate.tags & request.preferred_tags)
        modifiers["format_preference"] = 1.15 if preferred else 0.9

    if history.attempts:
        if history.best_score is not None and history.best_score >= 0.8:
            modifiers["history"] = 0.75 if skill.urgency > 0 else 0.45
        else:
            modifiers["history"] = 0.9
    else:
        modifiers["history"] = 1.0

    if skill.is_focus_skill:
        modifiers["goal_priority"] = FOCUS_BOOST

    repeats = request.skills_recommended_today.get(skill.skill_id, 0)
    if repeats:
        modifiers["variety"] = 0.6**repeats
    if candidate.minutes > request.minutes_remaining:
        modifiers["time_budget"] = 0.35
    if skill.readiness.missing_recommended:
        modifiers["recommended_prerequisites"] = 0.85

    score = priority
    for value in modifiers.values():
        score *= value
    return ScoredCandidate(
        candidate=candidate,
        skill=skill,
        priority=round(priority, 6),
        score=round(score, 6),
        components={k: round(v, 6) for k, v in contributions.items()},
        modifiers={k: round(v, 4) for k, v in modifiers.items()},
        target_difficulty=round(target, 3),
    )


def _explain(scored: ScoredCandidate, request: SelectionRequest, explored: bool) -> Explanation:
    skill = scored.skill
    days = None
    if skill.last_practiced_at is not None:
        days = max(0, (request.now - skill.last_practiced_at).days)
    return explain(
        ExplanationContext(
            skill_name=skill.name,
            urgency=skill.urgency,
            weakness=1.0 - skill.mean,
            goal_relevance=skill.goal_relevance,
            dependency_importance=skill.dependency_importance,
            contributions=scored.components,
            mean=skill.mean,
            evidence_count=skill.evidence_count,
            days_since_practice=days,
            recent_failures=skill.recent_failures,
            top_misconception=skill.top_misconception,
            blocking_for=skill.blocking_for,
            is_focus_skill=skill.is_focus_skill,
            milestone_title=skill.milestone_title,
            in_current_milestone=skill.in_current_milestone,
            path_name=request.path_name,
            explored=explored,
        )
    )


def select_challenge(
    candidates: Sequence[CandidateChallenge],
    skills: dict[int, SkillContext],
    histories: dict[int, ChallengeHistory],
    request: SelectionRequest,
) -> Selection | None:
    """Pick the next challenge, or None when nothing is currently eligible."""
    empty = ChallengeHistory()
    scored = [
        score_candidate(c, skills[c.skill_id], histories.get(c.challenge_id, empty), request)
        for c in candidates
        if _eligible(c, skills.get(c.skill_id), histories.get(c.challenge_id, empty), request)
    ]
    if not scored:
        return None
    scored.sort(key=lambda s: (-s.score, s.candidate.challenge_id))
    rng = _rng(request.seed)

    if request.exploration_rate > 0 and rng.random() < request.exploration_rate:
        unmeasured = [
            s
            for s in scored
            if s.skill.evidence_count == 0
            and s.skill.urgency == 0
            and s.candidate.minutes <= max(request.minutes_remaining, 3)
        ]
        if unmeasured:
            unmeasured.sort(key=lambda s: (not s.candidate.is_diagnostic, -s.score, s.candidate.challenge_id))
            pick = unmeasured[0]
            return Selection(pick, _explain(pick, request, explored=True), explored=True)

    top = scored[: max(1, request.top_k)]
    weights = [max(s.score, 1e-6) ** 2 for s in top]
    pick = rng.choices(top, weights=weights, k=1)[0]
    return Selection(pick, _explain(pick, request, explored=False))
