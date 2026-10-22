"""Mastery, analytics and learning history."""

from __future__ import annotations

from collections import defaultdict

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.billing.entitlements import has_feature
from apps.catalog.models import Skill
from apps.engine.mastery import MasteryLevel, get_model

from ..decorators import learner_required
from ..forms import HistoryFilterForm
from ..models import AttemptEvaluation, LearningAttempt, ReviewRecord, ReviewSchedule, SkillEvidence
from ..services import analytics
from ..services.planning import goal_context
from ..services.sessions import primary_goal
from ..services.snapshot import LearnerSnapshot


@learner_required
def mastery(request: HttpRequest) -> HttpResponse:
    user = request.user
    goal = primary_goal(user)
    snapshot = LearnerSnapshot.load(user, level=goal.experience_level if goal else None)
    in_goal = goal_context(goal, snapshot).universe if goal else set()
    reviews = {r.skill_id: r for r in ReviewSchedule.objects.filter(user=user)}
    skills = Skill.objects.active().select_related("category").order_by("category__order", "order")
    filter_by = request.GET.get("show", "goal" if in_goal else "practised")

    groups: dict[str, list] = defaultdict(list)
    counts = {"attention": 0, "strengths": 0, "practised": 0}
    for skill in skills:
        view = snapshot.view(skill.pk)
        review = reviews.get(skill.pk)
        attention = view.measured and (view.mean < 0.5 or (review is not None and review.due_at <= snapshot.now))
        strength = view.level in (MasteryLevel.PROFICIENT, MasteryLevel.MASTERED)
        counts["attention"] += attention
        counts["strengths"] += strength
        counts["practised"] += view.measured
        include = {
            "goal": skill.pk in in_goal,
            "practised": view.measured,
            "attention": attention,
            "strengths": strength,
            "all": True,
        }.get(filter_by, True)
        if include:
            groups[skill.category.name].append(
                {
                    "skill": skill,
                    "view": view,
                    "review": review,
                    "attention": attention,
                    "ready": snapshot.readiness(skill.pk).ready,
                }
            )
    return render(
        request,
        "learning/mastery.html",
        {"groups": dict(groups), "filter_by": filter_by, "counts": counts, "goal": goal, "now": snapshot.now},
    )


@learner_required
def mastery_detail(request: HttpRequest, slug: str) -> HttpResponse:
    user = request.user
    skill = get_object_or_404(Skill.objects.select_related("category"), slug=slug)
    goal = primary_goal(user)
    snapshot = LearnerSnapshot.load(user, level=goal.experience_level if goal else None)
    view = snapshot.view(skill.pk)
    evidence = list(
        SkillEvidence.objects.filter(user=user, skill=skill)
        .select_related("attempt__challenge_version", "attempt__challenge", "attempt__evaluation")
        .order_by("created_at")
    )
    chart = {
        "type": "line",
        "labels": [e.created_at.strftime("%d %b") for e in evidence],
        "percent": True,
        "suggestedMax": 100,
        "datasets": [
            {
                "label": "Estimated mastery",
                "data": [round(e.mastery_after * 100) for e in evidence],
                "color": "accent",
                "fill": True,
            },
            {"label": "Attempt score", "data": [round(e.score * 100) for e in evidence], "color": "info"},
        ],
    }
    errors = []
    for evaluation in (
        AttemptEvaluation.objects.filter(attempt__user=user, attempt__challenge__skill=skill)
        .exclude(misconceptions=[])
        .select_related("attempt__challenge_version")
        .order_by("-created_at")[:8]
    ):
        for item in evaluation.misconceptions:
            errors.append(
                {
                    "label": item["label"],
                    "category": item.get("category", ""),
                    "when": evaluation.created_at,
                    "attempt": evaluation.attempt,
                }
            )
    review = ReviewSchedule.objects.filter(user=user, skill=skill).first()
    review_records = ReviewRecord.objects.filter(schedule=review).order_by("-reviewed_at")[:6] if review else []
    prerequisites = [
        {"skill": snapshot.skills.get(edge.prerequisite_id), "edge": edge, "view": snapshot.view(edge.prerequisite_id)}
        for edge in snapshot.edges.get(skill.pk, [])
        if edge.prerequisite_id in snapshot.skills
    ]
    model = get_model()
    return render(
        request,
        "learning/mastery_detail.html",
        {
            "skill": skill,
            "view": view,
            "evidence": list(reversed(evidence))[:20],
            "evidence_count": len(evidence),
            "chart": chart,
            "errors": errors[:8],
            "review": review,
            "review_records": review_records,
            "prerequisites": prerequisites,
            "readiness": snapshot.readiness(skill.pk),
            "model_version": model.version,
            "formats": sorted(snapshot.masteries[skill.pk].formats_seen) if skill.pk in snapshot.masteries else [],
        },
    )


@learner_required
def progress(request: HttpRequest) -> HttpResponse:
    user = request.user
    advanced = has_feature(user, "advanced_analytics")
    performance = analytics.skill_performance(user)
    goal = primary_goal(user)
    goal_progress = None
    if goal and goal.path_version_id:
        goal_progress = goal_context(goal, LearnerSnapshot.load(user, level=goal.experience_level)).progress
    context = {
        "totals": analytics.totals(user),
        "activity": analytics.activity(user),
        "trends": analytics.weekly_trends(user),
        "performance": performance,
        "performance_chart": analytics.skill_chart(performance),
        "completion": analytics.completion(user),
        "advanced": advanced,
        "goal": goal,
        "goal_progress": goal_progress,
    }
    if advanced:
        context["retention"] = analytics.retention(user)
        context["errors"] = analytics.error_categories(user)
    return render(request, "learning/progress.html", context)


@learner_required
def history(request: HttpRequest) -> HttpResponse:
    user = request.user
    form = HistoryFilterForm(request.GET or None, user=user)
    queryset = (
        LearningAttempt.objects.filter(user=user)
        .select_related("challenge__skill", "challenge_version", "evaluation")
        .order_by("-submitted_at")
    )
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            queryset = queryset.filter(
                Q(challenge_version__title__icontains=data["q"]) | Q(challenge__skill__name__icontains=data["q"])
            )
        if data.get("skill"):
            queryset = queryset.filter(challenge__skill=data["skill"])
        if data.get("kind"):
            queryset = queryset.filter(challenge__kind=data["kind"])
        result = data.get("result")
        if result == "pending":
            queryset = queryset.exclude(status=LearningAttempt.Status.EVALUATED)
        elif result:
            queryset = queryset.filter(evaluation__verdict=result)
        if data.get("start"):
            queryset = queryset.filter(local_date__gte=data["start"])
        if data.get("end"):
            queryset = queryset.filter(local_date__lte=data["end"])
        if data.get("reviews"):
            queryset = queryset.filter(is_review=True)
        if data.get("hints"):
            queryset = queryset.filter(hints_used__gt=0)
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    context = {"form": form, "page": page, "filtered": bool(request.GET.dict().keys() - {"page"})}
    if request.htmx and request.htmx.target == "history-results":
        return render(request, "learning/partials/_history_results.html", context)
    return render(request, "learning/history.html", context)
