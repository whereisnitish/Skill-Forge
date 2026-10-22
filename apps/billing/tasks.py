from __future__ import annotations

import logging

from celery import shared_task

from .services import expire_lapsed

logger = logging.getLogger(__name__)


@shared_task
def expire_lapsed_subscriptions() -> int:
    """Downgrade cancelled subscriptions whose paid period has ended. Idempotent."""
    count = expire_lapsed()
    logger.info("billing.expired", extra={"count": count})
    return count
