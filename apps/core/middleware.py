from __future__ import annotations

import re
import secrets
import uuid
import zoneinfo
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .logging import request_id_var

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class RequestIDMiddleware:
    """Attach a correlation id to the request, log records and response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware:
    """Content-Security-Policy with a per-request script nonce, plus Permissions-Policy."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        nonce = secrets.token_urlsafe(16)
        request.csp_nonce = nonce  # type: ignore[attr-defined]
        response = self.get_response(request)
        form_targets = "'self'"
        if settings.BILLING_PROVIDER == "stripe":
            form_targets += " https://checkout.stripe.com https://billing.stripe.com"
        policy = "; ".join(
            [
                "default-src 'self'",
                f"script-src 'self' 'nonce-{nonce}'",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data:",
                "font-src 'self'",
                "connect-src 'self'",
                "object-src 'none'",
                "base-uri 'self'",
                "frame-ancestors 'none'",
                f"form-action {form_targets}",
            ]
        )
        response.setdefault("Content-Security-Policy", policy)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        return response


class UserTimezoneMiddleware:
    """Activate the signed-in user's timezone so dates render in local time."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tz_name = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            profile = getattr(user, "profile", None)
            tz_name = getattr(profile, "timezone", None)
        if tz_name:
            try:
                timezone.activate(zoneinfo.ZoneInfo(tz_name))
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                timezone.deactivate()
        else:
            timezone.deactivate()
        return self.get_response(request)
