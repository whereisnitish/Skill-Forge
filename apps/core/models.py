from __future__ import annotations

from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TaskFailure(models.Model):
    """A background task that raised after exhausting its retries.

    Visible in the admin so operators can spot failing jobs without trawling
    logs. Only identifiers and exception summaries are stored, never payloads.
    """

    task_name = models.CharField(max_length=200, db_index=True)
    task_id = models.CharField(max_length=100, db_index=True)
    exception_type = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.task_name} ({self.exception_type})"
