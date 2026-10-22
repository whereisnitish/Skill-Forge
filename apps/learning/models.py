"""Learner state and history.

Attempts are append-only: the submitted response is frozen at creation and a
retry creates a new attempt. Mastery and review state are derived from
evaluated attempts and every change is backed by an evidence or review record.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.catalog.constants import GoalType
from apps.core.models import TimeStampedModel

User = settings.AUTH_USER_MODEL


class LearningGoal(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="goals")
    title = models.CharField(max_length=140)
    goal_type = models.CharField(max_length=20, choices=GoalType.choices)
    motivation = models.TextField(blank=True, max_length=600)
    path = models.ForeignKey(
        "catalog.LearningPath", on_delete=models.PROTECT, null=True, blank=True, related_name="goals"
    )
    path_version = models.ForeignKey(
        "catalog.LearningPathVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="goals"
    )
    experience_level = models.CharField(max_length=20, choices=Level.choices, default=Level.BEGINNER)
    daily_minutes = models.PositiveSmallIntegerField(default=15)
    target_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    is_primary = models.BooleanField(default=False)
    focus_skills = models.ManyToManyField("catalog.Skill", blank=True, related_name="focused_by_goals")
    status_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-is_primary", "status", "-updated_at"]
        indexes = [models.Index(fields=["user", "status"])]
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(is_primary=True), name="one_primary_goal_per_user"),
            models.CheckConstraint(
                condition=Q(daily_minutes__gte=5, daily_minutes__lte=120), name="goal_daily_minutes_range"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class LearningSession(TimeStampedModel):
    """A learner's plan for one local calendar day."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="learning_sessions")
    goal = models.ForeignKey(LearningGoal, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions")
    local_date = models.DateField()
    minutes_budget = models.PositiveSmallIntegerField(default=15)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-local_date"]
        constraints = [
            models.UniqueConstraint(fields=["user", "local_date"], name="one_session_per_user_day"),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.local_date}"


class Recommendation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"
        EXPIRED = "expired", "Expired"

    session = models.ForeignKey(LearningSession, on_delete=models.CASCADE, related_name="recommendations")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recommendations")
    challenge = models.ForeignKey("catalog.Challenge", on_delete=models.PROTECT, related_name="recommendations")
    challenge_version = models.ForeignKey(
        "catalog.ChallengeVersion", on_delete=models.PROTECT, related_name="recommendations"
    )
    position = models.PositiveSmallIntegerField()
    reason_code = models.CharField(max_length=40)
    reason_text = models.CharField(max_length=300)
    reason_data = models.JSONField(default=dict, blank=True)
    score = models.FloatField()
    strategy_version = models.CharField(max_length=40)
    is_review = models.BooleanField(default=False)
    explored = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["session", "position"]
        indexes = [models.Index(fields=["user", "status"])]
        constraints = [
            models.UniqueConstraint(fields=["session", "position"], name="unique_recommendation_slot"),
        ]

    def __str__(self) -> str:
        return f"{self.challenge} ({self.reason_code})"

    @property
    def reason_label(self) -> str:
        from apps.engine.explain import REASON_LABELS

        return REASON_LABELS.get(self.reason_code, "Recommended")


class AttemptDraft(models.Model):
    """Work in progress for a challenge version: autosaved response, hints and reveals."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attempt_drafts")
    challenge_version = models.ForeignKey("catalog.ChallengeVersion", on_delete=models.CASCADE, related_name="drafts")
    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.SET_NULL, null=True, blank=True, related_name="drafts"
    )
    response = models.JSONField(default=dict, blank=True)
    hints_revealed = models.PositiveSmallIntegerField(default=0)
    solution_revealed = models.BooleanField(default=False)
    started_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "challenge_version"], name="one_draft_per_version"),
        ]

    def __str__(self) -> str:
        return f"Draft by {self.user_id} for version {self.challenge_version_id}"


class LearningAttempt(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Awaiting evaluation"
        EVALUATED = "evaluated", "Evaluated"
        FAILED = "failed", "Evaluation failed"

    MUTABLE_FIELDS = frozenset({"status", "evaluation_error", "evaluation_attempts"})

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attempts")
    challenge = models.ForeignKey("catalog.Challenge", on_delete=models.PROTECT, related_name="attempts")
    challenge_version = models.ForeignKey("catalog.ChallengeVersion", on_delete=models.PROTECT, related_name="attempts")
    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts"
    )
    session = models.ForeignKey(
        LearningSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts"
    )
    goal = models.ForeignKey(LearningGoal, on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts")
    attempt_number = models.PositiveIntegerField(default=1)
    response = models.JSONField()
    hints_used = models.PositiveSmallIntegerField(default=0)
    hints_available = models.PositiveSmallIntegerField(default=0)
    solution_revealed = models.BooleanField(default=False)
    is_review = models.BooleanField(default=False)
    is_diagnostic = models.BooleanField(default=False)
    started_at = models.DateTimeField()
    submitted_at = models.DateTimeField(default=timezone.now)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    local_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    evaluation_error = models.CharField(max_length=300, blank=True)
    evaluation_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["user", "-submitted_at"]),
            models.Index(fields=["user", "local_date"]),
            models.Index(fields=["user", "challenge"]),
            models.Index(fields=["status", "submitted_at"]),
        ]

    def __str__(self) -> str:
        return f"Attempt {self.pk} on {self.challenge_id}"

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            update_fields = kwargs.get("update_fields")
            if not update_fields or not set(update_fields) <= self.MUTABLE_FIELDS:
                raise ValidationError("Attempts are immutable; only evaluation status may change.")
        super().save(*args, **kwargs)


class AttemptEvaluation(models.Model):
    class Verdict(models.TextChoices):
        CORRECT = "correct", "Correct"
        PARTIAL = "partial", "Partially correct"
        INCORRECT = "incorrect", "Incorrect"

    attempt = models.OneToOneField(LearningAttempt, on_delete=models.CASCADE, related_name="evaluation")
    score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    verdict = models.CharField(max_length=12, choices=Verdict.choices)
    passed = models.BooleanField()
    summary = models.CharField(max_length=300)
    feedback = models.JSONField(default=dict)
    misconceptions = models.JSONField(default=list, blank=True)
    evaluator_version = models.CharField(max_length=40)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(score__gte=0.0, score__lte=1.0), name="evaluation_score_range"),
        ]

    def __str__(self) -> str:
        return f"{self.verdict} ({self.score:.2f})"


class SkillMastery(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="skill_masteries")
    skill = models.ForeignKey("catalog.Skill", on_delete=models.CASCADE, related_name="masteries")
    alpha = models.FloatField()
    beta = models.FloatField()
    prior_alpha = models.FloatField()
    prior_beta = models.FloatField()
    evidence_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    delayed_successes = models.PositiveIntegerField(default=0)
    formats_seen = models.JSONField(default=list, blank=True)
    last_practiced_at = models.DateTimeField(null=True, blank=True)
    mean_at_update = models.FloatField(help_text="Posterior mean when last updated (before time decay).")
    model_version = models.CharField(max_length=40)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "skill masteries"
        constraints = [
            models.UniqueConstraint(fields=["user", "skill"], name="one_mastery_per_user_skill"),
        ]
        indexes = [models.Index(fields=["user", "mean_at_update"])]

    def __str__(self) -> str:
        return f"{self.user} · {self.skill}: {self.mean_at_update:.2f}"


class SkillEvidence(models.Model):
    """How one evaluated attempt changed the mastery estimate for one skill."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="skill_evidence")
    skill = models.ForeignKey("catalog.Skill", on_delete=models.CASCADE, related_name="evidence")
    attempt = models.ForeignKey(LearningAttempt, on_delete=models.CASCADE, related_name="evidence")
    weight = models.FloatField()
    score = models.FloatField()
    mastery_before = models.FloatField()
    mastery_after = models.FloatField()
    std_after = models.FloatField()
    detail = models.JSONField(default=dict, blank=True)
    model_version = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["attempt", "skill"], name="one_evidence_per_attempt_skill"),
        ]
        indexes = [models.Index(fields=["user", "skill", "created_at"])]

    def __str__(self) -> str:
        return f"Evidence {self.mastery_before:.2f}→{self.mastery_after:.2f} (attempt {self.attempt_id})"


