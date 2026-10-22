"""Reminder scheduling and email delivery.

Reminders run hourly and fire for users whose *local* hour matches their
chosen reminder hour. Duplicate prevention is enforced by the unique
(user, dedupe_key) constraint, so overlapping or retried runs are harmless.
Delivery claims a notification with a conditional UPDATE before sending, so
two workers can't both send the same email.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.emails import send_templated_email
from apps.core.timeutils import get_zone

from .content import daily_reminder_content, review_due_content
from .emails import UNSUBSCRIBE_SALT, build_notification_email, unsubscribe_token, unsubscribe_url
from .models import Notification
from .services import notify

__all__ = ["UNSUBSCRIBE_SALT", "unsubscribe_token", "unsubscribe_url"]

logger = logging.getLogger(__name__)

RETRYABLE = (smtplib.SMTPException, ConnectionError, TimeoutError, OSError)


@shared_task(bind=True, max_retries=5, acks_late=True)
def deliver_notification_email(self, notification_id: int) -> str:
    claimed = Notification.objects.filter(pk=notification_id, email_status=Notification.EmailStatus.PENDING).update(
        email_status=Notification.EmailStatus.SENDING
    )
    if not claimed:
        return "not-pending"
    notification = Notification.objects.select_related("user__profile").get(pk=notification_id)
    user = notification.user
    if not user.is_active:
        Notification.objects.filter(pk=notification_id).update(
            email_status=Notification.EmailStatus.SKIPPED, email_error="Account inactive."
        )
        return "skipped"
    template, context, headers = build_notification_email(notification)
    try:
        send_templated_email(user.email, template, context, headers=headers)
    except RETRYABLE as exc:
        attempts = notification.email_attempts + 1
        final = self.request.retries >= self.max_retries
        Notification.objects.filter(pk=notification_id).update(
            email_status=Notification.EmailStatus.FAILED if final else Notification.EmailStatus.PENDING,
            email_attempts=attempts,
            email_error=type(exc).__name__,
        )
        if final:
            raise
        raise self.retry(exc=exc, countdown=min(600, 30 * 2**self.request.retries)) from exc
    Notification.objects.filter(pk=notification_id).update(
        email_status=Notification.EmailStatus.SENT,
        email_sent_at=timezone.now(),
        email_attempts=notification.email_attempts + 1,
        email_error="",
    )
    logger.info(
        "notification.email_sent",
        extra={"notification_id": notification_id, "kind": notification.kind, "template": template},
    )
    return "sent"


def _local(now: datetime, tz_name: str) -> datetime:
    return now.astimezone(get_zone(tz_name))


@shared_task
def send_daily_reminders(now_iso: str | None = None) -> int:
    from apps.learning.models import LearningAttempt, LearningGoal

    now = datetime.fromisoformat(now_iso) if now_iso else timezone.now()
    users = (
        get_user_model()
        .objects.filter(is_active=True, profile__daily_reminder_enabled=True)
        .select_related("profile")
        .iterator(chunk_size=500)
    )
    sent = 0
    for user in users:
        local = _local(now, user.profile.timezone)
        if local.hour != user.profile.reminder_hour:
            continue
        dedupe_key = f"daily:{local.date().isoformat()}"
        if Notification.objects.filter(user=user, dedupe_key=dedupe_key).exists():
            sent += 1  # already reminded today (e.g. a retried run)
            continue
        if not LearningGoal.objects.filter(user=user, is_primary=True, status=LearningGoal.Status.ACTIVE).exists():
            continue
        if LearningAttempt.objects.filter(user=user, local_date=local.date()).exists():
            continue
        content = daily_reminder_content(user, now)
        notify(
            user,
            kind=Notification.Kind.DAILY_REMINDER,
            title=content.title,
            body=content.body,
            url=content.url,
            data=content.data,
            dedupe_key=dedupe_key,
            email=True,
        )
        sent += 1
    logger.info("reminders.daily", extra={"count": sent})
    return sent


@shared_task
def send_review_reminders(now_iso: str | None = None) -> int:
    now = datetime.fromisoformat(now_iso) if now_iso else timezone.now()
    users = (
        get_user_model()
        .objects.filter(is_active=True, profile__review_reminder_enabled=True, review_schedules__due_at__lte=now)
        .distinct()
        .select_related("profile")
        .iterator(chunk_size=500)
    )
    sent = 0
    for user in users:
        local = _local(now, user.profile.timezone)
        if local.hour != user.profile.reminder_hour:
            continue
        content = review_due_content(user, now)
        if content is None:
            continue
        notify(
            user,
            kind=Notification.Kind.REVIEW_DUE,
            title=content.title,
            body=content.body,
            url=content.url,
            data=content.data,
            dedupe_key=f"reviews:{local.date().isoformat()}",
            email=True,
        )
        sent += 1
    logger.info("reminders.reviews", extra={"count": sent})
    return sent
