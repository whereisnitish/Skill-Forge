from __future__ import annotations

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """In-app notification with optional email delivery.

    `dedupe_key` is unique per user (e.g. ``daily:2026-10-22``), so scheduler
    retries or overlapping runs can never create a second reminder.
    """

    class Kind(models.TextChoices):
        DAILY_REMINDER = "daily_reminder", "Daily reminder"
        REVIEW_DUE = "review_due", "Reviews due"
        MILESTONE = "milestone", "Milestone"
        ACHIEVEMENT = "achievement", "Achievement"
        ACCOUNT = "account", "Account"
        BILLING = "billing", "Billing"

    class EmailStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True)
    # Structured details for the email template (e.g. today's challenge, due skills). No secrets.
    data = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(max_length=16, choices=EmailStatus.choices, default=EmailStatus.NOT_REQUESTED)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_attempts = models.PositiveSmallIntegerField(default=0)
    email_error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "dedupe_key"], name="unique_notification_dedupe"),
        ]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self) -> str:
        return self.title
