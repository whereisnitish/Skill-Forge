from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.billing.entitlements import has_feature
from apps.catalog.constants import ChallengeKind
from apps.catalog.models import Challenge, LearningPath, Skill
from apps.evaluation.base import InvalidResponse
from apps.learning.models import LearningAttempt, LearningEvent
from apps.learning.services.attempts import submit_attempt
from apps.learning.services.goals import create_goal, default_path_for
from apps.learning.services.planning import load_milestones

from .models import OnboardingState

logger = logging.getLogger(__name__)

DIAGNOSTIC_QUESTIONS = 5
SKIP_VALUE = "__skip__"


def get_state(user) -> OnboardingState:
    state, _ = OnboardingState.objects.get_or_create(user=user)
    return state


def save_step(state: OnboardingState, next_step: str, **data) -> None:
    """Persist answers so far and remember where to resume."""
    state.data = {**state.data, **data}
    state.step = next_step
    state.save(update_fields=["data", "step", "updated_at"])


def available_paths(user, goal_type: str) -> list[LearningPath]:
    paths = list(
        LearningPath.objects.filter(goal_type=goal_type, is_active=True, current_version__isnull=False).order_by(
            "-is_default_for_goal", "order"
        )
    )
    if not has_feature(user, "premium_paths"):
        paths = [p for p in paths if not p.is_premium]
    return paths


def path_skills(path: LearningPath) -> list[Skill]:
    skills: list[Skill] = []
    for milestone in load_milestones(path.current_version_id):
        for step in sorted(milestone.steps.all(), key=lambda s: s.order):
            if step.skill not in skills:
                skills.append(step.skill)
    return skills


def diagnostic_challenges(goal_type: str, limit: int = DIAGNOSTIC_QUESTIONS) -> list[Challenge]:
    """Placement questions spread across the path's milestones (deliberately ignoring prerequisites)."""
    path = default_path_for(goal_type)
    if path is None or path.current_version_id is None:
        return []
    milestones = load_milestones(path.current_version_id)
    queues = [[step.skill_id for step in sorted(m.steps.all(), key=lambda s: s.order)] for m in milestones]
    order: list[int] = []
    while any(queues) and len(order) < limit * 2:
        for queue in queues:
            if queue:
                skill_id = queue.pop(0)
                if skill_id not in order:
                    order.append(skill_id)
    challenges = {
        c.skill_id: c
        for c in Challenge.objects.published()
        .filter(skill_id__in=order, kind=ChallengeKind.MULTIPLE_CHOICE, is_diagnostic=True)
        .select_related("current_version", "skill")
        .order_by("difficulty")
    }
    return [challenges[s] for s in order if s in challenges][:limit]


def record_diagnostic(user, challenges: list[Challenge], answers: dict[int, str]) -> dict:
    """Submit each answered placement question as a real, evaluated diagnostic attempt."""
    results = {"answered": 0, "correct": 0, "skipped": 0}
    for challenge in challenges:
        choice = answers.get(challenge.pk)
        if not choice or choice == SKIP_VALUE:
            results["skipped"] += 1
            continue
        if LearningAttempt.objects.filter(user=user, challenge=challenge, is_diagnostic=True).exists():
            continue
        try:
            attempt = submit_attempt(
                user, challenge.current_version, {"selected": [choice]}, is_diagnostic=True, enforce_limits=False
            )
        except InvalidResponse:
            results["skipped"] += 1
            continue
        results["answered"] += 1
        evaluation = getattr(attempt, "evaluation", None)
        if evaluation is not None and evaluation.passed:
            results["correct"] += 1
    return results


@transaction.atomic
def complete_onboarding(
    user, state: OnboardingState, *, title: str, path: LearningPath, focus_slugs: list[str], target_date
):
    data = state.data
    profile = user.profile
    profile.experience_level = data.get("level", profile.experience_level)
    profile.daily_minutes = int(data.get("daily_minutes", profile.daily_minutes))
    profile.preferred_formats = list(data.get("formats", []))
    profile.save()
    goal = create_goal(
        user,
        title=title,
        goal_type=data["goal_type"],
        path=path,
        experience_level=profile.experience_level,
        daily_minutes=profile.daily_minutes,
        target_date=target_date,
        focus_skills=list(Skill.objects.filter(slug__in=focus_slugs, is_active=True)),
        primary=True,
    )
    LearningAttempt.objects.filter(user=user, is_diagnostic=True, goal__isnull=True).update(goal=goal)
    state.goal = goal
    state.step = "plan"
    state.completed_at = timezone.now()
    state.save(update_fields=["goal", "step", "completed_at", "updated_at"])
    LearningEvent.objects.create(
        user=user,
        event_type=LearningEvent.Type.ONBOARDING_COMPLETED,
        goal=goal,
        payload={"goal_type": data["goal_type"], "path": path.slug, "diagnostic": data.get("diagnostic", {})},
    )
    logger.info("onboarding.completed", extra={"user_id": user.pk, "goal_id": goal.pk})
    return goal
