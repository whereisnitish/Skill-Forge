"""Load a learner's state into engine data structures with a fixed number of queries."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from apps.catalog.models import Skill, SkillPrerequisite
from apps.engine.eligibility import PrerequisiteEdge, Readiness, readiness
from apps.engine.graph import SkillGraph
from apps.engine.mastery import LEVEL_LABELS, MasteryLevel, MasteryState, get_model
from apps.engine.scheduling import ReviewState

from ..models import ReviewSchedule, SkillMastery


@dataclass(frozen=True)
class SkillRow:
    id: int
    slug: str
    name: str
    difficulty: int
    review_interval_days: int
    category_id: int


def mastery_state_from_row(row: SkillMastery) -> MasteryState:
    return MasteryState(
        alpha=row.alpha,
        beta=row.beta,
        prior_alpha=row.prior_alpha,
        prior_beta=row.prior_beta,
        evidence_count=row.evidence_count,
        success_count=row.success_count,
        delayed_successes=row.delayed_successes,
        formats_seen=frozenset(row.formats_seen or []),
        last_practiced_at=row.last_practiced_at,
        model_version=row.model_version,
    )


def review_state_from_row(row: ReviewSchedule) -> ReviewState:
    return ReviewState(
        interval_days=row.interval_days,
        ease=row.ease,
        repetitions=row.repetitions,
        lapses=row.lapses,
        due_at=row.due_at,
        last_reviewed_at=row.last_reviewed_at,
        last_score=row.last_score,
        algorithm_version=row.algorithm_version,
    )


@dataclass(frozen=True)
class MasteryView:
    """Presentation-ready mastery for one skill at a point in time."""

    skill_id: int
    mean: float
    std: float
    lower_bound: float
    evidence_count: int
    level: MasteryLevel
    confidence: str
    measured: bool
    last_practiced_at: datetime | None

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS[self.level]

    @property
    def percent(self) -> int:
        return round(self.mean * 100)


class LearnerSnapshot:
    def __init__(
        self,
        *,
        user,
        now: datetime,
        level: str,
        skills: dict[int, SkillRow],
        edges: dict[int, list[PrerequisiteEdge]],
        masteries: dict[int, MasteryState],
        reviews: dict[int, ReviewState],
    ):
        self.user = user
        self.now = now
        self.level = level
        self.skills = skills
        self.edges = edges
        self.masteries = masteries
        self.reviews = reviews
        self.model = get_model()
        self.graph = SkillGraph.from_edges(
            skills.keys(), ((skill_id, e.prerequisite_id) for skill_id, es in edges.items() for e in es)
        )
        self._current: dict[int, MasteryState] = {}

    @classmethod
    def load(cls, user, *, now: datetime | None = None, level: str | None = None) -> LearnerSnapshot:
        now = now or timezone.now()
        if level is None:
            level = getattr(getattr(user, "profile", None), "experience_level", "beginner")
        skills = {
            s.id: SkillRow(s.id, s.slug, s.name, s.difficulty, s.review_interval_days, s.category_id)
            for s in Skill.objects.active().only(
                "id", "slug", "name", "difficulty", "review_interval_days", "category_id"
            )
        }
        edges: dict[int, list[PrerequisiteEdge]] = defaultdict(list)
        for link in SkillPrerequisite.objects.filter(skill__is_active=True, prerequisite__is_active=True):
            edges[link.skill_id].append(
                PrerequisiteEdge(
                    prerequisite_id=link.prerequisite_id,
                    required=link.strength == SkillPrerequisite.Strength.REQUIRED,
                    min_mastery=link.min_mastery,
                )
            )
        masteries = {row.skill_id: mastery_state_from_row(row) for row in SkillMastery.objects.filter(user=user)}
        reviews = {row.skill_id: review_state_from_row(row) for row in ReviewSchedule.objects.filter(user=user)}
        return cls(
            user=user, now=now, level=level, skills=skills, edges=dict(edges), masteries=masteries, reviews=reviews
        )

    # -- mastery ---------------------------------------------------------
    def state(self, skill_id: int) -> MasteryState:
        """Current (time-decayed) mastery state, falling back to the level prior."""
        if skill_id not in self._current:
            stored = self.masteries.get(skill_id)
            if stored is None:
                skill = self.skills.get(skill_id)
                difficulty = skill.difficulty if skill else 2
                self._current[skill_id] = self.model.prior(self.level, difficulty)
            else:
                self._current[skill_id] = self.model.current(stored, self.now)
        return self._current[skill_id]

    def mean(self, skill_id: int) -> float:
        return self.state(skill_id).mean

    def measured(self, skill_id: int) -> bool:
        stored = self.masteries.get(skill_id)
        return stored is not None and stored.evidence_count > 0

    def view(self, skill_id: int) -> MasteryView:
        state = self.state(skill_id)
        measured = self.measured(skill_id)
        stored = self.masteries.get(skill_id)
        return MasteryView(
            skill_id=skill_id,
            mean=state.mean,
            std=state.std,
            lower_bound=state.lower_bound,
            evidence_count=state.evidence_count,
            level=self.model.level(state if measured else None),
            confidence=self.model.confidence(state if measured else None),
            measured=measured,
            last_practiced_at=stored.last_practiced_at if stored else None,
        )

    def readiness(self, skill_id: int) -> Readiness:
        return readiness(self.edges.get(skill_id, []), self.mean)
