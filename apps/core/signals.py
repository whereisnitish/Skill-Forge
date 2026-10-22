"""Celery signal handlers that make background failures visible."""

from __future__ import annotations

import logging

from celery.signals import task_failure, task_retry

logger = logging.getLogger("apps.tasks")


@task_failure.connect
def record_task_failure(sender=None, task_id=None, exception=None, **kwargs) -> None:
    task_name = getattr(sender, "name", str(sender))
    logger.error(
        "task.failed",
        extra={"task": task_name, "task_id": task_id, "exception": type(exception).__name__},
    )
    try:
        from .models import TaskFailure

        TaskFailure.objects.create(
            task_name=task_name[:200],
            task_id=str(task_id or "")[:100],
            exception_type=type(exception).__name__[:200],
            message=str(exception)[:2000],
        )
    except Exception:
        logger.exception("task.failure_record_failed")


@task_retry.connect
def log_task_retry(sender=None, request=None, reason=None, **kwargs) -> None:
    logger.warning(
        "task.retry",
        extra={
            "task": getattr(sender, "name", str(sender)),
            "task_id": getattr(request, "id", None),
            "reason": type(reason).__name__ if isinstance(reason, BaseException) else str(reason),
        },
    )
