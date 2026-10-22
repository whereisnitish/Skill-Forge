from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.billing.entitlements import has_feature
from apps.learning.decorators import learner_required
from apps.learning.models import LearningAttempt, LearningGoal
from apps.learning.services.planning import load_milestones, path_progress
from apps.learning.services.sessions import primary_goal
from apps.learning.services.snapshot import LearnerSnapshot

from . import skillmap
from .constants import DIFFICULTY_LABELS
from .models import Challenge, LearningPath, Skill, SkillCategory, SkillPrerequisite

STATUS_CHOICES = [
    ("", "Any status"),
    ("ready", "Ready to learn"),
    ("locked", "Needs prerequisites"),
    ("in_progress", "In progress"),
    ("strong", "Proficient or mastered"),
    ("not_started", "Not started"),
]


@learner_required
def skills(request: HttpRequest) -> HttpResponse:
    user = request.user
    goal = primary_goal(user)
    snapshot = LearnerSnapshot.load(user, level=goal.experience_level if goal else None)
    q = (request.GET.get("q") or "").strip()[:80]
    category = request.GET.get("category", "")
    difficulty = request.GET.get("difficulty", "")
    status = request.GET.get("status", "")
    view_mode = request.GET.get("view", "list")

    queryset = (
        Skill.objects.active()
        .select_related("category")
        .annotate(challenge_count=Count("challenges", filter=Q(challenges__is_active=True)))
    )
    if q:
        queryset = queryset.filter(Q(name__icontains=q) | Q(summary__icontains=q) | Q(slug__icontains=q))
    if category:
        queryset = queryset.filter(category__slug=category)
    if difficulty.isdigit():
        queryset = queryset.filter(difficulty=int(difficulty))

    rows = []
    for skill in queryset:
        view = snapshot.view(skill.pk)
        ready = snapshot.readiness(skill.pk).ready
        state = (
            "strong"
            if view.level in ("proficient", "mastered")
            else "in_progress"
            if view.measured
            else "ready"
            if ready
            else "locked"
        )
        if status and not (status == state or (status == "not_started" and not view.measured)):
            continue
        rows.append({"skill": skill, "view": view, "ready": ready, "state": state})

    context = {
        "rows": rows,
        "page": Paginator(rows, 24).get_page(request.GET.get("page")),
        "categories": SkillCategory.objects.all(),
        "difficulties": sorted(DIFFICULTY_LABELS.items()),
        "statuses": STATUS_CHOICES,
        "filters": {"q": q, "category": category, "difficulty": difficulty, "status": status},
        "view_mode": view_mode,
        "result_count": len(rows),
    }
    if view_mode == "map":
        visible = [r["skill"] for r in rows]
        visible_ids = {s.pk for s in visible}
        edges = [
            (e.skill_id, e.prerequisite_id, e.strength == SkillPrerequisite.Strength.REQUIRED)
            for e in SkillPrerequisite.objects.filter(skill_id__in=visible_ids, prerequisite_id__in=visible_ids)
        ]
        context["map"] = skillmap.layout(
            visible,
            edges,
            {s.pk: snapshot.view(s.pk) for s in visible},
            {s.pk: snapshot.readiness(s.pk).ready for s in visible},
        )
    template = (
        "catalog/partials/_skills_results.html"
        if request.htmx and request.htmx.target == "skill-results"
        else "catalog/skills.html"
    )
    return render(request, template, context)


@learner_required
def skill_detail(request: HttpRequest, slug: str) -> HttpResponse:
    user = request.user
    skill = get_object_or_404(Skill.objects.select_related("category"), slug=slug, is_active=True)
    goal = primary_goal(user)
    snapshot = LearnerSnapshot.load(user, level=goal.experience_level if goal else None)
    challenges = list(
        Challenge.objects.published().filter(skill=skill).select_related("current_version").order_by("difficulty")
    )
    best = dict(
        LearningAttempt.objects.filter(user=user, challenge__in=challenges)
        .values("challenge_id")
        .annotate(best=Max("evaluation__score"))
        .values_list("challenge_id", "best")
    )
    prerequisites = [
        {"link": link, "view": snapshot.view(link.prerequisite_id)}
        for link in skill.prerequisite_links.select_related("prerequisite").filter(prerequisite__is_active=True)
    ]
    unlocks = Skill.objects.filter(prerequisite_links__prerequisite=skill, is_active=True).distinct()
    from apps.evaluation.registry import unavailable_kinds

    return render(
        request,
        "catalog/skill_detail.html",
        {
            "skill": skill,
            "view": snapshot.view(skill.pk),
            "readiness": snapshot.readiness(skill.pk),
            "challenges": [
                {"challenge": c, "best": best.get(c.pk), "available": c.kind not in unavailable_kinds()}
                for c in challenges
            ],
            "prerequisites": prerequisites,
            "unlocks": unlocks,
            "related": skill.related_skills.filter(is_active=True),
        },
    )


@learner_required
def paths(request: HttpRequest) -> HttpResponse:
    user = request.user
    enrolled = {}
    for goal in LearningGoal.objects.filter(user=user, path__isnull=False).exclude(status=LearningGoal.Status.ARCHIVED):
        enrolled.setdefault(goal.path_id, goal)
    items = (
        LearningPath.objects.filter(is_active=True, current_version__isnull=False)
        .select_related("current_version")
        .annotate(step_count=Count("current_version__milestones__steps"))
    )
    return render(
        request,
        "catalog/paths.html",
        {"paths": items, "enrolled": enrolled, "premium_ok": has_feature(user, "premium_paths")},
    )


@learner_required
def path_detail(request: HttpRequest, slug: str) -> HttpResponse:
    user = request.user
    path = get_object_or_404(LearningPath.objects.select_related("current_version"), slug=slug, is_active=True)
    goal = (
        LearningGoal.objects.filter(user=user, path=path)
        .exclude(status=LearningGoal.Status.ARCHIVED)
        .select_related("path_version")
        .order_by("-is_primary", "-updated_at")
        .first()
    )
    version = goal.path_version if goal and goal.path_version_id else path.current_version
    snapshot = LearnerSnapshot.load(user, level=goal.experience_level if goal else None)
    progress = path_progress(load_milestones(version.pk), snapshot)
    return render(
        request,
        "catalog/path_detail.html",
        {
            "path": path,
            "goal": goal,
            "version": version,
            "progress": progress,
            "locked": path.is_premium and not has_feature(user, "premium_paths"),
            "newer_version": goal is not None and version.pk != path.current_version_id,
        },
    )
