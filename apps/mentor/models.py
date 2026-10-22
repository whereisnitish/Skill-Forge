from __future__ import annotations

from django.conf import settings
from django.db import models


class MentorRequest(models.Model):
    """A request to the AI mentor and its validated result.

    The learner's own question and the structured response are stored so they
    can revisit it; application logs only ever record ids, timings and token
    counts.
    """

    class Kind(models.TextChoices):
        EXPLAIN_FAILURE = "explain_failure", "Explain my mistake"
        EXPLAIN_CONCEPT = "explain_concept", "Explain the concept"
        NEXT_STEPS = "next_steps", "Suggest follow-up practice"
        MISTAKE_SUMMARY = "mistake_summary", "Summarise my recurring mistakes"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        LIVE = "live", "AI model"
        FALLBACK = "fallback", "Curated guidance"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mentor_requests")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    attempt = models.ForeignKey(
        "learning.LearningAttempt", on_delete=models.CASCADE, null=True, blank=True, related_name="mentor_requests"
    )
    skill = models.ForeignKey(
        "catalog.Skill", on_delete=models.SET_NULL, null=True, blank=True, related_name="mentor_requests"
    )
    question = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=12, choices=Source.choices, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    model = models.CharField(max_length=80, blank=True)
    response = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"]), models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.kind} ({self.status})"
