from __future__ import annotations

from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import Subscription, UsageRecord
from .plans import PLANS, Plan, get_plan

ENTITLED_STATUSES = {Subscription.Status.ACTIVE, Subscription.Status.TRIALING, Subscription.Status.PAST_DUE}


def subscription_for(user) -> Subscription | None:
    try:
        return user.subscription
    except Subscription.DoesNotExist:
        return None


def active_plan(user) -> Plan:
    """The plan whose entitlements apply right now, derived only from stored provider state."""
    subscription = subscription_for(user)
    if subscription is None:
        return PLANS["free"]
    if subscription.status in ENTITLED_STATUSES:
        return get_plan(subscription.plan)
    if (
        subscription.status == Subscription.Status.CANCELED
        and subscription.current_period_end
        and subscription.current_period_end > timezone.now()
    ):
        return get_plan(subscription.plan)
    return PLANS["free"]


def has_feature(user, feature: str) -> bool:
    return bool(active_plan(user).entitlements.get(feature))


def daily_submission_limit(user) -> int | None:
    return active_plan(user).entitlements.get("daily_submissions")


def ai_mentor_daily_limit(user) -> int:
    return int(active_plan(user).entitlements.get("ai_mentor_daily") or 0)


def usage(user, feature: str, period: date) -> int:
    record = UsageRecord.objects.filter(user=user, feature=feature, period=period).first()
    return record.count if record else 0


def consume(user, feature: str, period: date, limit: int | None) -> bool:
    """Atomically count one use; returns False (and counts nothing) when over the limit."""
    for _ in range(2):
        try:
            with transaction.atomic():
                record, _ = UsageRecord.objects.select_for_update().get_or_create(
                    user=user, feature=feature, period=period
                )
                if limit is not None and record.count >= limit:
                    return False
                UsageRecord.objects.filter(pk=record.pk).update(count=F("count") + 1)
                return True
        except IntegrityError:
            continue
    return False


def release(user, feature: str, period: date) -> None:
    """Give back one unit (e.g. when a request failed before reaching the provider)."""
    UsageRecord.objects.filter(user=user, feature=feature, period=period, count__gt=0).update(count=F("count") - 1)
