import hashlib
import hmac
import json
import time

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.billing import entitlements
from apps.billing.models import Subscription, WebhookEvent
from apps.billing.services import expire_lapsed, process_stripe_event

pytestmark = pytest.mark.django_db
SECRET = "whsec_test_secret"


def signed(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    signature = hmac.new(SECRET.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={signature}"


@pytest.fixture
def stripe_settings(settings):
    settings.BILLING_PROVIDER = "stripe"
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = SECRET
    settings.STRIPE_PRICE_IDS = {"pro": "price_pro", "interview": "price_int"}
    return settings


def checkout_event(user, event_id="evt_1", plan="pro"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "object": "checkout.session",
                "client_reference_id": str(user.pk),
                "customer": "cus_1",
                "subscription": "sub_1",
                "payment_status": "paid",
                "metadata": {"plan": plan, "user_id": str(user.pk)},
            }
        },
    }


def test_free_entitlements_by_default(learner):
    assert entitlements.active_plan(learner).code == "free"
    assert entitlements.daily_submission_limit(learner) == 8
    assert not entitlements.has_feature(learner, "advanced_analytics")


def test_paid_states_and_cancellation_window(learner):
    sub = Subscription.objects.create(user=learner, plan="pro", status="active", provider="stripe")
    assert entitlements.has_feature(learner, "advanced_analytics")
    sub.status = "canceled"
    sub.current_period_end = timezone.now() + timezone.timedelta(days=3)
    sub.save()
    learner.refresh_from_db()
    assert entitlements.active_plan(learner).code == "pro"  # paid period still running
    sub.current_period_end = timezone.now() - timezone.timedelta(days=1)
    sub.save()
    assert expire_lapsed() == 1
    learner.refresh_from_db()
    assert entitlements.active_plan(learner).code == "free"


def test_usage_quota_is_atomic_and_bounded(learner):
    day = timezone.localdate()
    assert all(entitlements.consume(learner, "ai_mentor", day, 2) for _ in range(2))
    assert not entitlements.consume(learner, "ai_mentor", day, 2)
    entitlements.release(learner, "ai_mentor", day)
    assert entitlements.usage(learner, "ai_mentor", day) == 1


def test_request_parameters_cannot_grant_paid_plans(auth_client, learner, settings):
    settings.BILLING_PROVIDER = ""
    response = auth_client.post(reverse("billing:checkout", args=["pro"]), {"plan": "pro", "status": "active"})
    assert response.status_code == 302
    assert auth_client.get(reverse("billing:dev_checkout", args=["pro"])).status_code == 404
    assert auth_client.post(reverse("billing:dev_checkout", args=["pro"])).status_code == 404
    assert auth_client.get(reverse("billing:index") + "?checkout=success").status_code == 200
    assert entitlements.active_plan(learner).code == "free"  # a success redirect proves nothing


def test_dev_adapter_only_with_debug(auth_client, learner, settings):
    settings.BILLING_PROVIDER = "dev"
    settings.DEBUG = False
    assert auth_client.post(reverse("billing:dev_checkout", args=["pro"])).status_code == 404
    settings.DEBUG = True
    assert auth_client.post(reverse("billing:dev_checkout", args=["pro"])).status_code == 302
    assert entitlements.active_plan(learner).code == "pro"


def test_webhook_rejects_bad_signatures(client, learner, stripe_settings):
    body, _ = signed(checkout_event(learner))
    response = client.post(
        reverse("billing:stripe_webhook"), body, content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=bad"
    )
    assert response.status_code == 400
    assert not Subscription.objects.filter(user=learner, plan="pro").exists()


def test_webhook_activates_plan_and_is_idempotent(client, learner, stripe_settings):
    body, sig = signed(checkout_event(learner))
    first = client.post(
        reverse("billing:stripe_webhook"), body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig
    )
    assert first.status_code == 200 and first.content == b"processed"
    sub = Subscription.objects.get(user=learner)
    assert (sub.plan, sub.status, sub.provider_subscription_id) == ("pro", "active", "sub_1")
    second = client.post(
        reverse("billing:stripe_webhook"), body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig
    )
    assert second.content == b"duplicate"
    assert WebhookEvent.objects.filter(event_id="evt_1").count() == 1


def test_subscription_state_transitions(learner, stripe_settings):
    process_stripe_event(checkout_event(learner))
    future = int(time.time()) + 86400 * 30
    process_stripe_event(
        {
            "id": "evt_2",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "object": "subscription",
                    "id": "sub_1",
                    "customer": "cus_1",
                    "status": "past_due",
                    "cancel_at_period_end": True,
                    "items": {"data": [{"price": {"id": "price_int"}, "current_period_end": future}]},
                }
            },
        }
    )
    sub = Subscription.objects.get(user=learner)
    assert sub.status == "past_due" and sub.plan == "interview" and sub.cancel_at_period_end
    assert sub.current_period_end is not None
    process_stripe_event(
        {
            "id": "evt_3",
            "type": "invoice.payment_failed",
            "data": {"object": {"id": "in_1", "subscription": "sub_1", "customer": "cus_1"}},
        }
    )
    assert learner.notifications.filter(kind="billing").exists()
    process_stripe_event(
        {
            "id": "evt_4",
            "type": "customer.subscription.deleted",
            "data": {"object": {"object": "subscription", "id": "sub_1", "customer": "cus_1", "status": "canceled"}},
        }
    )
    sub.refresh_from_db()
    assert (sub.plan, sub.status) == ("free", "expired")
    assert process_stripe_event({"id": "evt_5", "type": "something.else", "data": {"object": {}}}) == "ignored"


def test_unpaid_checkout_does_not_grant_access(learner, stripe_settings):
    event = checkout_event(learner, event_id="evt_unpaid")
    event["data"]["object"]["payment_status"] = "unpaid"
    process_stripe_event(event)
    assert Subscription.objects.get(user=learner).status == "incomplete"
    assert entitlements.active_plan(learner).code == "free"


def test_failed_processing_rolls_back_so_retry_can_succeed(learner, stripe_settings, monkeypatch):
    from apps.billing import services

    def boom(obj):
        raise RuntimeError("db down")

    monkeypatch.setitem(services.HANDLERS, "checkout.session.completed", boom)
    with pytest.raises(RuntimeError):
        process_stripe_event(checkout_event(learner, event_id="evt_retry"))
    assert not WebhookEvent.objects.filter(event_id="evt_retry").exists()
    monkeypatch.undo()
    assert process_stripe_event(checkout_event(learner, event_id="evt_retry")) == "processed"
