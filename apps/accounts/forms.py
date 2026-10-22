from __future__ import annotations

import zoneinfo
from functools import lru_cache

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm

from apps.catalog.constants import FORMAT_CHOICES

from .models import Profile, User


@lru_cache(maxsize=1)
def timezone_choices() -> list[tuple[str, str]]:
    zones = sorted(z for z in zoneinfo.available_timezones() if "/" in z or z == "UTC")
    return [(z, z.replace("_", " ")) for z in zones]


class RegistrationForm(forms.Form):
    display_name = forms.CharField(
        label="Name",
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Ada Lovelace"}),
        help_text="Optional. Shown on your dashboard.",
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 10 characters. Avoid common or purely numeric passwords.",
    )
    timezone = forms.CharField(required=False, widget=forms.HiddenInput())
    accept_terms = forms.BooleanField(
        label="I agree to the Terms of Service and Privacy Policy",
        error_messages={"required": "Please accept the terms to create an account."},
    )

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists. Try logging in or resetting your password."
            )
        return email

    def clean_timezone(self) -> str:
        tz = self.cleaned_data.get("timezone") or "UTC"
        return tz if tz in zoneinfo.available_timezones() else "UTC"

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            probe = User(email=cleaned.get("email", ""), display_name=cleaned.get("display_name", ""))
            try:
                password_validation.validate_password(password, probe)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return cleaned


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    error_messages = {
        "invalid_login": "That email and password combination didn't match our records.",
        "inactive": "This account is inactive.",
    }

    def clean(self):
        email = (self.cleaned_data.get("username") or "").lower()
        password = self.cleaned_data.get("password")
        if email and password:
            self.user_cache = authenticate(self.request, username=email, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class QueuedPasswordResetForm(PasswordResetForm):
    """Same lookup rules as Django's form, but email is sent by a background task."""

    def save(self, *args, **kwargs) -> None:
        from django.db import transaction

        from .tasks import send_password_reset_email

        email = self.cleaned_data["email"]
        for user in self.get_users(email):
            user_id = user.pk
            transaction.on_commit(lambda uid=user_id: send_password_reset_email.delay(uid))


class ProfileForm(forms.ModelForm):
    timezone = forms.ChoiceField(choices=timezone_choices, help_text="Used for daily plans, streaks and reminders.")

    class Meta:
        model = Profile
        fields = ["timezone"]


class DisplayNameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name"]
        labels = {"display_name": "Display name"}


class LearningPreferencesForm(forms.ModelForm):
    preferred_formats = forms.MultipleChoiceField(
        choices=FORMAT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Preferred formats are recommended more often; others still appear for variety.",
    )

    class Meta:
        model = Profile
        fields = ["daily_minutes", "difficulty_preference", "preferred_formats"]
        widgets = {"daily_minutes": forms.RadioSelect, "difficulty_preference": forms.RadioSelect}


class NotificationPreferencesForm(forms.ModelForm):
    reminder_hour = forms.TypedChoiceField(
        coerce=int,
        choices=[(h, f"{h:02d}:00") for h in range(24)],
        help_text="Local time, in your profile timezone.",
    )

    class Meta:
        model = Profile
        fields = [
            "daily_reminder_enabled",
            "review_reminder_enabled",
            "milestone_emails_enabled",
            "reminder_hour",
        ]
        labels = {
            "daily_reminder_enabled": "Daily practice reminder",
            "review_reminder_enabled": "Due-review reminders",
            "milestone_emails_enabled": "Milestone and achievement emails",
        }
        help_texts = {
            "daily_reminder_enabled": "Only sent on days you haven't practised yet.",
            "review_reminder_enabled": "Sent at most once a day, only when reviews are due.",
        }


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["theme", "reduce_motion", "text_scale"]
        widgets = {"theme": forms.RadioSelect, "text_scale": forms.RadioSelect}
        labels = {"reduce_motion": "Reduce motion"}
        help_texts = {"reduce_motion": "Turns off non-essential animation, even if your system allows it."}


class EmailChangeForm(forms.Form):
    email = forms.EmailField(label="New email address")
    current_password = forms.CharField(
        label="Current password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

    def __init__(self, user: User, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if email == self.user.email:
            raise forms.ValidationError("That's already your email address.")
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email address can't be used.")
        return email

    def clean_current_password(self) -> str:
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Your current password is incorrect.")
        return password


class DeleteAccountForm(forms.Form):
    current_password = forms.CharField(
        label="Current password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )
    confirmation = forms.CharField(label='Type "DELETE" to confirm')

    def __init__(self, user: User, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self) -> str:
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Your current password is incorrect.")
        return password

    def clean_confirmation(self) -> str:
        value = self.cleaned_data["confirmation"].strip()
        if value != "DELETE":
            raise forms.ValidationError("Type DELETE in capital letters to confirm.")
        return value
