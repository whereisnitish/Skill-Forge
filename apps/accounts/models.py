from __future__ import annotations

import zoneinfo

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


def validate_timezone(value: str) -> None:
    if value not in zoneinfo.available_timezones():
        raise ValidationError("Choose a valid timezone.")


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields) -> User:
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("email_verified_at", timezone.now())
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("Superusers must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Email-identified account. Learning preferences live on Profile."""

    username = None
    first_name = None
    last_name = None
    email = models.EmailField("email address", unique=True)
    display_name = models.CharField(max_length=60, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def friendly_name(self) -> str:
        return self.display_name or self.email.split("@", 1)[0]

    def get_full_name(self) -> str:
        return self.friendly_name

    def get_short_name(self) -> str:
        return self.friendly_name


class Profile(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    class Theme(models.TextChoices):
        SYSTEM = "system", "Match my system"
        DARK = "dark", "Dark"
        LIGHT = "light", "Light"

    class DifficultyPreference(models.TextChoices):
        GENTLE = "gentle", "Gentle — build confidence first"
        BALANCED = "balanced", "Balanced"
        STRETCH = "stretch", "Stretch — push me a little harder"

    class TextScale(models.TextChoices):
        DEFAULT = "default", "Default"
        LARGE = "large", "Larger text"

    DAILY_MINUTE_CHOICES = [(m, f"{m} minutes") for m in (10, 15, 20, 30, 45)]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_timezone])
    experience_level = models.CharField(max_length=20, choices=Level.choices, default=Level.BEGINNER)
    daily_minutes = models.PositiveSmallIntegerField(choices=DAILY_MINUTE_CHOICES, default=15)
    preferred_formats = models.JSONField(default=list, blank=True)
    difficulty_preference = models.CharField(
        max_length=20, choices=DifficultyPreference.choices, default=DifficultyPreference.BALANCED
    )
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.LIGHT)
    reduce_motion = models.BooleanField(default=False)
    text_scale = models.CharField(max_length=10, choices=TextScale.choices, default=TextScale.DEFAULT)

    # Notification preferences. Nothing is sent unless the relevant flag is on.
    daily_reminder_enabled = models.BooleanField(default=False)
    review_reminder_enabled = models.BooleanField(default=True)
    milestone_emails_enabled = models.BooleanField(default=True)
    reminder_hour = models.PositiveSmallIntegerField(default=9)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reminder_hour__gte=0, reminder_hour__lte=23),
                name="profile_reminder_hour_range",
            ),
            models.CheckConstraint(
                condition=models.Q(daily_minutes__gte=5, daily_minutes__lte=120),
                name="profile_daily_minutes_range",
            ),
        ]

    def __str__(self) -> str:
        return f"Profile for {self.user}"
