from __future__ import annotations

from celery import shared_task

from .services import TransientMentorFailure, run_mentor_request


@shared_task(bind=True, max_retries=2, soft_time_limit=100, time_limit=120, acks_late=True)
def run_mentor_request_task(self, request_id: int) -> str:
    """Generate mentor guidance; transient provider errors retry with backoff, then fall back."""
    try:
        return run_mentor_request(request_id, allow_retry=self.request.retries < self.max_retries)
    except TransientMentorFailure as exc:
        raise self.retry(exc=exc, countdown=5 * 2**self.request.retries) from exc
