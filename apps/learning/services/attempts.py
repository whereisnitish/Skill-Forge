"""Challenge workspace operations: drafts, hints, reveals and submission."""

from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Challenge, ChallengeVersion
from apps.core.timeutils import day_bounds, local_date, user_zone
from apps.evaluation.base import ChallengeSpec, EvaluationUnavailable
from apps.evaluation.registry import get_evaluator, is_async_kind, unavailable_kinds

from ..models import AttemptDraft, LearningAttempt, LearningEvent, Recommendation, ReviewSchedule
from .sessions import primary_goal

logger = logging.getLogger(__name__)

MAX_DRAFT_CHARS = 25000
MAX_TIME_SPENT_SECONDS = 3 * 3600


class SubmissionLimitReached(Exception):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Daily submission limit of {limit} reached.")


def build_spec(version: ChallengeVersion) -> ChallengeSpec:
    tests = [
        {"order": t.order, "name": t.name, "code": t.code, "is_hidden": t.is_hidden, "weight": t.weight}
        for t in version.test_cases.all()
    ]
    reference = "\n".join([version.prompt or "", str((version.content or {}).get("code", ""))])
    return ChallengeSpec(kind=version.challenge.kind, content=version.content, tests=tests, reference_text=reference)


def get_draft(user, version: ChallengeVersion) -> AttemptDraft | None:
    return AttemptDraft.objects.filter(user=user, challenge_version=version).first()


def ensure_draft(user, version: ChallengeVersion, recommendation: Recommendation | None = None) -> AttemptDraft:
    draft, created = AttemptDraft.objects.get_or_create(
        user=user, challenge_version=version, defaults={"recommendation": recommendation}
    )
    if not created and recommendation is not None and draft.recommendation_id != recommendation.pk:
        draft.recommendation = recommendation
        draft.save(update_fields=["recommendation", "updated_at"])
    return draft


def _clean_draft_payload(data: dict) -> dict:
    allowed = {"selected", "answer", "text", "line", "explanation", "code"}
    cleaned = {}
    for key in allowed & set(data):
        value = data[key]
        if isinstance(value, list):
            cleaned[key] = [str(v)[:100] for v in value][:20]
        else:
            cleaned[key] = str(value)[:MAX_DRAFT_CHARS]
    return cleaned


def autosave(user, version: ChallengeVersion, data: dict) -> AttemptDraft:
    draft = ensure_draft(user, version)
    draft.response = _clean_draft_payload(data)
    draft.save(update_fields=["response", "updated_at"])
    return draft


@transaction.atomic
def reveal_hint(user, version: ChallengeVersion) -> tuple[AttemptDraft, int]:
    """Reveal the next hint; returns the draft and how many hints are now visible."""
    ensure_draft(user, version)
    draft = AttemptDraft.objects.select_for_update().get(user=user, challenge_version=version)
    total = len(version.hints or [])
    if draft.hints_revealed < total:
        draft.hints_revealed += 1
        draft.save(update_fields=["hints_revealed", "updated_at"])
        LearningEvent.objects.create(
            user=user,
            event_type=LearningEvent.Type.HINT_REVEALED,
            skill_id=version.challenge.skill_id,
            payload={"challenge_version_id": version.pk, "hint_number": draft.hints_revealed},
        )
    return draft, draft.hints_revealed


@transaction.atomic
def reveal_solution(user, version: ChallengeVersion) -> AttemptDraft:
    ensure_draft(user, version)
    draft = AttemptDraft.objects.select_for_update().get(user=user, challenge_version=version)
    if not draft.solution_revealed:
        draft.solution_revealed = True
        draft.save(update_fields=["solution_revealed", "updated_at"])
        LearningEvent.objects.create(
            user=user,
            event_type=LearningEvent.Type.SOLUTION_REVEALED,
            skill_id=version.challenge.skill_id,
            payload={"challenge_version_id": version.pk},
        )
    return draft


