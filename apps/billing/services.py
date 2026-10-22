"""Subscription state transitions driven by verified provider events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from .adapters import DevAdapter, get_adapter
from .models import Subscription, WebhookEvent
from .plans import PAID_PLAN_CODES

logger = logging.getLogger(__name__)

STRIPE_STATUS_MAP = {
    "active": Subscription.Status.ACTIVE,
    "trialing": Subscription.Status.TRIALING,
    "past_due": Subscription.Status.PAST_DUE,
    "unpaid": Subscription.Status.PAST_DUE,
    "incomplete": Subscription.Status.INCOMPLETE,
    "incomplete_expired": Subscription.Status.EXPIRED,
    "canceled": Subscription.Status.CANCELED,
    "paused": Subscription.Status.PAST_DUE,
}


def _timestamp(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _plan_from_prices(obj: dict) -> str | None:
    price_to_plan = {price: plan for plan, price in settings.STRIPE_PRICE_IDS.items() if price}
    for item in (obj.get("items") or {}).get("data", []):
        price_id = (item.get("price") or {}).get("id")
        if price_id in price_to_plan:
            return price_to_plan[price_id]
    return None


def _period_end(obj: dict) -> datetime | None:
    # Newer Stripe API versions report the period on subscription items.
    if obj.get("current_period_end"):
        return _timestamp(obj["current_period_end"])
    ends = [item.get("current_period_end") for item in (obj.get("items") or {}).get("data", [])]
    ends = [e for e in ends if e]
    return _timestamp(max(ends)) if ends else None


def _subscription_for_user_id(user_id) -> Subscription | None:
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return None
    subscription, _ = Subscription.objects.select_for_update().get_or_create(user=user)
    return subscription


def _find_subscription(obj: dict) -> Subscription | None:
    sub_id = obj.get("id") if obj.get("object") == "subscription" else obj.get("subscription")
    if sub_id:
        found = (
            Subscription.objects.select_for_update()
            .filter(provider=Subscription.Provider.STRIPE, provider_subscription_id=sub_id)
            .first()
        )
        if found:
            return found
    metadata = obj.get("metadata") or {}
    if metadata.get("user_id"):
        return _subscription_for_user_id(metadata["user_id"])
    customer = obj.get("customer")
    if customer:
        return Subscription.objects.select_for_update().filter(provider_customer_id=customer).first()
    return None


def _apply_checkout_completed(obj: dict) -> str:
    user_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
    plan = (obj.get("metadata") or {}).get("plan")
    if not user_id or plan not in PAID_PLAN_CODES:
        return WebhookEvent.Status.IGNORED
    subscription = _subscription_for_user_id(user_id)
    if subscription is None:
        return WebhookEvent.Status.IGNORED
    paid = obj.get("payment_status") in {"paid", "no_payment_required"}
    subscription.plan = plan
    subscription.provider = Subscription.Provider.STRIPE
    subscription.provider_customer_id = obj.get("customer") or subscription.provider_customer_id
    subscription.provider_subscription_id = obj.get("subscription") or subscription.provider_subscription_id
    subscription.status = Subscription.Status.ACTIVE if paid else Subscription.Status.INCOMPLETE
    subscription.cancel_at_period_end = False
    subscription.save()
    return WebhookEvent.Status.PROCESSED


def _apply_subscription_change(obj: dict, deleted: bool) -> str:
    subscription = _find_subscription(obj)
    if subscription is None:
        return WebhookEvent.Status.IGNORED
    plan = (obj.get("metadata") or {}).get("plan") or _plan_from_prices(obj) or subscription.plan
    subscription.provider = Subscription.Provider.STRIPE
    subscription.provider_subscription_id = obj.get("id") or subscription.provider_subscription_id
    subscription.provider_customer_id = obj.get("customer") or subscription.provider_customer_id
    subscription.current_period_end = _period_end(obj) or subscription.current_period_end
    subscription.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    if deleted:
        subscription.status = Subscription.Status.EXPIRED
        subscription.plan = "free"
    else:
        subscription.status = STRIPE_STATUS_MAP.get(obj.get("status", ""), Subscription.Status.INCOMPLETE)
        if plan in PAID_PLAN_CODES:
            subscription.plan = plan
    subscription.save()
    return WebhookEvent.Status.PROCESSED


def _apply_payment_failed(obj: dict) -> str:
    subscription = _find_subscription(obj)
    if subscription is None:
        return WebhookEvent.Status.IGNORED
    subscription.status = Subscription.Status.PAST_DUE
    subscription.save(update_fields=["status", "updated_at"])
    from apps.notifications.models import Notification
    from apps.notifications.services import notify

    from .plans import get_plan

    notify(
        subscription.user,
        kind=Notification.Kind.BILLING,
        title="We couldn't process your payment",
        body="Please update your payment method in the billing portal to keep your plan.",
        url="/billing/",
        data={"template": "payment_failed", "plan": get_plan(subscription.plan).name},
        dedupe_key=f"payment_failed:{obj.get('id', '')}",
        email=True,
    )
    return WebhookEvent.Status.PROCESSED


HANDLERS = {
    "checkout.session.completed": lambda obj: _apply_checkout_completed(obj),
    "customer.subscription.created": lambda obj: _apply_subscription_change(obj, deleted=False),
    "customer.subscription.updated": lambda obj: _apply_subscription_change(obj, deleted=False),
    "customer.subscription.deleted": lambda obj: _apply_subscription_change(obj, deleted=True),
    "invoice.payment_failed": lambda obj: _apply_payment_failed(obj),
}


def process_stripe_event(event: dict) -> str:
    """Apply a verified Stripe event exactly once. Returns 'duplicate' for redeliveries.

    The idempotency record is written in the same transaction as the state
    change: if processing fails, both roll back and Stripe's retry is processed.
    """
    event_id = str(event.get("id", ""))
    event_type = str(event.get("type", ""))
    if not event_id:
        raise ValueError("Event has no id")
    if WebhookEvent.objects.filter(provider="stripe", event_id=event_id).exists():
        return "duplicate"
    handler = HANDLERS.get(event_type)
    try:
        with transaction.atomic():
            status = handler((event.get("data") or {}).get("object") or {}) if handler else WebhookEvent.Status.IGNORED
            WebhookEvent.objects.create(provider="stripe", event_id=event_id, event_type=event_type[:80], status=status)
    except IntegrityError:
        return "duplicate"
    logger.info("billing.webhook", extra={"event_type": event_type, "status": status})
    return status


@transaction.atomic
def activate_dev_plan(user, plan_code: str) -> Subscription:
    if not DevAdapter().available():
        raise PermissionError("Development billing is disabled.")
    if plan_code not in PAID_PLAN_CODES:
        raise ValueError("Unknown plan.")
    subscription, _ = Subscription.objects.select_for_update().get_or_create(user=user)
    subscription.plan = plan_code
    subscription.status = Subscription.Status.ACTIVE
    subscription.provider = Subscription.Provider.DEV
    subscription.current_period_end = timezone.now() + timedelta(days=30)
    subscription.cancel_at_period_end = False
    subscription.save()
    return subscription


@transaction.atomic
def cancel_dev_plan(user) -> None:
    if not DevAdapter().available():
        raise PermissionError("Development billing is disabled.")
    Subscription.objects.filter(user=user, provider=Subscription.Provider.DEV).update(
        plan="free", status=Subscription.Status.ACTIVE, provider=Subscription.Provider.NONE, current_period_end=None
    )


def cancel_subscription_for_deletion(user) -> None:
    subscription = Subscription.objects.filter(user=user).first()
    if subscription is None or subscription.provider != Subscription.Provider.STRIPE:
        return
    try:
        get_adapter().cancel_now(subscription)
    except Exception:
        logger.exception("billing.cancel_on_delete_failed", extra={"user_id": user.pk})


def expire_lapsed(now: datetime | None = None) -> int:
    now = now or timezone.now()
    return Subscription.objects.filter(status=Subscription.Status.CANCELED, current_period_end__lt=now).update(
        status=Subscription.Status.EXPIRED, plan="free"
    )
