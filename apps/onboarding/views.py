from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.views import PLAN_SESSION_KEY
from apps.catalog.constants import FORMAT_FAMILIES, GOAL_ICONS, GoalType
from apps.catalog.models import LearningPath
from apps.learning.decorators import ONBOARDED_SESSION_KEY
from apps.learning.services.planning import load_milestones

from . import services
from .forms import ExperienceStepForm, GoalStepForm, PlanStepForm, PreferencesStepForm, TimeStepForm
from .models import OnboardingState

GOAL_DESCRIPTIONS = {
    GoalType.PYTHON: "Idiomatic, robust Python: generators, decorators, typing, async.",
    GoalType.INTERVIEWS: "Problem-solving patterns, complexity and talking through trade-offs.",
    GoalType.DJANGO: "Models, queries, transactions, security and background work.",
    GoalType.AI: "Prompts, structured output, retrieval, evaluation and tool use.",
    GoalType.SYSTEM_DESIGN: "Scaling, caching, partitioning and consistency trade-offs.",
    GoalType.COMMUNICATION: "PR descriptions, review feedback and incident updates.",
}
LEVEL_DESCRIPTIONS = {
    "beginner": "I'm new to this or only know the basics.",
    "intermediate": "I use this regularly but have gaps.",
    "advanced": "I'm comfortable and want depth and edge cases.",
}
STEP_LABELS = ["Goal", "Experience", "Time", "Preferences", "Your plan"]


def _context(state: OnboardingState, step: str, **extra) -> dict:
    return {
        "state": state,
        "step": step,
        "step_number": OnboardingState.STEPS.index(step) + 1 if step in OnboardingState.STEPS else 2,
        "step_labels": STEP_LABELS,
        **extra,
    }


@login_required
def start(request: HttpRequest) -> HttpResponse:
    state = services.get_state(request.user)
    if state.is_complete:
        return redirect("learning:today")
    return redirect("onboarding:step", step=state.step)


@login_required
@require_http_methods(["GET", "POST"])
def step(request: HttpRequest, step: str) -> HttpResponse:
    state = services.get_state(request.user)
    if state.is_complete:
        return redirect("learning:today")
    handlers = {
        "goal": _goal,
        "experience": _experience,
        "diagnostic": _diagnostic,
        "time": _time,
        "preferences": _preferences,
        "plan": _plan,
    }
    handler = handlers.get(step)
    if handler is None:
        raise Http404
    if step != "goal" and "goal_type" not in state.data:
        return redirect("onboarding:step", step="goal")
    return handler(request, state)


def _goal(request: HttpRequest, state: OnboardingState) -> HttpResponse:
    form = GoalStepForm(request.POST or None, initial={"goal_type": state.data.get("goal_type")})
    if request.method == "POST" and form.is_valid():
        goal_type = form.cleaned_data["goal_type"]
        if goal_type != state.data.get("goal_type"):
            state.diagnostic_challenge_ids = []
            state.diagnostic_completed = False
            state.save(update_fields=["diagnostic_challenge_ids", "diagnostic_completed", "updated_at"])
        services.save_step(state, "experience", goal_type=goal_type)
        return redirect("onboarding:step", step="experience")
    options = [
        {"value": value, "label": label, "icon": GOAL_ICONS[value], "description": GOAL_DESCRIPTIONS[value]}
        for value, label in GoalType.choices
    ]
    return render(request, "onboarding/goal.html", _context(state, "goal", form=form, options=options))


def _experience(request: HttpRequest, state: OnboardingState) -> HttpResponse:
    form = ExperienceStepForm(
        request.POST or None,
        initial={"level": state.data.get("level", "beginner"), "take_diagnostic": not state.diagnostic_completed},
    )
    if request.method == "POST" and form.is_valid():
        level = form.cleaned_data["level"]
        profile = request.user.profile
        profile.experience_level = level
        profile.save(update_fields=["experience_level", "updated_at"])
        take = form.cleaned_data["take_diagnostic"] and not state.diagnostic_completed
        services.save_step(state, "diagnostic" if take else "time", level=level)
        return redirect("onboarding:step", step="diagnostic" if take else "time")
    levels = [
        {"value": v, "label": label, "description": LEVEL_DESCRIPTIONS[v]} for v, label in form.fields["level"].choices
    ]
    return render(request, "onboarding/experience.html", _context(state, "experience", form=form, levels=levels))


