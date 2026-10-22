from __future__ import annotations

from datetime import timedelta

from django import forms
from django.utils import timezone

from apps.catalog.constants import FORMAT_CHOICES, GoalType
from apps.learning.models import LearningGoal

DAILY_CHOICES = [(m, f"{m} minutes") for m in (10, 15, 20, 30, 45)]


class GoalStepForm(forms.Form):
    goal_type = forms.ChoiceField(choices=GoalType.choices, widget=forms.RadioSelect, label="What's your main goal?")


class ExperienceStepForm(forms.Form):
    level = forms.ChoiceField(
        choices=LearningGoal.Level.choices,
        widget=forms.RadioSelect,
        label="How experienced are you with this today?",
    )
    take_diagnostic = forms.BooleanField(
        required=False,
        initial=True,
        label="Take a 2-minute placement check",
        help_text="Five quick questions. Your answers are graded and give the plan real evidence to start from.",
    )


class TimeStepForm(forms.Form):
    daily_minutes = forms.TypedChoiceField(
        coerce=int, choices=DAILY_CHOICES, widget=forms.RadioSelect, label="How much time can you practise each day?"
    )


class PreferencesStepForm(forms.Form):
    formats = forms.MultipleChoiceField(
        choices=FORMAT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="What kind of practice do you enjoy?",
        help_text="Pick any. You'll still see other formats now and then — variety helps learning stick.",
    )


class PlanStepForm(forms.Form):
    title = forms.CharField(max_length=140, label="Name your goal")
    path = forms.ChoiceField(label="Learning path")
    focus_skills = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Anything to prioritise?",
        help_text="Optional. Prioritised skills come up more often once their prerequisites are in place.",
    )
    target_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label="Target date", help_text="Optional."
    )

    def __init__(self, *args, paths=(), skills=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["path"].choices = [(p.slug, p.name) for p in paths]
        self.fields["focus_skills"].choices = [(s.slug, s.name) for s in skills]

    def clean_target_date(self):
        target = self.cleaned_data.get("target_date")
        if target is None:
            return None
        today = timezone.localdate()
        if target <= today:
            raise forms.ValidationError("Choose a date in the future.")
        if target > today + timedelta(days=365 * 3):
            raise forms.ValidationError("Choose a date within the next three years.")
        return target
