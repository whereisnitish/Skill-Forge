from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.contrib.sessions.models import Session
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def cleanup_stale_data() -> dict:
    """Remove expired, non-essential records. Never touches attempts, evaluations or evidence."""
    from apps.learning.models import AttemptDraft, Recommendation
    from apps.mentor.models import MentorRequest
    from apps.notifications.models import Notification

    from .models import TaskFailure

    now = timezone.now()
    result = {
        "sessions": Session.objects.filter(expire_date__lt=now).delete()[0],
        "drafts": AttemptDraft.objects.filter(updated_at__lt=now - timedelta(days=30)).delete()[0],
        "recommendations_expired": Recommendation.objects.filter(
            status=Recommendation.Status.PENDING, created_at__lt=now - timedelta(days=2)
        ).update(status=Recommendation.Status.EXPIRED, resolved_at=now),
        "notifications": Notification.objects.filter(
            read_at__isnull=False, read_at__lt=now - timedelta(days=90)
        ).delete()[0],
        "stuck_mentor_requests": MentorRequest.objects.filter(
            status=MentorRequest.Status.PENDING, created_at__lt=now - timedelta(hours=1)
        ).update(status=MentorRequest.Status.FAILED, error_code="stale"),
        "task_failures": TaskFailure.objects.filter(resolved=True, occurred_at__lt=now - timedelta(days=30)).delete()[
            0
        ],
    }
    logger.info("cleanup.completed", extra=result)
    return result
