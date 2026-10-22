from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.catalog.models import LearningPath

from ..decorators import learner_required
from ..forms import GoalForm
from ..models import LearningAttempt, LearningEvent, LearningGoal, MilestoneCompletion
from ..services import goals as goal_service
from ..services.planning import goal_context
from ..services.snapshot import LearnerSnapshot


@learner_required
def goal_list(request: HttpRequest) -> HttpResponse:
    goals = list(LearningGoal.objects.filter(user=request.user).select_related("path"))
    snapshot = LearnerSnapshot.load(request.user)
    progress = {}
    for goal in goals:
        if goal.path_version_id and goal.status != LearningGoal.Status.ARCHIVED:
            progress[goal.pk] = goal_context(goal, snapshot).progress
    return render(request, "learning/goals/list.html", {"goals": goals, "progress": progress})


@learner_required
@require_http_methods(["GET", "POST"])
def goal_create(request: HttpRequest) -> HttpResponse:
    initial = {
        "daily_minutes": request.user.profile.daily_minutes,
        "experience_level": request.user.profile.experience_level,
    }
    path_slug = request.GET.get("path")
    if path_slug:
        path = LearningPath.objects.filter(slug=path_slug, is_active=True).first()
        if path:
            initial.update({"path": path, "goal_type": path.goal_type, "title": path.name})
    form = GoalForm(request.POST or None, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        goal = goal_service.create_goal(
            request.user,
            title=data["title"],
            goal_type=data["goal_type"],
            path=data["path"],
            experience_level=data["experience_level"],
            daily_minutes=data["daily_minutes"],
            target_date=data["target_date"],
            motivation=data["motivation"],
            focus_skills=list(data["focus_skills"]),
            primary=request.POST.get("make_primary") == "on" or None,
        )
        messages.success(request, f"Goal “{goal.title}” created.")
        return redirect("learning:goal_detail", pk=goal.pk)
    return render(request, "learning/goals/form.html", {"form": form, "creating": True})


@learner_required
@require_http_methods(["GET", "POST"])
def goal_edit(request: HttpRequest, pk: int) -> HttpResponse:
    goal = get_object_or_404(LearningGoal, pk=pk, user=request.user)
    form = GoalForm(request.POST or None, instance=goal, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        goal_service.update_goal(
            LearningGoal.objects.get(pk=goal.pk),
            changes={
                "title": data["title"],
                "goal_type": data["goal_type"],
                "path": data["path"],
                "experience_level": data["experience_level"],
                "daily_minutes": data["daily_minutes"],
                "target_date": data["target_date"],
                "motivation": data["motivation"],
            },
            focus_skills=list(data["focus_skills"]),
        )
        messages.success(request, "Goal updated. Your next recommendations will reflect the changes.")
        return redirect("learning:goal_detail", pk=goal.pk)
    return render(request, "learning/goals/form.html", {"form": form, "goal": goal, "creating": False})


@learner_required
def goal_detail(request: HttpRequest, pk: int) -> HttpResponse:
    goal = get_object_or_404(LearningGoal.objects.select_related("path", "path_version"), pk=pk, user=request.user)
    snapshot = LearnerSnapshot.load(request.user, level=goal.experience_level)
    context = goal_context(goal, snapshot)
    completions = {c.milestone_id: c for c in MilestoneCompletion.objects.filter(goal=goal).select_related("milestone")}
    events = LearningEvent.objects.filter(
        goal=goal,
        event_type__in=[
            LearningEvent.Type.GOAL_CREATED,
            LearningEvent.Type.GOAL_UPDATED,
            LearningEvent.Type.GOAL_STATUS_CHANGED,
            LearningEvent.Type.MILESTONE_COMPLETED,
        ],
    )[:12]
    attempts = LearningAttempt.objects.filter(goal=goal).count()
    focus = goal.focus_skills.all()
    newer_version = (
        goal.path_id and goal.path.current_version_id and goal.path_version_id != goal.path.current_version_id
    )
    return render(
        request,
        "learning/goals/detail.html",
        {
            "goal": goal,
            "progress": context.progress,
            "completions": completions,
            "events": events,
            "attempt_count": attempts,
            "focus_skills": focus,
            "snapshot": snapshot,
            "newer_version": newer_version,
        },
    )


@learner_required
@require_POST
def goal_status(request: HttpRequest, pk: int) -> HttpResponse:
    goal = get_object_or_404(LearningGoal, pk=pk, user=request.user)
    action = request.POST.get("action")
    transitions = {
        "pause": LearningGoal.Status.PAUSED,
        "resume": LearningGoal.Status.ACTIVE,
        "archive": LearningGoal.Status.ARCHIVED,
        "complete": LearningGoal.Status.COMPLETED,
    }
    if action == "primary":
        try:
            goal_service.make_primary(goal)
            messages.success(request, f"“{goal.title}” is now your current focus.")
        except ValueError as exc:
            messages.warning(request, str(exc))
    elif action == "upgrade_path":
        if goal_service.upgrade_path_version(goal):
            messages.success(request, "Your goal now follows the latest version of the path.")
        else:
            messages.info(request, "Your goal already follows the latest path version.")
    elif action in transitions:
        goal_service.set_goal_status(goal, transitions[action])
        labels = {"pause": "paused", "resume": "resumed", "archive": "archived", "complete": "marked complete"}
        messages.success(request, f"Goal {labels[action]}.")
    else:
        messages.error(request, "Unknown action.")
    return redirect("learning:goal_detail", pk=goal.pk)
