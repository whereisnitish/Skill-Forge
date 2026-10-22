from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject

THEMES = {"dark", "light", "system"}


def _unread_notifications(request: HttpRequest) -> int:
    from apps.notifications.models import Notification

    return Notification.objects.filter(user=request.user, read_at__isnull=True).count()


def site(request: HttpRequest) -> dict:
    from apps.evaluation.runner import runner_available
    from apps.mentor.providers import mentor_is_live

    user = getattr(request, "user", None)
    profile = getattr(user, "profile", None) if user is not None and user.is_authenticated else None

    theme = getattr(profile, "theme", None) or request.COOKIES.get("sf_theme", "light")
    if theme not in THEMES:
        theme = "light"

    context = {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL,
        "SUPPORT_EMAIL": settings.SUPPORT_EMAIL,
        "csp_nonce": getattr(request, "csp_nonce", ""),
        "theme": theme,
        "reduce_motion": bool(getattr(profile, "reduce_motion", False)),
        "text_scale": getattr(profile, "text_scale", "default"),
        "mentor_live": mentor_is_live(),
        "code_runner_available": runner_available(),
        "DEBUG": settings.DEBUG,
    }
    if profile is not None:
        context["unread_notifications"] = SimpleLazyObject(lambda: _unread_notifications(request))
    return context
