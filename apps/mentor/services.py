from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.billing.entitlements import ai_mentor_daily_limit, consume, release
from apps.core.ratelimit import hit
from apps.core.timeutils import local_date

from .context import build_context, build_prompt, curated_response
from .models import MentorRequest
from .providers import MentorError, get_live_provider, mentor_is_live

logger = logging.getLogger(__name__)

QUOTA_FEATURE = "ai_mentor"
DEDUPE_WINDOW = timedelta(minutes=2)


class MentorRateLimited(Exception):
    pass


class TransientMentorFailure(Exception):
    pass


def request_mentor(user, *, kind: str, attempt=None, skill=None, question: str = "") -> MentorRequest:
    """Create (or reuse) a mentor request and dispatch it to a background worker."""
    if kind not in MentorRequest.Kind.values:
        raise ValueError("Unknown mentor request type.")
    if attempt is not None and attempt.user_id != user.pk:
        raise PermissionError("Attempt does not belong to this user.")
    if skill is None and attempt is not None:
        skill = attempt.challenge.skill

    recent = MentorRequest.objects.filter(
        user=user,
        kind=kind,
        attempt=attempt,
        skill=skill,
        question=question,
        created_at__gte=timezone.now() - DEDUPE_WINDOW,
        error_code="",
    ).exclude(status=MentorRequest.Status.FAILED)
    existing = recent.first()
    if existing is not None:
        return existing

    if hit("mentor", f"u{user.pk}", f"{settings.AI_REQUESTS_PER_MINUTE}/m"):
        raise MentorRateLimited()

    with transaction.atomic():
        request = MentorRequest.objects.create(
            user=user,
            kind=kind,
            attempt=attempt,
            skill=skill,
            question=question[:500],
        )
        from .tasks import run_mentor_request_task

        request_id = request.pk
        transaction.on_commit(lambda: run_mentor_request_task.delay(request_id))
    return request


def _finish(request: MentorRequest, *, data: dict, source: str, provider: str, error_code: str = "", **meta) -> None:
    request.response = data
    request.source = source
    request.provider = provider
    request.error_code = error_code
    request.status = MentorRequest.Status.COMPLETED
    request.completed_at = timezone.now()
    request.model = meta.get("model", "")
    request.input_tokens = meta.get("input_tokens", 0)
    request.output_tokens = meta.get("output_tokens", 0)
    request.latency_ms = meta.get("latency_ms", 0)
    request.save()


def run_mentor_request(request_id: int, *, allow_retry: bool = False) -> str:
    """Produce the mentor response. Idempotent: only pending requests are processed."""
    request = MentorRequest.objects.select_related("user__profile", "skill").filter(pk=request_id).first()
    if request is None or request.status != MentorRequest.Status.PENDING:
        return "skipped"
    ctx = build_context(request)

    provider = get_live_provider()
    if provider is None:
        _finish(request, data=curated_response(ctx), source=MentorRequest.Source.FALLBACK, provider="curated")
        return "fallback"

    period = local_date(request.user)
    if not consume(request.user, QUOTA_FEATURE, period, ai_mentor_daily_limit(request.user)):
        _finish(
            request,
            data=curated_response(ctx),
            source=MentorRequest.Source.FALLBACK,
            provider="curated",
            error_code="quota_exceeded",
        )
        return "quota"

    try:
        result = provider.generate(build_prompt(ctx))
    except MentorError as exc:
        release(request.user, QUOTA_FEATURE, period)
        logger.warning("mentor.provider_error", extra={"request_id": request.pk, "code": exc.code})
        if exc.transient and allow_retry:
            raise TransientMentorFailure(exc.code) from exc
        _finish(
            request,
            data=curated_response(ctx),
            source=MentorRequest.Source.FALLBACK,
            provider="curated",
            error_code=exc.code,
        )
        return f"fallback:{exc.code}"

    _finish(
        request,
        data=result.data,
        source=MentorRequest.Source.LIVE,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
    )
    logger.info(
        "mentor.completed",
        extra={
            "request_id": request.pk,
            "latency_ms": result.latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
    )
    return "live"


def mentor_status() -> dict:
    return {"live": mentor_is_live(), "model": settings.AI_MODEL if mentor_is_live() else ""}
