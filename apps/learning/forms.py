from __future__ import annotations

from datetime import date, timedelta

from django import forms
from django.utils import timezone

from apps.catalog.constants import ChallengeKind, GoalType
from apps.catalog.models import LearningPath, Skill

from .models import LearningGoal

DAILY_CHOICES = [(m, f"{m} min") for m in (10, 15, 20, 30, 45)]
MAX_TARGET_YEARS = 3


class GoalForm(forms.ModelForm):
    daily_minutes = forms.TypedChoiceField(coerce=int, choices=DAILY_CHOICES, widget=forms.RadioSelect)
    path = forms.ModelChoiceField(
        queryset=LearningPath.objects.none(),
        required=False,
        empty_label="No path — practise my focus skills only",
        help_text="A curated path gives your goal a structure and milestones.",
    )
    focus_skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Optional. Prioritised skills are recommended more often.",
    )
    target_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), help_text="Optional deadline."
    )

    class Meta:
        model = LearningGoal
        fields = ["title", "goal_type", "path", "experience_level", "daily_minutes", "target_date", "motivation"]
        labels = {
            "goal_type": "Goal area",
            "experience_level": "Current level",
            "motivation": "Why this matters to you",
        }
        widgets = {"motivation": forms.Textarea(attrs={"rows": 3, "maxlength": 600})}

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["path"].queryset = LearningPath.objects.filter(is_active=True, current_version__isnull=False)
        self.fields["focus_skills"].queryset = Skill.objects.active().select_related("category")
        if self.instance.pk:
            self.fields["focus_skills"].initial = list(self.instance.focus_skills.values_list("pk", flat=True))

    def clean_target_date(self) -> date | None:
        target = self.cleaned_data.get("target_date")
        if target is None:
            return None
        today = timezone.localdate()
        if target <= today:
            raise forms.ValidationError("Choose a date in the future.")
        if target > today + timedelta(days=365 * MAX_TARGET_YEARS):
            raise forms.ValidationError(f"Choose a date within the next {MAX_TARGET_YEARS} years.")
        return target

    def clean(self):
        cleaned = super().clean()
        path = cleaned.get("path")
        if not path and not cleaned.get("focus_skills"):
            raise forms.ValidationError("Choose a learning path or at least one focus skill.")
        if path and path.is_premium and self.user is not None:
            from apps.billing.entitlements import has_feature

            if not has_feature(self.user, "premium_paths"):
                self.add_error("path", "This path is part of the Pro plan.")
        return cleaned


class HistoryFilterForm(forms.Form):
    RESULT_CHOICES = [
        ("", "Any result"),
        ("correct", "Correct"),
        ("partial", "Partially correct"),
        ("incorrect", "Incorrect"),
        ("pending", "Awaiting evaluation"),
    ]
    q = forms.CharField(
        required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Challenge title…"})
    )
    skill = forms.ModelChoiceField(
        queryset=Skill.objects.none(), required=False, empty_label="All skills", to_field_name="slug"
    )
    kind = forms.ChoiceField(choices=[("", "All formats"), *ChallengeKind.choices], required=False, label="Format")
    result = forms.ChoiceField(choices=RESULT_CHOICES, required=False)
    start = forms.DateField(required=False, label="From", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, label="To", widget=forms.DateInput(attrs={"type": "date"}))
    reviews = forms.BooleanField(required=False, label="Reviews only")
    hints = forms.BooleanField(required=False, label="Used hints")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["skill"].queryset = Skill.objects.filter(challenges__attempts__user=user).distinct()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("end") and cleaned["start"] > cleaned["end"]:
            self.add_error("end", "The end date must be after the start date.")
        return cleaned


GOAL_TYPE_CHOICES = GoalType.choices
