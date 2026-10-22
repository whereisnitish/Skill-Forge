"""Learning goal lifecycle. Changes affect future recommendations only; history is untouched."""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import LearningPath, Skill

from ..models import LearningEvent, LearningGoal
from .sessions import expire_pending_for_goal

TRACKED_FIELDS = ("title", "path_id", "experience_level", "daily_minutes", "target_date", "motivation")


def default_path_for(goal_type: str) -> LearningPath | None:
    return (
        LearningPath.objects.filter(goal_type=goal_type, is_active=True, is_default_for_goal=True)
        .select_related("current_version")
        .first()
    )


def _promote_another(user, exclude_id: int) -> None:
    candidate = (
        LearningGoal.objects.filter(user=user, status=LearningGoal.Status.ACTIVE)
        .exclude(pk=exclude_id)
        .order_by("-updated_at")
        .first()
    )
    if candidate is not None:
        candidate.is_primary = True
        candidate.save(update_fields=["is_primary", "updated_at"])


@transaction.atomic
def make_primary(goal: LearningGoal) -> LearningGoal:
    if goal.status != LearningGoal.Status.ACTIVE:
        raise ValueError("Only active goals can be your current focus.")
    previous = list(
        LearningGoal.objects.select_for_update().filter(user=goal.user, is_primary=True).exclude(pk=goal.pk)
    )
    LearningGoal.objects.filter(pk__in=[g.pk for g in previous]).update(is_primary=False)
    for old in previous:
        expire_pending_for_goal(old)
    goal.is_primary = True
    goal.save(update_fields=["is_primary", "updated_at"])
    return goal


@transaction.atomic
def create_goal(
    user,
    *,
    title: str,
    goal_type: str,
    experience_level: str,
    daily_minutes: int,
    path: LearningPath | None = None,
    target_date: date | None = None,
    motivation: str = "",
    focus_skills: list[Skill] | tuple = (),
    primary: bool | None = None,
) -> LearningGoal:
    goal = LearningGoal.objects.create(
        user=user,
        title=title,
        goal_type=goal_type,
        path=path,
        path_version=path.current_version if path else None,
        experience_level=experience_level,
        daily_minutes=daily_minutes,
        target_date=target_date,
        motivation=motivation,
        status=LearningGoal.Status.ACTIVE,
    )
    if focus_skills:
        goal.focus_skills.set(focus_skills)
    has_primary = LearningGoal.objects.filter(user=user, is_primary=True).exclude(pk=goal.pk).exists()
    if primary or (primary is None and not has_primary):
        make_primary(goal)
    LearningEvent.objects.create(
        user=user,
        event_type=LearningEvent.Type.GOAL_CREATED,
        goal=goal,
        payload={"goal_type": goal_type, "path": path.slug if path else None},
    )
    return goal


@transaction.atomic
def update_goal(goal: LearningGoal, *, changes: dict, focus_skills: list[Skill] | None = None) -> LearningGoal:
    before = {field: getattr(goal, field) for field in TRACKED_FIELDS}
    path = changes.pop("path", goal.path) if "path" in changes else goal.path
    for key, value in changes.items():
        setattr(goal, key, value)
    if path != goal.path or (path and goal.path_version_id is None):
        goal.path = path
        goal.path_version = path.current_version if path else None
    goal.save()
    focus_changed = False
    if focus_skills is not None:
        old_focus = set(goal.focus_skills.values_list("id", flat=True))
        goal.focus_skills.set(focus_skills)
        focus_changed = old_focus != {s.pk for s in focus_skills}
    changed = [f for f in TRACKED_FIELDS if getattr(goal, f) != before[f]]
    if focus_changed:
        changed.append("focus_skills")
    if changed:
        LearningEvent.objects.create(
            user=goal.user,
            event_type=LearningEvent.Type.GOAL_UPDATED,
            goal=goal,
            payload={"changed": changed},
        )
        expire_pending_for_goal(goal)
        if goal.is_primary and "daily_minutes" in changed:
            from .sessions import refresh_today_budget

            refresh_today_budget(goal.user)
    return goal


@transaction.atomic
def upgrade_path_version(goal: LearningGoal) -> bool:
    """Move a goal onto the latest published version of its path (history is unaffected)."""
    if not goal.path_id or not goal.path.current_version_id or goal.path_version_id == goal.path.current_version_id:
        return False
    previous = goal.path_version.number if goal.path_version_id else None
    goal.path_version = goal.path.current_version
    goal.save(update_fields=["path_version", "updated_at"])
    LearningEvent.objects.create(
        user=goal.user,
        event_type=LearningEvent.Type.GOAL_UPDATED,
        goal=goal,
        payload={"changed": ["path_version"], "from": previous, "to": goal.path_version.number},
    )
    expire_pending_for_goal(goal)
    return True


@transaction.atomic
def set_goal_status(goal: LearningGoal, status: str) -> LearningGoal:
    if status not in LearningGoal.Status.values:
        raise ValueError("Unknown status.")
    if status == goal.status:
        return goal
    previous = goal.status
    goal.status = status
    goal.status_changed_at = timezone.now()
    was_primary = goal.is_primary
    if status != LearningGoal.Status.ACTIVE:
        goal.is_primary = False
    goal.save(update_fields=["status", "status_changed_at", "is_primary", "updated_at"])
    if status != LearningGoal.Status.ACTIVE:
        expire_pending_for_goal(goal)
        if was_primary:
            _promote_another(goal.user, goal.pk)
    elif not LearningGoal.objects.filter(user=goal.user, is_primary=True).exists():
        make_primary(goal)
    LearningEvent.objects.create(
        user=goal.user,
        event_type=LearningEvent.Type.GOAL_STATUS_CHANGED,
        goal=goal,
        payload={"from": previous, "to": status},
    )
    return goal
