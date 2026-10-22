"""Curated learning content: skills, prerequisite graph, versioned challenges and paths.

Challenge and path content is versioned. A version is immutable once a learner
has attempted it, so historical attempts can always be re-read exactly as the
learner saw them.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel

from .constants import DIFFICULTY_LABELS, KIND_ICONS, ChallengeKind, GoalType

DIFFICULTY_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


class SkillCategory(models.Model):
    class Domain(models.TextChoices):
        SOFTWARE = "software", "Software engineering"
        COMMUNICATION = "communication", "Communication"

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=40, default="shapes")
    domain = models.CharField(max_length=20, choices=Domain.choices, default=Domain.SOFTWARE)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "skill categories"

    def __str__(self) -> str:
        return self.name


class SkillQuerySet(models.QuerySet):
    def active(self) -> SkillQuerySet:
        return self.filter(is_active=True)


class Skill(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=120)
    category = models.ForeignKey(SkillCategory, on_delete=models.PROTECT, related_name="skills")
    summary = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    difficulty = models.PositiveSmallIntegerField(validators=DIFFICULTY_VALIDATORS, default=2)
    learning_objectives = models.JSONField(default=list, blank=True)
    review_interval_days = models.PositiveSmallIntegerField(
        default=2, help_text="Recommended first review interval in days."
    )
    related_skills = models.ManyToManyField("self", blank=True, symmetrical=True)
    prerequisites = models.ManyToManyField(
        "self",
        through="SkillPrerequisite",
        through_fields=("skill", "prerequisite"),
        symmetrical=False,
        related_name="dependents",
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    objects = SkillQuerySet.as_manager()

    class Meta:
        ordering = ["category__order", "order", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(difficulty__gte=1, difficulty__lte=5), name="skill_difficulty_range"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def difficulty_label(self) -> str:
        return DIFFICULTY_LABELS.get(self.difficulty, "")


class SkillPrerequisite(models.Model):
    class Strength(models.TextChoices):
        REQUIRED = "required", "Required"
        RECOMMENDED = "recommended", "Recommended"

    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="prerequisite_links")
    prerequisite = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="dependent_links")
    strength = models.CharField(max_length=12, choices=Strength.choices, default=Strength.REQUIRED)
    min_mastery = models.FloatField(
        default=0.55,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Estimated mastery of the prerequisite needed before this skill is recommended.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["skill", "prerequisite"], name="unique_skill_prerequisite"),
            models.CheckConstraint(condition=~Q(skill=models.F("prerequisite")), name="prerequisite_not_self"),
        ]

    def __str__(self) -> str:
        return f"{self.prerequisite} → {self.skill}"

    def clean(self) -> None:
        from apps.engine.graph import SkillGraph

        if self.skill_id and self.skill_id == self.prerequisite_id:
            raise ValidationError("A skill cannot be its own prerequisite.")
        edges = SkillPrerequisite.objects.exclude(pk=self.pk).values_list("skill_id", "prerequisite_id")
        graph = SkillGraph.from_edges([], edges)
        if graph.would_create_cycle(self.skill_id, self.prerequisite_id):
            raise ValidationError("This prerequisite would create a cycle in the skill graph.")


class ChallengeQuerySet(models.QuerySet):
    def published(self) -> ChallengeQuerySet:
        return self.filter(
            is_active=True,
            review_status=Challenge.ReviewStatus.APPROVED,
            current_version__isnull=False,
            skill__is_active=True,
        )


class Challenge(TimeStampedModel):
    class Source(models.TextChoices):
        CURATED = "curated", "Curated"
        AI_GENERATED = "ai_generated", "AI generated"

    class ReviewStatus(models.TextChoices):
        DRAFT = "draft", "Draft — awaiting review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    slug = models.SlugField(unique=True, max_length=100)
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="challenges")
    secondary_skills = models.ManyToManyField(Skill, blank=True, related_name="secondary_challenges")
    kind = models.CharField(max_length=24, choices=ChallengeKind.choices)
    difficulty = models.PositiveSmallIntegerField(validators=DIFFICULTY_VALIDATORS)
    estimated_minutes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(60)])
    tags = models.JSONField(default=list, blank=True)
    is_diagnostic = models.BooleanField(
        default=False, help_text="Suitable for quick placement checks during onboarding."
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.CURATED)
    review_status = models.CharField(max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.APPROVED)
    is_active = models.BooleanField(default=True)
    current_version = models.ForeignKey(
        "ChallengeVersion", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = ChallengeQuerySet.as_manager()

    class Meta:
        ordering = ["skill__order", "difficulty", "slug"]
        indexes = [models.Index(fields=["skill", "is_active", "review_status"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(difficulty__gte=1, difficulty__lte=5), name="challenge_difficulty_range"
            ),
        ]

    def __str__(self) -> str:
        return self.slug

    @property
    def kind_icon(self) -> str:
        return KIND_ICONS.get(self.kind, "puzzle")

    @property
    def difficulty_label(self) -> str:
        return DIFFICULTY_LABELS.get(self.difficulty, "")

    @property
    def requires_code_runner(self) -> bool:
        return self.kind == ChallengeKind.PYTHON_CODE


class ChallengeVersion(models.Model):
    """Immutable snapshot of challenge content as presented to learners."""

    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    learning_objective = models.CharField(max_length=300)
    prompt = models.TextField()
    content = models.JSONField(default=dict, blank=True)
    hints = models.JSONField(default=list, blank=True)
    solution = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    evaluation_version = models.CharField(max_length=40)
    content_hash = models.CharField(max_length=64, db_index=True)
    generated_by = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["challenge", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["challenge", "number"], name="unique_challenge_version"),
        ]

    def __str__(self) -> str:
        return f"{self.challenge.slug} v{self.number}"

    def save(self, *args, **kwargs) -> None:
        if self.pk and self.attempts.exists():
            raise ValidationError("Challenge versions are immutable once attempted; create a new version.")
        super().save(*args, **kwargs)


class ChallengeTestCase(models.Model):
    version = models.ForeignKey(ChallengeVersion, on_delete=models.CASCADE, related_name="test_cases")
    order = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)
    code = models.TextField(help_text="Trusted assertion code executed after the learner's solution.")
    is_hidden = models.BooleanField(default=False)
    weight = models.FloatField(default=1.0, validators=[MinValueValidator(0.0)])

    class Meta:
        ordering = ["version", "order"]
        constraints = [
            models.UniqueConstraint(fields=["version", "order"], name="unique_test_case_order"),
        ]

    def __str__(self) -> str:
        return self.name


class LearningPath(TimeStampedModel):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    goal_type = models.CharField(max_length=20, choices=GoalType.choices)
    icon = models.CharField(max_length=40, default="route")
    is_premium = models.BooleanField(default=False)
    is_default_for_goal = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)
    current_version = models.ForeignKey(
        "LearningPathVersion", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["goal_type"],
                condition=Q(is_default_for_goal=True),
                name="one_default_path_per_goal",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class LearningPathVersion(models.Model):
    path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    notes = models.CharField(max_length=300, blank=True)
    content_hash = models.CharField(max_length=64)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["path", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["path", "number"], name="unique_path_version"),
        ]

    def __str__(self) -> str:
        return f"{self.path.name} v{self.number}"


class PathMilestone(models.Model):
    version = models.ForeignKey(LearningPathVersion, on_delete=models.CASCADE, related_name="milestones")
    order = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["version", "order"]
        constraints = [
            models.UniqueConstraint(fields=["version", "order"], name="unique_milestone_order"),
        ]

    def __str__(self) -> str:
        return self.title


class PathStep(models.Model):
    milestone = models.ForeignKey(PathMilestone, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField()
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="path_steps")
    target_mastery = models.FloatField(default=0.7, validators=[MinValueValidator(0.1), MaxValueValidator(1.0)])

    class Meta:
        ordering = ["milestone", "order"]
        constraints = [
            models.UniqueConstraint(fields=["milestone", "order"], name="unique_step_order"),
            models.UniqueConstraint(fields=["milestone", "skill"], name="unique_step_skill"),
        ]

    def __str__(self) -> str:
        return f"{self.milestone}: {self.skill}"
