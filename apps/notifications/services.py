from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)


def notify(
    user,
    *,
    kind: str,
    title: str,
    dedupe_key: str,
    body: str = "",
    url: str = "",
    data: dict | None = None,
    email: bool = False,
) -> Notification:
    """Create an in-app notification once per dedupe key, optionally emailing it.

    `data` carries structured details for the email template. Email is only
    queued for active accounts with a verified address; the caller is
    responsible for checking the relevant user preference.
    """
    try:
        with transaction.atomic():
            notification, created = Notification.objects.get_or_create(
                user=user,
                dedupe_key=dedupe_key,
                defaults={
                    "kind": kind,
                    "title": title[:160],
                    "body": body[:500],
                    "url": url[:300],
                    "data": data or {},
                },
            )
    except IntegrityError:
        return Notification.objects.get(user=user, dedupe_key=dedupe_key)
    if not created or not email:
        return notification

    if not user.is_active or not user.is_email_verified:
        notification.email_status = Notification.EmailStatus.SKIPPED
        notification.email_error = "Email address not verified."
        notification.save(update_fields=["email_status", "email_error"])
        return notification

    notification.email_status = Notification.EmailStatus.PENDING
    notification.save(update_fields=["email_status"])
    from .tasks import deliver_notification_email

    notification_id = notification.pk
    transaction.on_commit(lambda: deliver_notification_email.delay(notification_id))
    return notification


def mark_read(user, notification_id: int | None = None) -> int:
    queryset = Notification.objects.filter(user=user, read_at__isnull=True)
    if notification_id is not None:
        queryset = queryset.filter(pk=notification_id)
    return queryset.update(read_at=timezone.now())
