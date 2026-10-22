"""Account email tasks.

Tokens are generated inside the task from the user's current state, so no
secret-bearing link ever passes through the message broker.
"""

from __future__ import annotations

import logging
import smtplib

from celery import shared_task
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.emails import send_templated_email

from .models import User
from .tokens import email_verification_token

logger = logging.getLogger(__name__)

RETRYABLE = (smtplib.SMTPException, ConnectionError, TimeoutError, OSError)

SIGNUP_NEXT_STEPS = [
    ("Tell us your goal and your daily time", "Pick a track and take a two-minute placement check."),
    ("Get one focused challenge at a time", "Each one is chosen from your latest answers — and we say why."),
    ("Review just before you'd forget", "Spaced reviews turn practice into skills that stick."),
]


@shared_task(
    bind=True,
    autoretry_for=RETRYABLE,
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def send_verification_email(self, user_id: int, reason: str = "signup") -> str:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return "missing"
    if user.is_email_verified:
        return "already-verified"
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    context = {"user": user, "verify_url": settings.SITE_URL + reverse("accounts:verify_email", args=[uid, token])}
    if reason == "change":
        template = "verify_email_change"
        context["password_reset_url"] = settings.SITE_URL + reverse("accounts:password_reset")
    else:
        template = "verify_email"
        context["next_steps"] = SIGNUP_NEXT_STEPS
    send_templated_email(user.email, template, context)
    logger.info("email.verification_sent", extra={"user_id": user.pk, "reason": reason})
    return "sent"


@shared_task(
    bind=True,
    autoretry_for=RETRYABLE,
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def send_password_reset_email(self, user_id: int) -> str:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not user.has_usable_password():
        return "skipped"
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = settings.SITE_URL + reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    send_templated_email(user.email, "password_reset", {"user": user, "reset_url": url})
    logger.info("email.password_reset_sent", extra={"user_id": user.pk})
    return "sent"
