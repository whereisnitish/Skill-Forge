from __future__ import annotations

import logging
import smtplib

from celery import shared_task
from django.conf import settings
from django.urls import reverse

from apps.core.emails import absolute_url, send_templated_email

from .models import ContactMessage

logger = logging.getLogger(__name__)

RETRYABLE = (smtplib.SMTPException, ConnectionError, TimeoutError, OSError)


@shared_task(
    bind=True,
    autoretry_for=RETRYABLE,
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def send_contact_notification(self, message_id: int) -> str:
    """Forward a contact-form message to the support inbox; replies go straight to the sender."""
    message = ContactMessage.objects.select_related("user").filter(pk=message_id).first()
    if message is None:
        return "missing"
    send_templated_email(
        settings.SUPPORT_EMAIL,
        "contact_received",
        {
            "message": message,
            "admin_url": absolute_url(reverse("admin:marketing_contactmessage_change", args=[message.pk])),
        },
        reply_to=[message.email],
    )
    logger.info("contact.notified", extra={"message_id": message.pk, "topic": message.topic})
    return "sent"
