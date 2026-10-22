"""Challenge workspace, submission and attempt review."""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.billing.entitlements import daily_submission_limit
from apps.catalog.models import Challenge, ChallengeVersion
from apps.core.ratelimit import ratelimit
from apps.evaluation.base import EvaluationUnavailable, InvalidResponse
from apps.evaluation.code import syntax_error
from apps.evaluation.registry import unavailable_kinds

from ..decorators import learner_required
from ..models import AttemptDraft, LearningAttempt, Recommendation, ReviewRecord, SkillEvidence
from ..services import attempts as attempt_service
from ..services.sessions import today_plan
from ..services.snapshot import LearnerSnapshot


def _challenge_or_404(slug: str) -> Challenge:
    challenge = (
        Challenge.objects.published().select_related("skill__category", "current_version").filter(slug=slug).first()
    )
    if challenge is None:
        raise Http404
    return challenge


def _working_version(user, challenge: Challenge) -> ChallengeVersion:
    """Continue an in-progress draft on its version; otherwise use the current version."""
    draft = (
        AttemptDraft.objects.filter(user=user, challenge_version__challenge=challenge)
        .select_related("challenge_version")
        .order_by("-updated_at")
        .first()
    )
    return draft.challenge_version if draft else challenge.current_version


def _raw_response(request: HttpRequest) -> dict:
    post = request.POST
    return {
        "selected": post.getlist("selected"),
        "answer": post.get("answer", ""),
        "text": post.get("text", ""),
        "line": post.get("line", ""),
        "explanation": post.get("explanation", ""),
        "code": post.get("code", ""),
    }


def _code_lines(code: str) -> list[tuple[int, str]]:
    return list(enumerate((code or "").rstrip("\n").split("\n"), start=1))


def _workspace_context(request: HttpRequest, challenge: Challenge, version: ChallengeVersion, **extra) -> dict:
    user = request.user
    draft = attempt_service.get_draft(user, version)
    rec_id = request.GET.get("rec") or request.POST.get("recommendation")
    recommendation = None
    if rec_id and str(rec_id).isdigit():
        recommendation = Recommendation.objects.filter(
            pk=rec_id, user=user, challenge=challenge, status=Recommendation.Status.PENDING
        ).first()
    if recommendation is None:
        recommendation = Recommendation.objects.filter(
            user=user, challenge=challenge, status=Recommendation.Status.PENDING
        ).first()
    snapshot = LearnerSnapshot.load(user)
    hints = list(version.hints or [])
    revealed = draft.hints_revealed if draft else 0
    previous = LearningAttempt.objects.filter(user=user, challenge=challenge).order_by("-submitted_at").first()
    response = (draft.response if draft else {}) or {}
    context = {
        "challenge": challenge,
        "version": version,
        "content": version.content or {},
        "draft": draft,
        "response": response,
        "selected": set(response.get("selected", []) if isinstance(response.get("selected"), list) else []),
        "recommendation": recommendation,
        "mastery": snapshot.view(challenge.skill_id),
        "readiness": snapshot.readiness(challenge.skill_id),
        "hints": hints[:revealed],
        "hints_total": len(hints),
        "hints_remaining": max(0, len(hints) - revealed),
        "solution_revealed": bool(draft and draft.solution_revealed),
        "can_evaluate": challenge.kind not in unavailable_kinds(),
        "previous_attempt": previous,
        "code_lines": _code_lines(version.content.get("code", "")) if challenge.kind == "debugging" else [],
        "visible_tests": [t for t in version.test_cases.all() if not t.is_hidden],
        "hidden_test_count": sum(1 for t in version.test_cases.all() if t.is_hidden),
        "submission_limit": daily_submission_limit(user),
        "is_review_request": request.GET.get("review") == "1",
    }
    context.update(extra)
    return context


@learner_required
@require_GET
def workspace(request: HttpRequest, slug: str) -> HttpResponse:
    challenge = _challenge_or_404(slug)
    version = _working_version(request.user, challenge)
    context = _workspace_context(request, challenge, version)
    if context["can_evaluate"]:
        attempt_service.ensure_draft(request.user, version, context["recommendation"])
    return render(request, "learning/challenge.html", context)


