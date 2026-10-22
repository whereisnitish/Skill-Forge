"""Daily sessions: one plan per learner per local day, filled one recommendation at a time.

Only the *next* recommendation is materialised. When it is completed or
skipped, the following one is selected from the freshly updated learner state,
so each pick reflects the most recent evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.timeutils import local_date

from ..models import LearningEvent, LearningGoal, LearningSession, Recommendation
from .recommendations import create_recommendation


@dataclass
class TodayPlan:
    session: LearningSession | None
    current: Recommendation | None
    completed: list[Recommendation]
    minutes_used: int
    minutes_budget: int
    exhausted: bool  # nothing eligible to recommend right now

    @property
    def is_complete(self) -> bool:
        return self.session is not None and self.current is None and self.minutes_used >= self.minutes_budget

    @property
    def progress(self) -> float:
        if not self.minutes_budget:
            return 0.0
        return min(1.0, self.minutes_used / self.minutes_budget)


def primary_goal(user) -> LearningGoal | None:
    return (
        LearningGoal.objects.filter(user=user, is_primary=True, status=LearningGoal.Status.ACTIVE)
        .select_related("path", "path_version")
        .first()
    )


def _budget(goal: LearningGoal, user) -> int:
    return goal.daily_minutes or user.profile.daily_minutes


def ensure_session(user, *, now: datetime | None = None) -> LearningSession | None:
    goal = primary_goal(user)
    if goal is None:
        return None
    now = now or timezone.now()
    today = local_date(user, now)
    try:
        with transaction.atomic():
            session, created = LearningSession.objects.get_or_create(
                user=user, local_date=today, defaults={"goal": goal, "minutes_budget": _budget(goal, user)}
            )
    except IntegrityError:
        session = LearningSession.objects.get(user=user, local_date=today)
        created = False
    if not created and session.goal_id != goal.pk:
        session.goal = goal
        session.save(update_fields=["goal", "updated_at"])
    if created:
        Recommendation.objects.filter(
            user=user, status=Recommendation.Status.PENDING, session__local_date__lt=today
        ).update(status=Recommendation.Status.EXPIRED, resolved_at=now)
    session.goal = goal
    return session


def _minutes_used(recommendations: list[Recommendation]) -> int:
    return sum(r.challenge.estimated_minutes for r in recommendations if r.status == Recommendation.Status.COMPLETED)


def today_plan(user, *, now: datetime | None = None, generate: bool = True) -> TodayPlan:
    now = now or timezone.now()
    session = ensure_session(user, now=now)
    if session is None:
        return TodayPlan(None, None, [], 0, user.profile.daily_minutes, exhausted=False)

    recs = list(session.recommendations.select_related("challenge__skill", "challenge_version"))
    pending = [r for r in recs if r.status == Recommendation.Status.PENDING]
    completed = [r for r in recs if r.status == Recommendation.Status.COMPLETED]
    used = _minutes_used(recs)
    current = pending[0] if pending else None
    exhausted = False

    limit = settings.SKILLFORGE_ENGINE["MAX_DAILY_RECOMMENDATIONS"]
    if current is None and generate and used < session.minutes_budget and len(recs) < limit:
        current = create_recommendation(session, now=now)
        exhausted = current is None
    if current is not None and current.status != Recommendation.Status.PENDING:
        current = None

    if current is None and used >= session.minutes_budget and session.status != LearningSession.Status.COMPLETED:
        session.status = LearningSession.Status.COMPLETED
        session.completed_at = now
        session.save(update_fields=["status", "completed_at", "updated_at"])

    return TodayPlan(session, current, completed, used, session.minutes_budget, exhausted)


def practice_more(user, *, now: datetime | None = None) -> Recommendation | None:
    """Add one extra recommendation beyond today's time budget."""
    now = now or timezone.now()
    session = ensure_session(user, now=now)
    if session is None:
        return None
    pending = session.recommendations.filter(status=Recommendation.Status.PENDING).first()
    if pending:
        return pending
    return create_recommendation(session, now=now)


def skip_recommendation(recommendation: Recommendation, *, now: datetime | None = None) -> None:
    now = now or timezone.now()
    with transaction.atomic():
        updated = Recommendation.objects.filter(pk=recommendation.pk, status=Recommendation.Status.PENDING).update(
            status=Recommendation.Status.SKIPPED, resolved_at=now
        )
        if updated:
            LearningEvent.objects.create(
                user=recommendation.user,
                event_type=LearningEvent.Type.RECOMMENDATION_SKIPPED,
                skill_id=recommendation.challenge.skill_id,
                payload={"recommendation_id": recommendation.pk},
            )


def expire_pending_for_goal(goal: LearningGoal, *, now: datetime | None = None) -> int:
    """Drop not-yet-started recommendations so the next pick uses the goal's new settings."""
    return Recommendation.objects.filter(
        user=goal.user, session__goal=goal, status=Recommendation.Status.PENDING, attempts__isnull=True
    ).update(status=Recommendation.Status.EXPIRED, resolved_at=now or timezone.now())


def refresh_today_budget(user, *, now: datetime | None = None) -> None:
    now = now or timezone.now()
    goal = primary_goal(user)
    if goal is None:
        return
    LearningSession.objects.filter(user=user, local_date=local_date(user, now)).update(
        minutes_budget=_budget(goal, user)
    )
    expire_pending_for_goal(goal, now=now)
