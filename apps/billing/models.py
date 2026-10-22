from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q


class Subscription(models.Model):
    """The learner's plan. Paid states change only via verified provider webhooks."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIALING = "trialing", "Trialing"
        PAST_DUE = "past_due", "Past due"
        INCOMPLETE = "incomplete", "Incomplete"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    class Provider(models.TextChoices):
        NONE = "none", "None"
        DEV = "dev", "Development adapter"
        STRIPE = "stripe", "Stripe"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(max_length=20, default="free")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.NONE)
    provider_customer_id = models.CharField(max_length=100, blank=True)
    provider_subscription_id = models.CharField(max_length=100, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_subscription_id"],
                condition=~Q(provider_subscription_id=""),
                name="unique_provider_subscription",
            ),
        ]
        indexes = [models.Index(fields=["provider_customer_id"])]

    def __str__(self) -> str:
        return f"{self.user} · {self.plan} ({self.status})"


class UsageRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_records")
    feature = models.CharField(max_length=40)
    period = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "feature", "period"], name="unique_usage_period"),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.feature} {self.period}: {self.count}"


class WebhookEvent(models.Model):
    """Every provider event processed exactly once (unique on provider + event id)."""

    class Status(models.TextChoices):
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored"
        FAILED = "failed", "Failed"

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=80)
    status = models.CharField(max_length=12, choices=Status.choices)
    error = models.CharField(max_length=300, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="unique_webhook_event"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type} ({self.status})"