def can_evaluate(challenge: Challenge) -> bool:
    return challenge.kind not in unavailable_kinds()


def _resolve_recommendation(user, challenge: Challenge, recommendation_id: int | None) -> Recommendation | None:
    pending = Recommendation.objects.filter(user=user, challenge=challenge, status=Recommendation.Status.PENDING)
    if recommendation_id:
        match = pending.filter(pk=recommendation_id).first()
        if match:
            return match
    return pending.order_by("-created_at").first()


def submit_attempt(
    user,
    version: ChallengeVersion,
    data: dict,
    *,
    recommendation_id: int | None = None,
    is_diagnostic: bool = False,
    now: datetime | None = None,
    enforce_limits: bool = True,
) -> LearningAttempt:
    """Validate, freeze and record a submission, then evaluate it (inline or queued).

    Raises InvalidResponse for malformed answers, EvaluationUnavailable when the
    challenge cannot be evaluated here, and SubmissionLimitReached when the
    plan's daily allowance is used up. No attempt is created in those cases.
    """
    from apps.billing.entitlements import daily_submission_limit

    now = now or timezone.now()
    challenge = version.challenge
    if not can_evaluate(challenge):
        raise EvaluationUnavailable("Coding challenges need the sandboxed code runner, which isn't configured.")

    evaluator = get_evaluator(challenge.kind)
    spec = build_spec(version)
    response = evaluator.parse(spec, data)

    zone = user_zone(user)
    today = local_date(user, now)
    if enforce_limits and not is_diagnostic:
        limit = daily_submission_limit(user)
        if limit is not None:
            start, end = day_bounds(today, zone)
            used = LearningAttempt.objects.filter(
                user=user, submitted_at__gte=start, submitted_at__lt=end, is_diagnostic=False
            ).count()
            if used >= limit:
                raise SubmissionLimitReached(limit)

    with transaction.atomic():
        draft = AttemptDraft.objects.select_for_update().filter(user=user, challenge_version=version).first()
        recommendation = _resolve_recommendation(user, challenge, recommendation_id)
        goal = primary_goal(user)
        started_at = draft.started_at if draft else now
        _, day_end = day_bounds(today, zone)
        is_review = ReviewSchedule.objects.filter(user=user, skill_id=challenge.skill_id, due_at__lte=day_end).exists()
        attempt = LearningAttempt.objects.create(
            user=user,
            challenge=challenge,
            challenge_version=version,
            recommendation=recommendation,
            session=recommendation.session if recommendation else None,
            goal=goal,
            attempt_number=LearningAttempt.objects.filter(user=user, challenge=challenge).count() + 1,
            response=response,
            hints_used=draft.hints_revealed if draft else 0,
            hints_available=len(version.hints or []),
            solution_revealed=draft.solution_revealed if draft else False,
            is_review=is_review,
            is_diagnostic=is_diagnostic,
            started_at=started_at,
            submitted_at=now,
            time_spent_seconds=min(MAX_TIME_SPENT_SECONDS, max(0, int((now - started_at).total_seconds()))),
            local_date=today,
            status=LearningAttempt.Status.QUEUED,
        )
        if draft:
            draft.delete()
        LearningEvent.objects.create(
            user=user,
            event_type=LearningEvent.Type.ATTEMPT_SUBMITTED,
            goal=goal,
            skill_id=challenge.skill_id,
            attempt=attempt,
            payload={"challenge": challenge.slug, "version": version.number, "kind": challenge.kind},
        )
        if is_async_kind(challenge.kind):
            from ..tasks import evaluate_attempt_task

            attempt_id = attempt.pk
            transaction.on_commit(lambda: evaluate_attempt_task.delay(attempt_id))

    if not is_async_kind(challenge.kind):
        from .evaluation import evaluate_attempt

        evaluate_attempt(attempt.pk, now=now)
        attempt.refresh_from_db()
    logger.info("attempt.submitted", extra={"user_id": user.pk, "attempt_id": attempt.pk, "kind": challenge.kind})
    return attempt
