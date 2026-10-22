from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template import loader
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def liveness(request: HttpRequest) -> JsonResponse:
    """Liveness: the process is up and able to serve requests. No dependency checks."""
    return JsonResponse({"status": "ok"})


@never_cache
@require_GET
def readiness(request: HttpRequest) -> JsonResponse:
    """Readiness: dependencies needed to serve traffic are reachable."""
    checks: dict[str, str] = {}
    healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        logger.exception("readiness.database_failed")
        checks["database"] = "error"
        healthy = False

    try:
        cache.set("readyz:probe", "1", timeout=5)
        checks["cache"] = "ok" if cache.get("readyz:probe") == "1" else "error"
    except Exception:
        logger.exception("readiness.cache_failed")
        checks["cache"] = "error"
    if checks["cache"] != "ok":
        healthy = False

    if settings.CELERY_TASK_ALWAYS_EAGER:
        checks["broker"] = "skipped (eager mode)"
    else:
        from config.celery import app as celery_app

        try:
            with celery_app.connection_for_write() as conn:
                conn.ensure_connection(max_retries=1, timeout=2)
            checks["broker"] = "ok"
        except Exception:
            logger.exception("readiness.broker_failed")
            checks["broker"] = "error"
            healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status=200 if healthy else 503,
    )


@require_GET
def robots_txt(request: HttpRequest) -> HttpResponse:
    lines = [
        "User-agent: *",
        "Disallow: /app/",
        "Disallow: /settings/",
        "Disallow: /onboarding/",
        "Disallow: /billing/",
        "Disallow: /accounts/",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def _error(request: HttpRequest, template: str, status: int, message: str) -> HttpResponse:
    if getattr(request, "htmx", False):
        response = HttpResponse(message, status=status, content_type="text/plain")
        response["X-SF-Message"] = message
        return response
    return render(request, template, {"status": status}, status=status)


def bad_request(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return _error(request, "errors/400.html", 400, "That request could not be processed.")


def permission_denied(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return _error(request, "errors/403.html", 403, "You don't have access to that.")


def page_not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return _error(request, "errors/404.html", 404, "We couldn't find that.")


def server_error(request: HttpRequest) -> HttpResponse:
    # Rendered without a RequestContext so a failing context processor or
    # database cannot break the error page itself.
    if getattr(request, "htmx", False):
        response = HttpResponse("Something went wrong.", status=500, content_type="text/plain")
        response["X-SF-Message"] = "Something went wrong on our side. Please try again."
        return response
    template = loader.get_template("errors/500.html")
    return HttpResponse(template.render({"request_id": getattr(request, "request_id", "")}), status=500)


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    return _error(
        request,
        "errors/csrf.html",
        403,
        "Your session expired. Refresh the page and try again.",
    )


def rate_limited(request: HttpRequest) -> HttpResponse:
    return _error(
        request,
        "errors/429.html",
        429,
        "You're doing that a little too often. Please wait a moment and try again.",
    )
