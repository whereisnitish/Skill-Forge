from __future__ import annotations

from django.conf import settings
from django.db import models


class OnboardingState(models.Model):
    """Persisted wizard progress so learners can leave and resume."""

    STEPS = ("goal", "experience", "time", "preferences", "plan")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding")
    step = models.CharField(max_length=20, default="goal")
    data = models.JSONField(default=dict, blank=True)
    diagnostic_challenge_ids = models.JSONField(default=list, blank=True)
    diagnostic_completed = models.BooleanField(default=False)
    goal = models.ForeignKey(
        "learning.LearningGoal", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Onboarding for {self.user} ({self.step})"

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None

    @property
    def step_index(self) -> int:
        return self.STEPS.index(self.step) + 1 if self.step in self.STEPS else 1
