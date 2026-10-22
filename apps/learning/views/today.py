from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.entitlements import daily_submission_limit
from apps.catalog.models import Skill

from ..decorators import learner_required
from ..models import Recommendation, ReviewSchedule
from ..services.dashboard import build_dashboard, due_reviews, review_challenge_for
from ..services.sessions import practice_more, skip_recommendation, today_plan


@learner_required
def today(request: HttpRequest) -> HttpResponse:
    dashboard = build_dashboard(request.user)
    return render(
        request,
        "learning/today.html",
        {"d": dashboard, "submission_limit": daily_submission_limit(request.user)},
    )


@learner_required
@require_POST
def skip(request: HttpRequest, pk: int) -> HttpResponse:
    recommendation = get_object_or_404(Recommendation, pk=pk, user=request.user)
    skip_recommendation(recommendation)
    if request.htmx:
        plan = today_plan(request.user)
        return render(request, "learning/partials/_current_challenge.html", {"plan": plan})
    messages.info(request, "Skipped. Here's another challenge.")
    return redirect("learning:today")


@learner_required
@require_POST
def more(request: HttpRequest) -> HttpResponse:
    recommendation = practice_more(request.user)
    if recommendation is None:
        messages.info(request, "Nothing else is eligible right now — you're caught up. Try a review or another skill.")
        return redirect("learning:today")
    return redirect(f"{reverse('learning:challenge', args=[recommendation.challenge.slug])}?rec={recommendation.pk}")


@learner_required
def reviews(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    due, upcoming = due_reviews(request.user, now=now, limit=50)
    later = (
        ReviewSchedule.objects.filter(user=request.user, skill__is_active=True)
        .exclude(skill_id__in=[r.skill_id for r in due + upcoming])
        .select_related("skill")
        .order_by("due_at")[:50]
    )
    return render(request, "learning/reviews.html", {"due": due, "upcoming": upcoming, "later": later})


@learner_required
@require_POST
def start_review(request: HttpRequest, slug: str) -> HttpResponse:
    skill = get_object_or_404(Skill, slug=slug, is_active=True)
    if not ReviewSchedule.objects.filter(user=request.user, skill=skill).exists():
        messages.info(request, f"{skill.name} isn't on your review schedule yet.")
        return redirect("learning:reviews")
    challenge = review_challenge_for(request.user, skill.pk)
    if challenge is None:
        messages.warning(request, f"No reviewable challenges are available for {skill.name} right now.")
        return redirect("learning:reviews")
    return redirect(f"{reverse('learning:challenge', args=[challenge.slug])}?review=1")
