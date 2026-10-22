from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.billing.plans import PLANS
from apps.catalog.models import Challenge, LearningPath, Skill, SkillCategory
from apps.core.ratelimit import ratelimit

from .forms import ContactForm

logger = logging.getLogger(__name__)


def _catalogue_stats() -> dict:
    return {
        "skills": Skill.objects.active().count(),
        "challenges": Challenge.objects.published().count(),
        "paths": LearningPath.objects.filter(is_active=True).count(),
    }


def home(request: HttpRequest) -> HttpResponse:
    categories = SkillCategory.objects.annotate(skill_count=Count("skills", filter=Q(skills__is_active=True))).filter(
        skill_count__gt=0
    )
    return render(
        request,
        "marketing/home.html",
        {"stats": _catalogue_stats(), "categories": categories, "plans": list(PLANS.values())},
    )


def features(request: HttpRequest) -> HttpResponse:
    return render(request, "marketing/features.html", {"stats": _catalogue_stats()})


def how_it_works(request: HttpRequest) -> HttpResponse:
    weights = settings.SKILLFORGE_ENGINE["SELECTION_WEIGHTS"]
    return render(request, "marketing/how_it_works.html", {"weights": weights})


def tracks(request: HttpRequest) -> HttpResponse:
    paths = (
        LearningPath.objects.filter(is_active=True, current_version__isnull=False)
        .select_related("current_version")
        .prefetch_related("current_version__milestones__steps__skill")
    )
    categories = SkillCategory.objects.prefetch_related("skills").all()
    return render(request, "marketing/tracks.html", {"paths": paths, "categories": categories})


def pricing(request: HttpRequest) -> HttpResponse:
    return render(request, "marketing/pricing.html", {"plans": list(PLANS.values())})


def about(request: HttpRequest) -> HttpResponse:
    return render(request, "marketing/about.html")


def faq(request: HttpRequest) -> HttpResponse:
    return render(request, "marketing/faq.html")


def privacy(request: HttpRequest) -> HttpResponse:
    return render(request, "marketing/privacy.html")


def terms(request: HttpRequest) -> HttpResponse:
    return render(request, "marketing/terms.html")


@require_http_methods(["GET", "POST"])
@ratelimit("contact", rate="5/h", key="ip")
def contact(request: HttpRequest) -> HttpResponse:
    initial = {}
    if request.user.is_authenticated:
        initial = {"name": request.user.friendly_name, "email": request.user.email}
    if request.GET.get("topic") in dict(ContactForm.base_fields["topic"].choices):
        initial["topic"] = request.GET["topic"]
    form = ContactForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        message = form.save(commit=False)
        if request.user.is_authenticated:
            message.user = request.user
        message.save()
        from .tasks import send_contact_notification

        message_id = message.pk
        transaction.on_commit(lambda: send_contact_notification.delay(message_id))
        messages.success(request, "Thanks — your message has been received. We'll reply by email.")
        return redirect("marketing:contact")
    return render(request, "marketing/contact.html", {"form": form})
