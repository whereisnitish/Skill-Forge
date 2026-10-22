"""Profile & preference management. Each settings card posts independently via HTMX."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.ratelimit import ratelimit

from . import services
from .forms import (
    AppearanceForm,
    DeleteAccountForm,
    DisplayNameForm,
    EmailChangeForm,
    LearningPreferencesForm,
    NotificationPreferencesForm,
    ProfileForm,
)
from .views import logout_and_redirect

SECTIONS = {
    "profile": "accounts/settings/_profile.html",
    "learning": "accounts/settings/_learning.html",
    "notifications": "accounts/settings/_notifications.html",
    "appearance": "accounts/settings/_appearance.html",
    "email": "accounts/settings/_email.html",
    "password": "accounts/settings/_password.html",
}


def _forms(request: HttpRequest) -> dict:
    user = request.user
    profile = user.profile
    return {
        "name_form": DisplayNameForm(instance=user, prefix="name"),
        "profile_form": ProfileForm(instance=profile, prefix="profile"),
        "learning_form": LearningPreferencesForm(instance=profile, prefix="learning"),
        "notifications_form": NotificationPreferencesForm(instance=profile, prefix="notifications"),
        "appearance_form": AppearanceForm(instance=profile, prefix="appearance"),
        "email_form": EmailChangeForm(user, prefix="email"),
        "password_form": PasswordChangeForm(user, prefix="password"),
    }


@login_required
def index(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/settings/index.html", _forms(request))


def _respond(request: HttpRequest, section: str, context: dict, saved: bool) -> HttpResponse:
    if request.htmx:
        context["saved"] = saved
        response = render(request, SECTIONS[section], context)
        if saved and section == "appearance":
            response["HX-Refresh"] = "true"
        return response
    if saved:
        messages.success(request, "Your changes have been saved.")
        return redirect(reverse("accounts_settings:index") + f"#{section}")
    full = _forms(request)
    full.update(context)
    return render(request, "accounts/settings/index.html", full, status=200)


@login_required
@require_POST
def update_profile(request: HttpRequest) -> HttpResponse:
    user = request.user
    name_form = DisplayNameForm(request.POST, instance=user, prefix="name")
    profile_form = ProfileForm(request.POST, instance=user.profile, prefix="profile")
    saved = name_form.is_valid() and profile_form.is_valid()
    if saved:
        name_form.save()
        profile_form.save()
    return _respond(request, "profile", {"name_form": name_form, "profile_form": profile_form}, saved)


@login_required
@require_POST
def update_learning(request: HttpRequest) -> HttpResponse:
    form = LearningPreferencesForm(request.POST, instance=request.user.profile, prefix="learning")
    saved = form.is_valid()
    if saved:
        profile = form.save()
        from apps.learning.services.goals import update_goal
        from apps.learning.services.sessions import primary_goal, refresh_today_budget

        goal = primary_goal(request.user)
        if goal is not None and goal.daily_minutes != profile.daily_minutes:
            update_goal(goal, changes={"daily_minutes": profile.daily_minutes})
        refresh_today_budget(request.user)
    return _respond(request, "learning", {"learning_form": form}, saved)


@login_required
@require_POST
def update_notifications(request: HttpRequest) -> HttpResponse:
    form = NotificationPreferencesForm(request.POST, instance=request.user.profile, prefix="notifications")
    saved = form.is_valid()
    if saved:
        form.save()
    return _respond(request, "notifications", {"notifications_form": form}, saved)


@login_required
@require_POST
def update_appearance(request: HttpRequest) -> HttpResponse:
    form = AppearanceForm(request.POST, instance=request.user.profile, prefix="appearance")
    saved = form.is_valid()
    if saved:
        form.save()
    response = _respond(request, "appearance", {"appearance_form": form}, saved)
    if saved:
        response.set_cookie("sf_theme", form.cleaned_data["theme"], max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@require_POST
def set_theme(request: HttpRequest) -> HttpResponse:
    """Quick theme switch from the top bar; works signed in or out."""
    theme = request.POST.get("theme", "")
    if theme not in {"dark", "light", "system"}:
        return HttpResponse(status=400)
    if request.user.is_authenticated:
        profile = request.user.profile
        profile.theme = theme
        profile.save(update_fields=["theme", "updated_at"])
    response = HttpResponse(status=204)
    response.set_cookie("sf_theme", theme, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@login_required
@require_POST
@ratelimit("email-change", rate="5/h", key="user")
def change_email(request: HttpRequest) -> HttpResponse:
    form = EmailChangeForm(request.user, request.POST, prefix="email")
    saved = form.is_valid()
    if saved:
        services.change_email(request.user, form.cleaned_data["email"])
        form = EmailChangeForm(request.user, prefix="email")
    return _respond(request, "email", {"email_form": form}, saved)


@login_required
@require_POST
@ratelimit("password-change", rate="10/h", key="user")
def change_password(request: HttpRequest) -> HttpResponse:
    form = PasswordChangeForm(request.user, request.POST, prefix="password")
    saved = form.is_valid()
    if saved:
        user = form.save()
        update_session_auth_hash(request, user)
        form = PasswordChangeForm(request.user, prefix="password")
    return _respond(request, "password", {"password_form": form}, saved)


@login_required
@require_http_methods(["GET", "POST"])
@ratelimit("delete-account", rate="5/h", key="user")
def delete_account(request: HttpRequest) -> HttpResponse:
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        services.delete_account(user)
        return logout_and_redirect(request, "Your account and learning data have been permanently deleted.")
    return render(request, "accounts/settings/delete.html", {"form": form})
