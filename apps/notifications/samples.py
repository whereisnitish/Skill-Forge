"""Realistic sample data for previewing and test-sending every email (no database writes)."""

from __future__ import annotations

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile, User
from apps.core.emails import absolute_url
from apps.marketing.models import ContactMessage

from .emails import build_notification_email
from .models import Notification

EMAILS = [
    "verify_email",
    "verify_email_change",
    "password_reset",
    "daily_reminder",
    "review_due",
    "milestone",
    "achievement",
    "payment_failed",
    "account",
    "contact_received",
]

NOTIFICATION_SAMPLES = {
    "daily_reminder": {
        "kind": Notification.Kind.DAILY_REMINDER,
        "title": "Today's challenge: Why does normalise return nothing for a generator?",
        "url": "/app/challenges/gen-single-pass-explain/?rec=1",
        "data": {
            "budget": 15,
            "streak": 4,
            "challenge_title": "Why does normalise return nothing for a generator?",
            "skill": "Iterators & generators",
            "kind_label": "Concept explanation",
            "minutes": 6,
            "reason_label": "Due for review",
            "reason": "Scheduled because Iterators & generators is due for review — you last practised it 4 days ago.",
        },
    },
    "review_due": {
        "kind": Notification.Kind.REVIEW_DUE,
        "title": "3 skills due for review",
        "url": "/app/reviews/",
        "data": {
            "count": 3,
            "skills": [
                {"name": "Scope & closures", "overdue": True},
                {"name": "SQL joins & aggregation", "overdue": False},
                {"name": "Classes, dataclasses & protocols", "overdue": False},
            ],
            "more": 0,
        },
    },
    "milestone": {
        "kind": Notification.Kind.MILESTONE,
        "title": "Milestone complete: Idiomatic foundations",
        "url": "/app/goals/1/",
        "data": {
            "milestone": "Idiomatic foundations",
            "goal": "Write better Python",
            "path": "Python Craftsman",
            "completed": 1,
            "total": 4,
            "percent": 25,
            "next": "Functions as power tools",
        },
    },
    "achievement": {
        "kind": Notification.Kind.ACHIEVEMENT,
        "title": "Achievement unlocked: A week of practice",
        "url": "/app/progress/",
        "data": {
            "code": "streak_7",
            "name": "A week of practice",
            "description": "Practised seven days in a row.",
            "total": 5,
        },
    },
    "payment_failed": {
        "kind": Notification.Kind.BILLING,
        "title": "We couldn't process your payment",
        "url": "/billing/",
        "data": {"template": "payment_failed", "plan": "Pro"},
    },
    "account": {
        "kind": Notification.Kind.ACCOUNT,
        "title": "A note about your account",
        "body": "This layout is used for general account notices that don't have a dedicated template.",
        "url": "/settings/",
        "data": {},
    },
}


def sample_user(email: str = "ada@example.com") -> User:
    user = User(email=email, display_name="Ada")
    user.profile = Profile(user=user, timezone="Europe/London", reminder_hour=9)
    return user


def sample_email(name: str, *, email: str = "ada@example.com") -> tuple[str, dict, dict]:
    """Return (template prefix, context, headers) for a named sample email."""
    user = sample_user(email)
    if name in NOTIFICATION_SAMPLES:
        notification = Notification(user=user, dedupe_key="sample", **NOTIFICATION_SAMPLES[name])
        return build_notification_email(notification)
    if name == "verify_email":
        from apps.accounts.tasks import SIGNUP_NEXT_STEPS

        return (
            name,
            {
                "user": user,
                "verify_url": absolute_url("/accounts/verify-email/sample/token/"),
                "next_steps": SIGNUP_NEXT_STEPS,
            },
            {},
        )
    if name == "verify_email_change":
        return (
            name,
            {
                "user": user,
                "verify_url": absolute_url("/accounts/verify-email/sample/token/"),
                "password_reset_url": absolute_url(reverse("accounts:password_reset")),
            },
            {},
        )
    if name == "password_reset":
        return name, {"user": user, "reset_url": absolute_url("/accounts/password-reset/sample/token/")}, {}
    if name == "contact_received":
        message = ContactMessage(
            pk=1,
            name="Grace Hopper",
            email="grace@example.com",
            topic=ContactMessage.Topic.TEAMS,
            message="Hi! We're a team of 12 engineers interested in the Teams plan.\n\nCould you tell us more?",
            created_at=timezone.now(),
        )
        admin = absolute_url(reverse("admin:marketing_contactmessage_change", args=[1]))
        return name, {"message": message, "admin_url": admin}, {"Reply-To": message.email}
    raise ValueError(f"Unknown email {name!r}. Choose from: {', '.join(EMAILS)}")


def recipient_note() -> str:
    return f"from {settings.DEFAULT_FROM_EMAIL} via {settings.EMAIL_BACKEND.rsplit('.', 2)[-2]}"