class ReviewSchedule(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="review_schedules")
    skill = models.ForeignKey("catalog.Skill", on_delete=models.CASCADE, related_name="review_schedules")
    interval_days = models.FloatField()
    ease = models.FloatField()
    repetitions = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    due_at = models.DateTimeField()
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    last_score = models.FloatField(null=True, blank=True)
    algorithm_version = models.CharField(max_length=40)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "skill"], name="one_review_schedule_per_user_skill"),
        ]
        indexes = [models.Index(fields=["user", "due_at"]), models.Index(fields=["due_at"])]

    def __str__(self) -> str:
        return f"{self.user} · {self.skill} due {self.due_at:%Y-%m-%d}"


class ReviewRecord(models.Model):
    """Audit row for each scheduling decision. One per attempt, so retries can't double-apply."""

    schedule = models.ForeignKey(ReviewSchedule, on_delete=models.CASCADE, related_name="records")
    attempt = models.OneToOneField(LearningAttempt, on_delete=models.CASCADE, related_name="review_record")
    outcome = models.CharField(max_length=20)
    quality = models.PositiveSmallIntegerField()
    previous_interval_days = models.FloatField(null=True, blank=True)
    previous_due_at = models.DateTimeField(null=True, blank=True)
    new_interval_days = models.FloatField()
    new_due_at = models.DateTimeField()
    reviewed_at = models.DateTimeField()

    class Meta:
        ordering = ["-reviewed_at"]

    def __str__(self) -> str:
        return f"{self.outcome} → {self.new_interval_days:g} d (attempt {self.attempt_id})"