@learner_required
@require_POST
@ratelimit("submit", rate="30/m", key="user")
def submit(request: HttpRequest, slug: str) -> HttpResponse:
    challenge = _challenge_or_404(slug)
    version = _working_version(request.user, challenge)
    data = _raw_response(request)
    rec_id = request.POST.get("recommendation")
    try:
        attempt = attempt_service.submit_attempt(
            request.user,
            version,
            data,
            recommendation_id=int(rec_id) if rec_id and rec_id.isdigit() else None,
        )
    except InvalidResponse as exc:
        attempt_service.autosave(request.user, version, data)
        context = _workspace_context(request, challenge, version, form_error=str(exc))
        return render(request, "learning/challenge.html", context, status=422)
    except EvaluationUnavailable as exc:
        messages.warning(request, str(exc))
        return redirect("learning:challenge", slug=slug)
    except attempt_service.SubmissionLimitReached as exc:
        attempt_service.autosave(request.user, version, data)
        messages.warning(
            request,
            f"You've used today's {exc.limit} graded submissions on the Free plan. Your answer is saved as a draft.",
        )
        return redirect("billing:index")
    return redirect("learning:attempt", pk=attempt.pk)


@learner_required
@require_POST
@ratelimit("hint", rate="30/m", key="user")
def hint(request: HttpRequest, slug: str) -> HttpResponse:
    challenge = _challenge_or_404(slug)
    version = _working_version(request.user, challenge)
    _, revealed = attempt_service.reveal_hint(request.user, version)
    hints = list(version.hints or [])
    context = {
        "challenge": challenge,
        "hints": hints[:revealed],
        "hints_total": len(hints),
        "hints_remaining": max(0, len(hints) - revealed),
        "just_revealed": True,
    }
    if request.htmx:
        return render(request, "learning/partials/_hints.html", context)
    return redirect("learning:challenge", slug=slug)


@learner_required
@require_POST
def reveal_solution(request: HttpRequest, slug: str) -> HttpResponse:
    challenge = _challenge_or_404(slug)
    version = _working_version(request.user, challenge)
    attempt_service.reveal_solution(request.user, version)
    if request.htmx:
        return render(request, "learning/partials/_solution.html", {"version": version, "challenge": challenge})
    return redirect("learning:challenge", slug=slug)


@learner_required
@require_POST
@ratelimit("autosave", rate="60/m", key="user")
def autosave(request: HttpRequest, slug: str) -> HttpResponse:
    challenge = _challenge_or_404(slug)
    version = _working_version(request.user, challenge)
    attempt_service.autosave(request.user, version, _raw_response(request))
    return HttpResponse(status=204)


@learner_required
@require_POST
@ratelimit("syntax", rate="30/m", key="user")
def check_syntax(request: HttpRequest, slug: str) -> HttpResponse:
    _challenge_or_404(slug)
    code = request.POST.get("code", "")[:20000]
    return render(request, "learning/partials/_syntax.html", {"problem": syntax_error(code), "empty": not code.strip()})


@learner_required
def attempt_detail(request: HttpRequest, pk: int) -> HttpResponse:
    attempt = get_object_or_404(
        LearningAttempt.objects.select_related("challenge__skill", "challenge_version", "recommendation"),
        pk=pk,
        user=request.user,
    )
    return render(request, "learning/attempt.html", _attempt_context(request, attempt))


@learner_required
@require_GET
def attempt_status(request: HttpRequest, pk: int) -> HttpResponse:
    attempt = get_object_or_404(
        LearningAttempt.objects.select_related("challenge__skill", "challenge_version"), pk=pk, user=request.user
    )
    return render(request, "learning/partials/_attempt_result.html", _attempt_context(request, attempt))


def _attempt_context(request: HttpRequest, attempt: LearningAttempt) -> dict:
    version = attempt.challenge_version
    evaluation = getattr(attempt, "evaluation", None) if attempt.status == LearningAttempt.Status.EVALUATED else None
    evidence = list(SkillEvidence.objects.filter(attempt=attempt).select_related("skill").order_by("-weight"))
    review = ReviewRecord.objects.filter(attempt=attempt).first()
    plan = today_plan(request.user) if evaluation else None
    response = attempt.response or {}
    options = version.content.get("options", []) if attempt.challenge.kind == "multiple_choice" else []
    later_attempts = LearningAttempt.objects.filter(
        user=request.user, challenge=attempt.challenge, submitted_at__gt=attempt.submitted_at
    ).count()
    return {
        "attempt": attempt,
        "challenge": attempt.challenge,
        "version": version,
        "content": version.content or {},
        "evaluation": evaluation,
        "feedback": evaluation.feedback if evaluation else {},
        "evidence": evidence,
        "primary_evidence": next((e for e in evidence if e.weight >= 1.0), None),
        "review": review,
        "plan": plan,
        "response": response,
        "selected": set(response.get("selected", [])),
        "options": options,
        "code_lines": _code_lines(version.content.get("code", "")) if attempt.challenge.kind == "debugging" else [],
        "bug_lines": set(version.content.get("bug_lines", [])),
        "later_attempts": later_attempts,
        "retry_url": reverse("learning:challenge", args=[attempt.challenge.slug]),
    }