def _diagnostic(request: HttpRequest, state: OnboardingState) -> HttpResponse:
    if state.diagnostic_completed:
        return redirect("onboarding:step", step="time")
    if not state.diagnostic_challenge_ids:
        challenges = services.diagnostic_challenges(state.data["goal_type"])
        state.diagnostic_challenge_ids = [c.pk for c in challenges]
        state.save(update_fields=["diagnostic_challenge_ids", "updated_at"])
    from apps.catalog.models import Challenge

    by_id = {
        c.pk: c
        for c in Challenge.objects.published()
        .filter(pk__in=state.diagnostic_challenge_ids)
        .select_related("current_version", "skill")
    }
    challenges = [by_id[i] for i in state.diagnostic_challenge_ids if i in by_id]
    if not challenges:
        messages.info(request, "No placement questions are available for this goal yet — we'll calibrate as you go.")
        services.save_step(state, "time")
        return redirect("onboarding:step", step="time")

    if request.method == "POST":
        if request.POST.get("action") == "skip":
            state.diagnostic_completed = True
            state.save(update_fields=["diagnostic_completed", "updated_at"])
            services.save_step(state, "time", diagnostic={"answered": 0, "correct": 0, "skipped": len(challenges)})
            return redirect("onboarding:step", step="time")
        answers = {c.pk: request.POST.get(f"q{c.pk}", "") for c in challenges}
        results = services.record_diagnostic(request.user, challenges, answers)
        state.diagnostic_completed = True
        state.save(update_fields=["diagnostic_completed", "updated_at"])
        services.save_step(state, "time", diagnostic=results)
        messages.success(
            request, f"Placement check done: {results['correct']} of {results['answered']} answered correctly."
        )
        return redirect("onboarding:step", step="time")
    return render(
        request,
        "onboarding/diagnostic.html",
        _context(state, "diagnostic", challenges=challenges, skip_value=services.SKIP_VALUE),
    )


def _time(request: HttpRequest, state: OnboardingState) -> HttpResponse:
    form = TimeStepForm(request.POST or None, initial={"daily_minutes": state.data.get("daily_minutes", 15)})
    if request.method == "POST" and form.is_valid():
        services.save_step(state, "preferences", daily_minutes=form.cleaned_data["daily_minutes"])
        return redirect("onboarding:step", step="preferences")
    return render(request, "onboarding/time.html", _context(state, "time", form=form))


def _preferences(request: HttpRequest, state: OnboardingState) -> HttpResponse:
    form = PreferencesStepForm(request.POST or None, initial={"formats": state.data.get("formats", [])})
    if request.method == "POST" and form.is_valid():
        services.save_step(state, "plan", formats=form.cleaned_data["formats"])
        return redirect("onboarding:step", step="plan")
    families = [{"value": k, **v} for k, v in FORMAT_FAMILIES.items()]
    return render(request, "onboarding/preferences.html", _context(state, "preferences", form=form, families=families))


def _plan(request: HttpRequest, state: OnboardingState) -> HttpResponse:
    goal_type = state.data["goal_type"]
    paths = services.available_paths(request.user, goal_type)
    if not paths:
        messages.error(request, "No learning path is available for that goal yet. Please choose another goal.")
        return redirect("onboarding:step", step="goal")
    chosen_slug = request.POST.get("path") or request.GET.get("path") or state.data.get("path") or paths[0].slug
    path = next((p for p in paths if p.slug == chosen_slug), paths[0])
    skills = services.path_skills(path)
    form = PlanStepForm(
        request.POST or None,
        paths=paths,
        skills=skills,
        initial={"title": GoalType(goal_type).label, "path": path.slug, "focus_skills": state.data.get("focus", [])},
    )
    if request.method == "POST" and request.POST.get("action") == "confirm" and form.is_valid():
        data = form.cleaned_data
        selected = next(p for p in paths if p.slug == data["path"])
        services.complete_onboarding(
            request.user,
            state,
            title=data["title"],
            path=selected,
            focus_slugs=data["focus_skills"],
            target_date=data["target_date"],
        )
        request.session[ONBOARDED_SESSION_KEY] = True
        plan = request.session.pop(PLAN_SESSION_KEY, None)
        messages.success(request, "Your plan is ready. Here's your first challenge.")
        if plan in {"pro", "interview"}:
            messages.info(request, "You picked a paid plan when signing up — you can upgrade any time from Billing.")
        return redirect("learning:today")
    if request.method == "POST" and request.POST.get("action") == "change_path":
        services.save_step(state, "plan", path=path.slug)
        return redirect(f"{request.path}?path={path.slug}")
    milestones = load_milestones(path.current_version_id)
    return render(
        request,
        "onboarding/plan.html",
        _context(
            state,
            "plan",
            form=form,
            path=path,
            paths=paths,
            milestones=milestones,
            daily_minutes=state.data.get("daily_minutes", 15),
            formats=[FORMAT_FAMILIES[f]["label"] for f in state.data.get("formats", []) if f in FORMAT_FAMILIES],
            diagnostic=state.data.get("diagnostic"),
            premium_paths=LearningPath.objects.filter(goal_type=goal_type, is_premium=True, is_active=True).exclude(
                pk__in=[p.pk for p in paths]
            ),
        ),
    )
