"""Which template each notification email uses, and the context it is rendered with."""

from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.urls import reverse

from apps.core.emails import absolute_url

from .models import Notification

UNSUBSCRIBE_SALT = "notifications.unsubscribe"

TEMPLATE_FOR_KIND = {
    Notification.Kind.DAILY_REMINDER: "daily_reminder",
    Notification.Kind.REVIEW_DUE: "review_due",
    Notification.Kind.MILESTONE: "milestone",
    Notification.Kind.ACHIEVEMENT: "achievement",
    Notification.Kind.BILLING: "payment_failed",
    Notification.Kind.ACCOUNT: "account",
}

# Optional emails that the learner can switch off with one click. Account and
# billing notices are transactional and have no unsubscribe link.
UNSUBSCRIBABLE = {
    Notification.Kind.DAILY_REMINDER,
    Notification.Kind.REVIEW_DUE,
    Notification.Kind.MILESTONE,
    Notification.Kind.ACHIEVEMENT,
}


def unsubscribe_token(user_id: int, kind: str) -> str:
    return signing.dumps({"u": user_id, "k": kind}, salt=UNSUBSCRIBE_SALT, compress=True)


def unsubscribe_url(user_id: int, kind: str) -> str:
    return settings.SITE_URL + reverse("notifications:unsubscribe", args=[unsubscribe_token(user_id, kind)])


def build_notification_email(notification: Notification) -> tuple[str, dict, dict[str, str]]:
    """Return (template prefix, context, extra headers) for a notification email."""
    user = notification.user
    profile = user.profile
    data = notification.data or {}
    template = data.get("template") or TEMPLATE_FOR_KIND.get(notification.kind, "account")
    context = {
        "user": user,
        "notification": notification,
        "data": data,
        "action_url": absolute_url(notification.url or reverse("learning:today")),
        "reminder_time": f"{profile.reminder_hour:02d}:00",
        "timezone_name": profile.timezone.replace("_", " "),
    }
    headers: dict[str, str] = {}
    if notification.kind in UNSUBSCRIBABLE:
        url = unsubscribe_url(user.pk, notification.kind)
        context["unsubscribe_url"] = url
        headers = {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return template, context, headers
