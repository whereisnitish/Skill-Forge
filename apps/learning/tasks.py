from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.timeutils import get_zone
from apps.evaluation.runner import RunnerBusy, RunnerUnavailable

from .models import LearningAttempt, LearningGoal, LearningSession

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=4, acks_late=True, soft_time_limit=60, time_limit=90)
def evaluate_attempt_task(self, attempt_id: int) -> str:
    """Evaluate a queued attempt. Safe to run more than once (evaluation is idempotent)."""
    from .services.evaluation import evaluate_attempt

    try:
        evaluation = evaluate_attempt(attempt_id)
    except RunnerBusy as exc:
        raise self.retry(exc=exc, countdown=5 * 2**self.request.retries) from exc
    except RunnerUnavailable as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc
        return "unavailable"
    return evaluation.verdict if evaluation else "missing"


@shared_task
def retry_pending_evaluations(max_age_hours: int = 24) -> int:
    """Re-dispatch attempts still awaiting evaluation (e.g. runner outage)."""
    cutoff = timezone.now() - timedelta(minutes=5)
    oldest = timezone.now() - timedelta(hours=max_age_hours)
    ids = list(
        LearningAttempt.objects.filter(
            status=LearningAttempt.Status.QUEUED, submitted_at__lt=cutoff, submitted_at__gte=oldest
        ).values_list("id", flat=True)[:200]
    )
    for attempt_id in ids:
        evaluate_attempt_task.delay(attempt_id)
    return len(ids)


@shared_task
def prepare_daily_sessions(now_iso: str | None = None) -> int:
    """Pre-build today's first recommendation for learners whose local day just started.

    Purely an optimisation — the Today page builds the plan on demand too.
    The unique (user, local_date) constraint keeps repeated runs harmless.
    """
    from .services.sessions import today_plan

    now = datetime.fromisoformat(now_iso) if now_iso else timezone.now()
    user_ids = (
        LearningGoal.objects.filter(is_primary=True, status=LearningGoal.Status.ACTIVE)
        .values_list("user_id", flat=True)
        .distinct()
    )
    prepared = 0
    for user in get_user_model().objects.filter(pk__in=user_ids, is_active=True).select_related("profile"):
        local = now.astimezone(get_zone(user.profile.timezone))
        if not 4 <= local.hour < 5:
            continue
        if LearningSession.objects.filter(user=user, local_date=local.date()).exists():
            continue
        try:
            today_plan(user, now=now)
            prepared += 1
        except Exception:
            logger.exception("sessions.prepare_failed", extra={"user_id": user.pk})
    logger.info("sessions.prepared", extra={"count": prepared})
    return prepared
