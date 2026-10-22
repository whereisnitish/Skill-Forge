from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.ratelimit import ratelimit
from apps.core.timeutils import local_date

from . import services
from .adapters import BillingUnavailable, DevAdapter, get_adapter
from .entitlements import active_plan, ai_mentor_daily_limit, daily_submission_limit, subscription_for, usage
from .plans import PAID_PLAN_CODES, PLANS

logger = logging.getLogger(__name__)


@login_required
def index(request: HttpRequest) -> HttpResponse:
    adapter = get_adapter()
    today = local_date(request.user)
    checkout = request.GET.get("checkout")
    if checkout == "success":
        messages.info(
            request,
            "Thanks! Your plan updates as soon as the payment provider confirms the payment — usually within a minute.",
        )
    elif checkout == "cancelled":
        messages.info(request, "Checkout was cancelled. You haven't been charged.")
    context = {
        "plans": list(PLANS.values()),
        "current_plan": active_plan(request.user),
        "subscription": subscription_for(request.user),
        "adapter": adapter,
        "billing_available": adapter.available(),
        "dev_billing": isinstance(adapter, DevAdapter),
        "mentor_used": usage(request.user, "ai_mentor", today),
        "mentor_limit": ai_mentor_daily_limit(request.user),
        "submission_limit": daily_submission_limit(request.user),
    }
    return render(request, "billing/index.html", context)


@login_required
@require_POST
@ratelimit("billing-checkout", rate="10/h", key="user")
def checkout(request: HttpRequest, plan: str) -> HttpResponse:
    if plan not in PAID_PLAN_CODES:
        raise Http404
    try:
        url = get_adapter().checkout_url(request.user, plan)
    except BillingUnavailable as exc:
        messages.warning(request, str(exc))
        return redirect("billing:index")
    except Exception:
        logger.exception("billing.checkout_failed", extra={"user_id": request.user.pk})
        messages.error(request, "We couldn't start checkout. Please try again in a moment.")
        return redirect("billing:index")
    return redirect(url, permanent=False)


@login_required
@require_POST
def portal(request: HttpRequest) -> HttpResponse:
    try:
        url = get_adapter().portal_url(request.user)
    except Exception:
        logger.exception("billing.portal_failed", extra={"user_id": request.user.pk})
        url = None
    if not url:
        messages.warning(request, "The billing portal isn't available for your account.")
        return redirect("billing:index")
    return redirect(url)


def _require_dev() -> None:
    if not DevAdapter().available():
        raise Http404


@login_required
@require_http_methods(["GET", "POST"])
def dev_checkout(request: HttpRequest, plan: str) -> HttpResponse:
    _require_dev()
    if plan not in PAID_PLAN_CODES:
        raise Http404
    if request.method == "POST":
        services.activate_dev_plan(request.user, plan)
        messages.success(request, f"Development plan switched to {PLANS[plan].name}. No payment was taken.")
        return redirect("billing:index")
    return render(request, "billing/dev_checkout.html", {"plan": PLANS[plan]})


@login_required
@require_POST
def dev_cancel(request: HttpRequest) -> HttpResponse:
    _require_dev()
    services.cancel_dev_plan(request.user)
    messages.info(request, "Development plan reset to Free.")
    return redirect("billing:index")


@csrf_exempt  # Authenticated by the Stripe signature, not a browser session.
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    if settings.BILLING_PROVIDER != "stripe" or not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=404)
    import stripe

    payload = request.body
    signature = request.headers.get("Stripe-Signature", "")
    try:
        stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        logger.warning("billing.webhook_rejected")
        return HttpResponseBadRequest("invalid signature")
    try:
        event = json.loads(payload)
        result = services.process_stripe_event(event)
    except Exception:
        logger.exception("billing.webhook_failed")
        return HttpResponse(status=500)
    return HttpResponse(result, status=200, content_type="text/plain")
