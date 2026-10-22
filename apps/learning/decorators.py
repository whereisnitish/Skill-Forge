from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

ONBOARDED_SESSION_KEY = "sf_onboarded"


def has_completed_onboarding(request: HttpRequest) -> bool:
    if request.session.get(ONBOARDED_SESSION_KEY):
        return True
    from apps.onboarding.models import OnboardingState

    done = OnboardingState.objects.filter(user=request.user, completed_at__isnull=False).exists()
    if done:
        request.session[ONBOARDED_SESSION_KEY] = True
    return done


def learner_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Signed-in learners who have finished onboarding; others are sent to the wizard."""

    @wraps(view)
    @login_required
    def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not has_completed_onboarding(request):
            if getattr(request, "htmx", False):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse("onboarding:start")
                return response
            return redirect("onboarding:start")
        return view(request, *args, **kwargs)

    return wrapped
