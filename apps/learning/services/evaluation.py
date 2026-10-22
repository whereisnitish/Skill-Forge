"""Evaluate an attempt exactly once and apply the result to the learner model."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import datetime

from django.db import transaction

from apps.evaluation.registry import get_evaluator, is_async_kind
from apps.evaluation.runner import RunnerUnavailable

from ..models import AttemptEvaluation, LearningAttempt, LearningEvent
from .attempts import build_spec
from .learner_model import apply_learning_updates

logger = logging.getLogger(__name__)

MAX_EVALUATION_ATTEMPTS = 5


def evaluate_attempt(attempt_id: int, *, now: datetime | None = None) -> AttemptEvaluation | None:
    """Idempotent: evaluating an already-evaluated attempt returns the stored result.

    The (possibly slow) evaluator runs outside any database transaction; the
    result is then written under a row lock so concurrent or repeated task
    executions cannot double-apply learner-model updates.
    """
    attempt = (
        LearningAttempt.objects.select_related("challenge", "challenge_version__challenge")
        .filter(pk=attempt_id)
        .first()
    )
    if attempt is None:
        return None
    if attempt.status == LearningAttempt.Status.EVALUATED:
        return AttemptEvaluation.objects.filter(attempt=attempt).first()

    version = attempt.challenge_version
    spec = build_spec(version)
    evaluator = get_evaluator(attempt.challenge.kind)
    started = time.monotonic()
    try:
        if is_async_kind(attempt.challenge.kind):
            result = evaluator.evaluate(spec, attempt.response, user_id=attempt.user_id)
        else:
            result = evaluator.evaluate(spec, attempt.response)
    except RunnerUnavailable as exc:
        _record_failure(attempt, str(exc))
        raise
    duration_ms = int((time.monotonic() - started) * 1000)

    with transaction.atomic():
        locked = LearningAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.status == LearningAttempt.Status.EVALUATED:
            return AttemptEvaluation.objects.get(attempt=locked)
        evaluation = AttemptEvaluation.objects.create(
            attempt=locked,
            score=result.score,
            verdict=result.verdict,
            passed=result.passed,
            summary=result.summary[:300],
            feedback=result.to_feedback_json(),
            misconceptions=[asdict(m) for m in result.misconceptions],
            evaluator_version=result.evaluator_version,
            duration_ms=duration_ms,
        )
        locked.status = LearningAttempt.Status.EVALUATED
        locked.evaluation_error = ""
        locked.save(update_fields=["status", "evaluation_error"])
        LearningEvent.objects.create(
            user_id=locked.user_id,
            event_type=LearningEvent.Type.ATTEMPT_EVALUATED,
            goal_id=locked.goal_id,
            skill_id=locked.challenge.skill_id,
            attempt=locked,
            payload={
                "score": evaluation.score,
                "verdict": evaluation.verdict,
                "evaluator": evaluation.evaluator_version,
            },
        )
        apply_learning_updates(locked, evaluation, now=now)
    logger.info(
        "attempt.evaluated",
        extra={"attempt_id": attempt.pk, "verdict": evaluation.verdict, "duration_ms": duration_ms},
    )
    return evaluation


def _record_failure(attempt: LearningAttempt, message: str) -> None:
    with transaction.atomic():
        locked = LearningAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.status == LearningAttempt.Status.EVALUATED:
            return
        locked.evaluation_attempts += 1
        locked.evaluation_error = message[:300]
        if locked.evaluation_attempts >= MAX_EVALUATION_ATTEMPTS:
            locked.status = LearningAttempt.Status.FAILED
            LearningEvent.objects.create(
                user_id=locked.user_id,
                event_type=LearningEvent.Type.EVALUATION_FAILED,
                attempt=locked,
                payload={"reason": message[:200]},
            )
        locked.save(update_fields=["status", "evaluation_error", "evaluation_attempts"])
