from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import Skill
from apps.learning.models import LearningAttempt

from .models import MentorRequest
from .services import MentorRateLimited, mentor_status, request_mentor


@login_required
def index(request: HttpRequest) -> HttpResponse:
    page = Paginator(
        MentorRequest.objects.filter(user=request.user).select_related("skill", "attempt__challenge_version"), 10
    ).get_page(request.GET.get("page"))
    skills = Skill.objects.active().select_related("category")
    return render(request, "mentor/index.html", {"page": page, "skills": skills, "status": mentor_status()})


@login_required
@require_POST
def ask(request: HttpRequest) -> HttpResponse:
    kind = request.POST.get("kind", "")
    attempt = None
    skill = None
    if request.POST.get("attempt"):
        attempt = get_object_or_404(LearningAttempt, pk=request.POST["attempt"], user=request.user)
    elif request.POST.get("skill"):
        skill = get_object_or_404(Skill, slug=request.POST["skill"], is_active=True)
    question = (request.POST.get("question") or "").strip()[:500]
    if kind not in MentorRequest.Kind.values:
        return render(request, "mentor/_error.html", {"message": "Unknown request type."}, status=400)
    if kind == MentorRequest.Kind.EXPLAIN_FAILURE and attempt is None:
        return render(request, "mentor/_error.html", {"message": "Choose an attempt to explain."}, status=400)
    try:
        mentor_request = request_mentor(request.user, kind=kind, attempt=attempt, skill=skill, question=question)
    except MentorRateLimited:
        return render(
            request,
            "mentor/_error.html",
            {"message": "You're asking the mentor a lot right now — wait a minute and try again."},
            status=429,
        )
    mentor_request.refresh_from_db()
    return render(request, "mentor/_response.html", {"item": mentor_request})


@login_required
@require_GET
def detail(request: HttpRequest, pk: int) -> HttpResponse:
    item = MentorRequest.objects.filter(pk=pk, user=request.user).first()
    if item is None:
        raise Http404
    return render(request, "mentor/_response.html", {"item": item})
