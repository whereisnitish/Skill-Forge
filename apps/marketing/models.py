from __future__ import annotations

from django.conf import settings
from django.db import models


class ContactMessage(models.Model):
    class Topic(models.TextChoices):
        SUPPORT = "support", "Product support"
        BILLING = "billing", "Billing"
        TEAMS = "teams", "Teams plan"
        PRIVACY = "privacy", "Privacy request"
        OTHER = "other", "Something else"

    name = models.CharField(max_length=100)
    email = models.EmailField()
    topic = models.CharField(max_length=12, choices=Topic.choices, default=Topic.SUPPORT)
    message = models.TextField(max_length=4000)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_topic_display()} from {self.email}"