class LearningEvent(models.Model):
    """Append-only audit log of meaningful learning operations (no sensitive content)."""

    class Type(models.TextChoices):
        ONBOARDING_COMPLETED = "onboarding_completed", "Onboarding completed"
        GOAL_CREATED = "goal_created", "Goal created"
        GOAL_UPDATED = "goal_updated", "Goal updated"
        GOAL_STATUS_CHANGED = "goal_status_changed", "Goal status changed"
        RECOMMENDATION_CREATED = "recommendation_created", "Recommendation created"
        RECOMMENDATION_SKIPPED = "recommendation_skipped", "Recommendation skipped"
        HINT_REVEALED = "hint_revealed", "Hint revealed"
        SOLUTION_REVEALED = "solution_revealed", "Solution revealed"
        ATTEMPT_SUBMITTED = "attempt_submitted", "Attempt submitted"
        ATTEMPT_EVALUATED = "attempt_evaluated", "Attempt evaluated"
        EVALUATION_FAILED = "evaluation_failed", "Evaluation failed"
        MASTERY_UPDATED = "mastery_updated", "Mastery updated"
        REVIEW_SCHEDULED = "review_scheduled", "Review scheduled"
        MILESTONE_COMPLETED = "milestone_completed", "Milestone completed"
        ACHIEVEMENT_EARNED = "achievement_earned", "Achievement earned"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="learning_events")
    event_type = models.CharField(max_length=40, choices=Type.choices)
    occurred_at = models.DateTimeField(default=timezone.now)
    goal = models.ForeignKey(LearningGoal, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    skill = models.ForeignKey("catalog.Skill", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    attempt = models.ForeignKey(LearningAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["user", "-occurred_at"]),
            models.Index(fields=["user", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class UserAchievement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="achievements")
    code = models.CharField(max_length=40)
    earned_at = models.DateTimeField(default=timezone.now)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-earned_at"]
        constraints = [models.UniqueConstraint(fields=["user", "code"], name="one_achievement_per_user")]

    def __str__(self) -> str:
        return f"{self.code} for {self.user_id}"


class MilestoneCompletion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="milestone_completions")
    goal = models.ForeignKey(LearningGoal, on_delete=models.CASCADE, related_name="milestone_completions")
    milestone = models.ForeignKey("catalog.PathMilestone", on_delete=models.PROTECT, related_name="completions")
    completed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-completed_at"]
        constraints = [
            models.UniqueConstraint(fields=["goal", "milestone"], name="one_completion_per_goal_milestone"),
        ]

    def __str__(self) -> str:
        return f"Milestone {self.milestone_id} completed for goal {self.goal_id}"
