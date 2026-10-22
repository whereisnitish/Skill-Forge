"""Data for the Today dashboard — all derived from persisted records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from apps.catalog.models import Challenge
from apps.core.timeutils import day_bounds, local_now, user_zone
from apps.engine.progress import streaks

from ..models import LearningAttempt, ReviewSchedule, SkillEvidence, UserAchievement
from .achievements import ACHIEVEMENTS
from .planning import PathProgress, path_progress
from .sessions import TodayPlan, primary_goal, today_plan
from .snapshot import LearnerSnapshot, MasteryView


@dataclass(frozen=True)
class DueReview:
    skill_id: int
    skill_slug: str
    skill_name: str
    due_at: datetime
    overdue: bool


@dataclass(frozen=True)
class DayActivity:
    day: date
    label: str
    attempts: int
    passed: int
    minutes: int
    is_today: bool
    height: int = 0  # bar height as % of the busiest day this week


@dataclass
class Dashboard:
    greeting: str
    plan: TodayPlan
    goal: object | None
    progress: PathProgress | None
    current_mastery: MasteryView | None
    due_reviews: list[DueReview]
    upcoming_reviews: list[DueReview]
    streak: int
    longest_streak: int
    practised_today: bool
    week: list[DayActivity]
    recent_evidence: list[SkillEvidence]
    achievements: list[tuple[UserAchievement, object]]
    total_attempts: int
    has_history: bool
    week_minutes: int = 0
    week_attempts: int = 0
    milestones_done: int = 0
    extra: dict = field(default_factory=dict)


def greeting_for(local: datetime, name: str) -> str:
    hour = local.hour
    part = "Good morning" if 5 <= hour < 12 else "Good afternoon" if 12 <= hour < 18 else "Good evening"
    return f"{part}, {name}"


def due_reviews(user, *, now: datetime, limit: int = 6) -> tuple[list[DueReview], list[DueReview]]:
    zone = user_zone(user)
    today = now.astimezone(zone).date()
    _, day_end = day_bounds(today, zone)
    rows = (
        ReviewSchedule.objects.filter(user=user, skill__is_active=True, due_at__lte=day_end + timedelta(days=7))
        .select_related("skill")
        .order_by("due_at")[: limit * 3]
    )
    due, upcoming = [], []
    for row in rows:
        item = DueReview(row.skill_id, row.skill.slug, row.skill.name, row.due_at, row.due_at <= now)
        (due if row.due_at <= day_end else upcoming).append(item)
    return due[:limit], upcoming[:limit]


def week_activity(user, *, now: datetime) -> list[DayActivity]:
    today = local_now(user, now).date()
    start = today - timedelta(days=6)
    rows = (
        LearningAttempt.objects.filter(user=user, local_date__gte=start, local_date__lte=today)
        .values("local_date")
        .annotate(
            n=Count("id"),
            passed=Count("id", filter=Q(evaluation__passed=True)),
            seconds=Sum("time_spent_seconds"),
        )
    )
    by_day = {r["local_date"]: r for r in rows}
    busiest = max((r["n"] for r in rows), default=0)
    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        row = by_day.get(day, {})
        attempts = row.get("n", 0)
        days.append(
            DayActivity(
                day=day,
                label=day.strftime("%a"),
                attempts=attempts,
                passed=row.get("passed", 0),
                minutes=round((row.get("seconds") or 0) / 60),
                is_today=day == today,
                height=round(100 * attempts / busiest) if busiest else 0,
            )
        )
    return days


def build_dashboard(user, *, now: datetime | None = None) -> Dashboard:
    now = now or timezone.now()
    plan = today_plan(user, now=now)
    goal = primary_goal(user)
    snapshot = LearnerSnapshot.load(user, now=now, level=goal.experience_level if goal else None)

    progress = None
    if goal is not None and goal.path_version_id:
        from .planning import load_milestones

        progress = path_progress(load_milestones(goal.path_version_id), snapshot)

    current_mastery = None
    if plan.current is not None:
        current_mastery = snapshot.view(plan.current.challenge.skill_id)

    due, upcoming = due_reviews(user, now=now)
    active_days = LearningAttempt.objects.filter(user=user).values_list("local_date", flat=True).distinct()
    today = local_now(user, now).date()
    day_list = list(active_days)
    current_streak, longest = streaks(day_list, today)
    week = week_activity(user, now=now)
    recent = list(
        SkillEvidence.objects.filter(user=user, weight__gte=1.0)
        .select_related("skill", "attempt__challenge_version")
        .order_by("-created_at")[:5]
    )
    achievements = [
        (a, ACHIEVEMENTS.get(a.code)) for a in UserAchievement.objects.filter(user=user).order_by("-earned_at")[:4]
    ]
    total = LearningAttempt.objects.filter(user=user).count()
    return Dashboard(
        greeting=greeting_for(local_now(user, now), user.friendly_name),
        plan=plan,
        goal=goal,
        progress=progress,
        current_mastery=current_mastery,
        due_reviews=due,
        upcoming_reviews=upcoming,
        streak=current_streak,
        longest_streak=longest,
        practised_today=today in set(day_list),
        week=week,
        recent_evidence=recent,
        achievements=achievements,
        total_attempts=total,
        has_history=total > 0,
        week_minutes=sum(d.minutes for d in week),
        week_attempts=sum(d.attempts for d in week),
        milestones_done=goal.milestone_completions.count() if goal else 0,
    )


def review_challenge_for(user, skill_id: int, *, now: datetime | None = None) -> Challenge | None:
    """Pick a challenge to review a skill: prefer ones not seen recently, and not the last one used."""
    from apps.evaluation.registry import unavailable_kinds

    now = now or timezone.now()
    challenges = list(Challenge.objects.published().filter(skill_id=skill_id).exclude(kind__in=unavailable_kinds()))
    if not challenges:
        return None
    last_seen = dict(
        LearningAttempt.objects.filter(user=user, challenge__in=challenges)
        .values("challenge_id")
        .annotate(last=Max("submitted_at"))
        .values_list("challenge_id", "last")
    )
    epoch = datetime(2000, 1, 1, tzinfo=now.tzinfo)
    challenges.sort(key=lambda c: (last_seen.get(c.id) or epoch, c.difficulty))
    return challenges[0]
