import pytest
from django.urls import reverse

from apps.learning.models import LearningAttempt, LearningGoal
from apps.onboarding.models import OnboardingState

pytestmark = pytest.mark.django_db


def test_onboarding_flow_creates_goal_with_diagnostic_evidence(client, make_user, catalog):
    user = make_user("new@example.com")
    client.force_login(user)
    assert client.get("/app/").url == reverse("onboarding:start")
    assert client.get(reverse("onboarding:start")).url == reverse("onboarding:step", args=["goal"])
    assert client.post(reverse("onboarding:step", args=["goal"]), {"goal_type": "python"}).status_code == 302
    client.post(reverse("onboarding:step", args=["experience"]), {"level": "intermediate", "take_diagnostic": "on"})
    page = client.get(reverse("onboarding:step", args=["diagnostic"]))
    challenges = page.context["challenges"]
    assert challenges, "diagnostic questions should come from the default path"
    answers = {f"q{c.pk}": "a" for c in challenges}
    client.post(reverse("onboarding:step", args=["diagnostic"]), {"action": "submit", **answers})
    assert LearningAttempt.objects.filter(user=user, is_diagnostic=True).count() == len(challenges)

    # Leaving and coming back resumes where we were.
    client.post(reverse("onboarding:step", args=["time"]), {"daily_minutes": "20"})
    assert client.get(reverse("onboarding:start")).url == reverse("onboarding:step", args=["preferences"])
    client.post(reverse("onboarding:step", args=["preferences"]), {"formats": ["conceptual"]})
    plan = client.get(reverse("onboarding:step", args=["plan"]))
    assert plan.status_code == 200
    assert "premium-path" not in [p.slug for p in plan.context["paths"]]
    response = client.post(
        reverse("onboarding:step", args=["plan"]),
        {"action": "confirm", "title": "Sharpen Python", "path": "test-path", "focus_skills": ["intermediate"]},
    )
    assert response.url == reverse("learning:today")
    goal = LearningGoal.objects.get(user=user)
    assert goal.is_primary and goal.daily_minutes == 20 and goal.experience_level == "intermediate"
    assert list(goal.focus_skills.values_list("slug", flat=True)) == ["intermediate"]
    assert OnboardingState.objects.get(user=user).is_complete
    assert LearningAttempt.objects.filter(user=user, is_diagnostic=True, goal=goal).count() == len(challenges)
    user.profile.refresh_from_db()
    assert user.profile.preferred_formats == ["conceptual"]
    today = client.get("/app/")
    assert today.status_code == 200
    assert today.context["d"].plan.current is not None


def test_challenge_workspace_submission_and_feedback(auth_client, learner):
    rec = auth_client.get("/app/").context["d"].plan.current
    page = auth_client.get(reverse("learning:challenge", args=[rec.challenge.slug]) + f"?rec={rec.pk}")
    assert page.status_code == 200
    content = page.content.decode()
    assert rec.challenge_version.explanation not in content  # answer not revealed before submission
    hint = auth_client.post(reverse("learning:hint", args=[rec.challenge.slug]), HTTP_HX_REQUEST="true")
    assert "Hint 1" in hint.content.decode()
    from tests.learning.helpers import correct_answer

    response = auth_client.post(
        reverse("learning:submit", args=[rec.challenge.slug]),
        {"recommendation": rec.pk, **correct_answer(rec.challenge.slug)},
    )
    attempt = LearningAttempt.objects.get(user=learner)
    assert response.url == reverse("learning:attempt", args=[attempt.pk])
    feedback = auth_client.get(response.url)
    assert feedback.status_code == 200
    assert "Correct" in feedback.content.decode()
    assert attempt.hints_used == 1


def test_invalid_submission_returns_422_and_keeps_draft(auth_client, learner):
    url = reverse("learning:submit", args=["basics-concept"])
    response = auth_client.post(url, {"text": ""})
    assert response.status_code == 422
    assert "Write your answer" in response.content.decode()
    assert not LearningAttempt.objects.filter(user=learner).exists()


def test_public_pages_and_seo(client, catalog):
    for name in [
        "home",
        "features",
        "how_it_works",
        "tracks",
        "pricing",
        "about",
        "faq",
        "contact",
        "privacy",
        "terms",
    ]:
        response = client.get(reverse(f"marketing:{name}"))
        assert response.status_code == 200, name
        html = response.content.decode()
        assert '<link rel="canonical"' in html and 'property="og:title"' in html
    assert "Draft" in client.get(reverse("marketing:privacy")).content.decode()
    assert client.get("/sitemap.xml").status_code == 200
    assert "Disallow: /app/" in client.get("/robots.txt").content.decode()


def test_contact_form_stores_message_and_validates(client, db):
    from apps.marketing.models import ContactMessage

    bad = client.post(reverse("marketing:contact"), {"name": "A", "email": "nope", "topic": "support", "message": "hi"})
    assert bad.status_code == 200 and not ContactMessage.objects.exists()
    ok = client.post(
        reverse("marketing:contact"),
        {"name": "Ada", "email": "ada@example.com", "topic": "teams", "message": "Tell me about Teams please."},
    )
    assert ok.status_code == 302 and ContactMessage.objects.get().topic == "teams"


def test_app_pages_render_for_a_learner(auth_client, learner):
    for url in [
        "/app/",
        "/app/reviews/",
        "/app/goals/",
        "/app/goals/new/",
        "/app/paths/",
        "/app/paths/test-path/",
        "/app/skills/",
        "/app/skills/?view=map",
        "/app/skills/basics/",
        "/app/mastery/",
        "/app/mastery/basics/",
        "/app/progress/",
        "/app/history/",
        "/app/mentor/",
        "/app/notifications/",
        "/settings/",
        "/billing/",
    ]:
        assert auth_client.get(url).status_code == 200, url


def test_health_checks(client, db):
    assert client.get("/healthz/").json() == {"status": "ok"}
    ready = client.get("/readyz/").json()
    assert ready["status"] == "ok" and ready["checks"]["database"] == "ok"
