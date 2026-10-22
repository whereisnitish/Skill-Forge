"""Build reminder notifications from the learner's real, current state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.urls import reverse

from apps.core.timeutils import day_bounds, get_zone

MAX_LISTED_SKILLS = 5


@dataclass
class NotificationContent:
    title: str
    body: str
    url: str
    data: dict = field(default_factory=dict)


def current_streak(user, today) -> int:
    from apps.engine.progress import streaks
    from apps.learning.models import LearningAttempt

    days = LearningAttempt.objects.filter(user=user).values_list("local_date", flat=True).distinct()
    return streaks(days, today)[0]


def daily_reminder_content(user, now: datetime) -> NotificationContent:
    """Today's actual recommendation (creating it if needed), why it was chosen, and the streak."""
    from apps.learning.services.sessions import today_plan

    local_today = now.astimezone(get_zone(user.profile.timezone)).date()
    plan = today_plan(user, now=now)
    data = {"budget": plan.minutes_budget, "streak": current_streak(user, local_today)}
    rec = plan.current
    if rec is None:
        return NotificationContent(
            title="Your daily practice is ready",
            body=f"A {plan.minutes_budget}-minute session is waiting for you.",
            url=reverse("learning:today"),
            data=data,
        )
    data.update(
        {
            "challenge_title": rec.challenge_version.title,
            "skill": rec.challenge.skill.name,
            "kind_label": rec.challenge.get_kind_display(),
            "minutes": rec.challenge.estimated_minutes,
            "reason": rec.reason_text,
            "reason_label": rec.reason_label,
        }
    )
    return NotificationContent(
        title=f"Today's challenge: {rec.challenge_version.title}",
        body=rec.reason_text,
        url=reverse("learning:challenge", args=[rec.challenge.slug]) + f"?rec={rec.pk}",
        data=data,
    )


def review_due_content(user, now: datetime) -> NotificationContent | None:
    """The skills due for review right now, or None when nothing is due."""
    from apps.learning.models import ReviewSchedule

    zone = get_zone(user.profile.timezone)
    day_start, _ = day_bounds(now.astimezone(zone).date(), zone)
    due = list(
        ReviewSchedule.objects.filter(user=user, skill__is_active=True, due_at__lte=now)
        .select_related("skill")
        .order_by("due_at")
    )
    if not due:
        return None
    count = len(due)
    data = {
        "count": count,
        "skills": [{"name": row.skill.name, "overdue": row.due_at < day_start} for row in due[:MAX_LISTED_SKILLS]],
        "more": max(0, count - MAX_LISTED_SKILLS),
    }
    names = ", ".join(skill["name"] for skill in data["skills"][:3])
    return NotificationContent(
        title=f"{count} skill{'s' if count != 1 else ''} due for review",
        body=f"Due now: {names}{'…' if count > 3 else ''}. A quick review keeps them from fading.",
        url=reverse("learning:reviews"),
        data=data,
    )
