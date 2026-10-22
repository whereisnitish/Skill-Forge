"""Goal and path context: relevance, blocking prerequisites and milestone progress."""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.catalog.models import PathMilestone

from ..models import LearningGoal
from .snapshot import LearnerSnapshot, MasteryView

STEP_MIN_EVIDENCE = 2

RELEVANCE_FOCUS = 1.0
RELEVANCE_CURRENT_MILESTONE = 0.85
RELEVANCE_NEXT_MILESTONE = 0.6
RELEVANCE_LATER_MILESTONE = 0.4
RELEVANCE_COMPLETED_MILESTONE = 0.3
RELEVANCE_REVIEW_ONLY = 0.3


@dataclass(frozen=True)
class StepProgress:
    skill_id: int
    skill_slug: str
    skill_name: str
    target: float
    mastery: MasteryView
    complete: bool
    ready: bool

    @property
    def fraction(self) -> float:
        return min(1.0, self.mastery.mean / self.target) if self.target else 0.0


@dataclass(frozen=True)
class MilestoneProgress:
    id: int
    order: int
    title: str
    description: str
    steps: list[StepProgress]

    @property
    def complete(self) -> bool:
        return all(step.complete for step in self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for step in self.steps if step.complete)

    @property
    def fraction(self) -> float:
        if not self.steps:
            return 0.0
        return sum(step.fraction if not step.complete else 1.0 for step in self.steps) / len(self.steps)


@dataclass
class PathProgress:
    milestones: list[MilestoneProgress]
    current_index: int | None

    @property
    def complete(self) -> bool:
        return bool(self.milestones) and all(m.complete for m in self.milestones)

    @property
    def fraction(self) -> float:
        steps = [s for m in self.milestones for s in m.steps]
        if not steps:
            return 0.0
        return sum(1.0 if s.complete else s.fraction for s in steps) / len(steps)

    @property
    def completed_steps(self) -> int:
        return sum(m.completed_steps for m in self.milestones)

    @property
    def total_steps(self) -> int:
        return sum(len(m.steps) for m in self.milestones)

    @property
    def current(self) -> MilestoneProgress | None:
        return self.milestones[self.current_index] if self.current_index is not None else None


@dataclass
class GoalContext:
    goal: LearningGoal
    progress: PathProgress | None
    relevance: dict[int, float]
    milestone_titles: dict[int, str]
    dependency_importance: dict[int, float]
    blocking_for: dict[int, tuple[str, ...]]
    focus_ids: set[int] = field(default_factory=set)
    current_milestone_ids: set[int] = field(default_factory=set)

    @property
    def universe(self) -> set[int]:
        return set(self.relevance)


def load_milestones(path_version_id: int) -> list[PathMilestone]:
    return list(
        PathMilestone.objects.filter(version_id=path_version_id).prefetch_related("steps__skill").order_by("order")
    )


def path_progress(milestones: list[PathMilestone], snapshot: LearnerSnapshot) -> PathProgress:
    result: list[MilestoneProgress] = []
    for milestone in milestones:
        steps = []
        for step in sorted(milestone.steps.all(), key=lambda s: s.order):
            view = snapshot.view(step.skill_id)
            steps.append(
                StepProgress(
                    skill_id=step.skill_id,
                    skill_slug=step.skill.slug,
                    skill_name=step.skill.name,
                    target=step.target_mastery,
                    mastery=view,
                    complete=view.measured
                    and view.mean >= step.target_mastery
                    and view.evidence_count >= STEP_MIN_EVIDENCE,
                    ready=snapshot.readiness(step.skill_id).ready,
                )
            )
        result.append(MilestoneProgress(milestone.id, milestone.order, milestone.title, milestone.description, steps))
    current = next((i for i, m in enumerate(result) if not m.complete), None)
    return PathProgress(result, current)


def goal_context(
    goal: LearningGoal, snapshot: LearnerSnapshot, milestones: list[PathMilestone] | None = None
) -> GoalContext:
    relevance: dict[int, float] = {}
    milestone_titles: dict[int, str] = {}
    focus_ids = {s.id for s in goal.focus_skills.all()} & set(snapshot.skills)
    progress = None
    current_ids: set[int] = set()

    if goal.path_version_id:
        if milestones is None:
            milestones = load_milestones(goal.path_version_id)
        progress = path_progress(milestones, snapshot)
        current = progress.current_index
        for index, milestone in enumerate(progress.milestones):
            if milestone.complete:
                weight = RELEVANCE_COMPLETED_MILESTONE
            elif current is not None and index == current:
                weight = RELEVANCE_CURRENT_MILESTONE
                current_ids.update(step.skill_id for step in milestone.steps)
            elif current is not None and index == current + 1:
                weight = RELEVANCE_NEXT_MILESTONE
            else:
                weight = RELEVANCE_LATER_MILESTONE
            for step in milestone.steps:
                if step.skill_id not in snapshot.skills:
                    continue
                relevance[step.skill_id] = max(relevance.get(step.skill_id, 0.0), weight)
                milestone_titles.setdefault(step.skill_id, milestone.title)

    for skill_id in focus_ids:
        relevance[skill_id] = RELEVANCE_FOCUS

    scope = set(relevance)
    graph = snapshot.graph
    # Prerequisites outside the path inherit half the relevance of what they unlock.
    for skill_id in list(scope):
        for ancestor in graph.ancestors(skill_id):
            if ancestor in snapshot.skills and ancestor not in scope:
                inherited = 0.5 * relevance[skill_id]
                relevance[ancestor] = max(relevance.get(ancestor, 0.0), inherited)

    # Previously practised skills stay reviewable even when outside the goal.
    for skill_id in snapshot.reviews:
        if skill_id in snapshot.skills and skill_id not in relevance:
            relevance[skill_id] = RELEVANCE_REVIEW_ONLY

    importance = graph.dependency_importance(scope or None)

    # Only near-term targets (focus skills, current and next milestone) count as "blocked".
    blocking: dict[int, list[str]] = {}
    for skill_id in scope:
        if relevance[skill_id] < RELEVANCE_NEXT_MILESTONE:
            continue
        ready = snapshot.readiness(skill_id)
        if ready.ready:
            continue
        name = snapshot.skills[skill_id].name
        for prereq in ready.missing_required:
            blocking.setdefault(prereq, []).append(name)

    return GoalContext(
        goal=goal,
        progress=progress,
        relevance=relevance,
        milestone_titles=milestone_titles,
        dependency_importance={k: importance.get(k, 0.0) for k in relevance},
        blocking_for={k: tuple(sorted(v)) for k, v in blocking.items()},
        focus_ids=focus_ids,
        current_milestone_ids=current_ids & set(snapshot.skills),
    )
