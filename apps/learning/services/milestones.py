from __future__ import annotations

from datetime import datetime

from django.db import IntegrityError, transaction
from django.urls import reverse

from ..models import LearningEvent, LearningGoal, MilestoneCompletion
from .planning import load_milestones, path_progress
from .snapshot import LearnerSnapshot


def check_milestones(goal: LearningGoal, *, now: datetime) -> list[int]:
    """Record newly completed milestones for a goal's pinned path version."""
    if not goal.path_version_id:
        return []
    milestones = load_milestones(goal.path_version_id)
    snapshot = LearnerSnapshot.load(goal.user, now=now, level=goal.experience_level)
    progress = path_progress(milestones, snapshot)
    done = set(MilestoneCompletion.objects.filter(goal=goal).values_list("milestone_id", flat=True))
    completed: list[int] = []
    for milestone in progress.milestones:
        if not milestone.complete or milestone.id in done:
            continue
        try:
            with transaction.atomic():
                MilestoneCompletion.objects.create(
                    user=goal.user, goal=goal, milestone_id=milestone.id, completed_at=now
                )
        except IntegrityError:
            continue
        completed.append(milestone.id)
        LearningEvent.objects.create(
            user=goal.user,
            event_type=LearningEvent.Type.MILESTONE_COMPLETED,
            goal=goal,
            occurred_at=now,
            payload={"milestone_id": milestone.id, "title": milestone.title},
        )
        from apps.notifications.models import Notification
        from apps.notifications.services import notify

        total = len(progress.milestones)
        finished = len(done) + len(completed)
        upcoming = next((m for m in progress.milestones if not m.complete and m.id not in done), None)
        notify(
            goal.user,
            kind=Notification.Kind.MILESTONE,
            title=f"Milestone complete: {milestone.title}",
            body=f"You've completed a milestone on your {goal.title} goal.",
            url=reverse("learning:goal_detail", args=[goal.pk]),
            data={
                "milestone": milestone.title,
                "goal": goal.title,
                "path": goal.path.name if goal.path_id else "",
                "completed": finished,
                "total": total,
                "percent": round(100 * finished / total) if total else 0,
                "next": upcoming.title if upcoming else "",
            },
            dedupe_key=f"milestone:{goal.pk}:{milestone.id}",
            email=goal.user.profile.milestone_emails_enabled,
        )
    return completed
