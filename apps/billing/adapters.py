"""Payment provider adapters.

* StripeAdapter — real Checkout + Billing Portal; plan changes are applied only
  from signature-verified webhooks, never from the browser redirect.
* DevAdapter — local development only (requires DEBUG and BILLING_PROVIDER=dev);
  clearly labelled, takes no payment, and is refused by production settings.
* DisabledAdapter — no provider configured: paid plans are shown as unavailable.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.urls import reverse

from .models import Subscription

logger = logging.getLogger(__name__)


class BillingUnavailable(RuntimeError):
    pass


class DisabledAdapter:
    name = "none"
    label = "Not configured"

    def available(self) -> bool:
        return False

    def checkout_url(self, user, plan_code: str) -> str:
        raise BillingUnavailable("Paid plans aren't available yet.")

    def portal_url(self, user) -> str | None:
        return None

    def cancel_now(self, subscription: Subscription) -> None:
        return None


class DevAdapter(DisabledAdapter):
    name = "dev"
    label = "Development billing (no real payments)"

    def available(self) -> bool:
        return bool(settings.DEBUG and settings.BILLING_PROVIDER == "dev")

    def checkout_url(self, user, plan_code: str) -> str:
        if not self.available():
            raise BillingUnavailable("Development billing is disabled.")
        return reverse("billing:dev_checkout", args=[plan_code])


class StripeAdapter(DisabledAdapter):
    name = "stripe"
    label = "Stripe"

    def available(self) -> bool:
        return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET)

    def _client(self):
        import stripe

        return stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    def checkout_url(self, user, plan_code: str) -> str:
        price = settings.STRIPE_PRICE_IDS.get(plan_code)
        if not self.available() or not price:
            raise BillingUnavailable("This plan isn't available for purchase yet.")
        subscription = getattr(user, "subscription", None)
        params = {
            "mode": "subscription",
            "line_items": [{"price": price, "quantity": 1}],
            "client_reference_id": str(user.pk),
            "metadata": {"user_id": str(user.pk), "plan": plan_code},
            "subscription_data": {"metadata": {"user_id": str(user.pk), "plan": plan_code}},
            "success_url": settings.SITE_URL + reverse("billing:index") + "?checkout=success",
            "cancel_url": settings.SITE_URL + reverse("billing:index") + "?checkout=cancelled",
        }
        if subscription and subscription.provider_customer_id:
            params["customer"] = subscription.provider_customer_id
        else:
            params["customer_email"] = user.email
        session = self._client().v1.checkout.sessions.create(params=params)
        return session.url

    def portal_url(self, user) -> str | None:
        subscription = getattr(user, "subscription", None)
        if not self.available() or not subscription or not subscription.provider_customer_id:
            return None
        session = self._client().v1.billing_portal.sessions.create(
            params={
                "customer": subscription.provider_customer_id,
                "return_url": settings.SITE_URL + reverse("billing:index"),
            }
        )
        return session.url

    def cancel_now(self, subscription: Subscription) -> None:
        if subscription.provider_subscription_id:
            self._client().v1.subscriptions.cancel(subscription.provider_subscription_id)


def get_adapter() -> DisabledAdapter:
    provider = settings.BILLING_PROVIDER
    if provider == "stripe":
        return StripeAdapter()
    if provider == "dev":
        adapter = DevAdapter()
        return adapter if adapter.available() else DisabledAdapter()
    return DisabledAdapter()
