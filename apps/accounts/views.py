from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth import views as auth_views
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_http_methods

from apps.core.ratelimit import is_limited, ratelimit

from . import services
from .forms import LoginForm, QueuedPasswordResetForm, RegistrationForm
from .tokens import email_verification_token

logger = logging.getLogger(__name__)

PLAN_SESSION_KEY = "sf_selected_plan"
ALLOWED_SIGNUP_PLANS = {"free", "pro", "interview", "teams"}


@require_http_methods(["GET", "POST"])
@ratelimit("register", rate="5/h", key="ip")
def register(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("learning:today")

    plan = request.GET.get("plan") or request.POST.get("plan") or ""
    if plan in ALLOWED_SIGNUP_PLANS:
        request.session[PLAN_SESSION_KEY] = plan

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        user = services.register_user(
            email=data["email"],
            password=data["password"],
            display_name=data["display_name"],
            tz=data["timezone"],
        )
        selected = request.session.get(PLAN_SESSION_KEY)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        if selected:
            request.session[PLAN_SESSION_KEY] = selected
        messages.success(request, "Welcome to SkillForge! We've sent a link to verify your email.")
        return redirect("onboarding:start")
    return render(
        request,
        "accounts/register.html",
        {"form": form, "plan": request.session.get(PLAN_SESSION_KEY, "")},
    )


@method_decorator(require_http_methods(["GET", "POST"]), name="dispatch")
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("username") or "").strip().lower()
        if is_limited(request, "login-ip", "ip", "20/m") or (
            email and is_limited(request, "login-email", lambda r: email, "8/m")
        ):
            from apps.core.views import rate_limited

            return rate_limited(request)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        logger.info("account.login", extra={"user_id": form.get_user().pk})
        return super().form_valid(form)


class LogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("marketing:home")


@method_decorator(ratelimit("password-reset", rate="5/h", key="ip"), name="post")
class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = QueuedPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@require_http_methods(["GET"])
def verify_email(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, user_model.DoesNotExist):
        user = None

    if user is not None and user.is_email_verified:
        return render(request, "accounts/verify_email_result.html", {"status": "already"})
    if user is None or not email_verification_token.check_token(user, token):
        return render(request, "accounts/verify_email_result.html", {"status": "invalid"}, status=400)

    services.mark_email_verified(user)
    return render(request, "accounts/verify_email_result.html", {"status": "verified"})


@require_http_methods(["POST"])
@ratelimit("verify-resend", rate="3/h", key="user_or_ip")
def resend_verification(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.user.is_email_verified:
        messages.info(request, "Your email address is already verified.")
    else:
        services.queue_verification_email(request.user)
        messages.success(request, f"We've sent a new verification link to {request.user.email}.")
    target = request.POST.get("next") or reverse("accounts_settings:index")
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        target = reverse("accounts_settings:index")
    return redirect(target)


def logout_and_redirect(request: HttpRequest, message: str) -> HttpResponse:
    logout(request)
    messages.info(request, message)
    return redirect("marketing:home")
