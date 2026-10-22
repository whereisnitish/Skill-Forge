"""Authorization, CSRF, redirects, headers, rate limits and malformed input."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.learning.models import LearningAttempt, LearningGoal, Recommendation
from apps.learning.services import attempts as attempt_service
from apps.learning.services.sessions import today_plan
from apps.mentor.models import MentorRequest
from apps.notifications.models import Notification
from tests.learning.helpers import correct_answer, version

pytestmark = pytest.mark.django_db


@pytest.fixture
def victim(make_learner):
    user = make_learner("victim@example.com")
    attempt = attempt_service.submit_attempt(user, version("basics-mcq"), correct_answer("basics-mcq"))
    rec = today_plan(user).current
    note = Notification.objects.create(user=user, kind="account", title="Private", dedupe_key="x")
    mentor = MentorRequest.objects.create(
        user=user, kind="explain_concept", status="completed", response={"headline": "secret"}
    )
    return {
        "user": user,
        "attempt": attempt,
        "rec": rec,
        "goal": LearningGoal.objects.get(user=user),
        "note": note,
        "mentor": mentor,
    }


@pytest.fixture
def attacker(client, make_learner):
    client.force_login(make_learner("attacker@example.com"))
    return client


def test_cannot_read_or_modify_another_users_data(attacker, victim):
    goal, attempt, rec, note, mentor = (
        victim["goal"],
        victim["attempt"],
        victim["rec"],
        victim["note"],
        victim["mentor"],
    )
    assert attacker.get(reverse("learning:attempt", args=[attempt.pk])).status_code == 404
    assert attacker.get(reverse("learning:attempt_status", args=[attempt.pk])).status_code == 404
    assert attacker.get(reverse("learning:goal_detail", args=[goal.pk])).status_code == 404
    assert attacker.get(reverse("learning:goal_edit", args=[goal.pk])).status_code == 404
    assert attacker.post(reverse("learning:goal_status", args=[goal.pk]), {"action": "archive"}).status_code == 404
    assert attacker.post(reverse("learning:skip", args=[rec.pk])).status_code == 404
    assert attacker.post(reverse("notifications:read", args=[note.pk])).status_code == 404
    assert attacker.get(reverse("mentor:detail", args=[mentor.pk])).status_code == 404
    assert attacker.post(reverse("mentor:ask"), {"kind": "explain_failure", "attempt": attempt.pk}).status_code == 404

    goal.refresh_from_db()
    rec.refresh_from_db()
    note.refresh_from_db()
    assert goal.status == "active"
    assert rec.status == Recommendation.Status.PENDING
    assert note.read_at is None


def test_lists_only_show_own_records(attacker, victim):
    history = attacker.get(reverse("learning:history"))
    assert victim["attempt"].challenge_version.title not in history.content.decode()
    assert history.context["page"].paginator.count == 0
    assert "secret" not in attacker.get(reverse("mentor:index")).content.decode()
    assert "Private" not in attacker.get(reverse("notifications:index")).content.decode()


def test_recommendation_ids_from_other_users_are_ignored_on_submit(attacker, victim):
    rec = victim["rec"]
    attacker.post(
        reverse("learning:submit", args=[rec.challenge.slug]),
        {"recommendation": rec.pk, **correct_answer(rec.challenge.slug)},
    )
    rec.refresh_from_db()
    assert rec.status == Recommendation.Status.PENDING
    mine = LearningAttempt.objects.get(user__email="attacker@example.com")
    assert mine.recommendation is None or mine.recommendation.user.email == "attacker@example.com"


@pytest.mark.parametrize(
    "url",
    [
        "/app/",
        "/app/goals/",
        "/app/history/",
        "/app/mastery/",
        "/app/progress/",
        "/app/skills/",
        "/app/mentor/",
        "/app/notifications/",
        "/settings/",
        "/billing/",
        "/onboarding/",
    ],
)
def test_app_requires_login(client, db, url):
    response = client.get(url)
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_csrf_is_enforced(learner):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(learner)
    response = csrf_client.post(reverse("learning:practice_more"))
    assert response.status_code == 403
    response = csrf_client.post(reverse("accounts:login"), {"username": "x@example.com", "password": "y"})
    assert response.status_code == 403


def test_login_does_not_redirect_offsite(client, learner, password):
    response = client.post(
        reverse("accounts:login") + "?next=https://evil.example.com/",
        {"username": learner.email, "password": password, "next": "https://evil.example.com/"},
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.url


def test_resend_verification_ignores_offsite_next(client, make_user):
    user = make_user(verified=False)
    client.force_login(user)
    response = client.post(reverse("accounts:resend_verification"), {"next": "//evil.example.com/x"})
    assert "evil.example.com" not in response.url


def test_security_headers(client, db):
    response = client.get("/")
    csp = response["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "X-Request-ID" in response
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in response.content.decode()


def test_login_is_rate_limited(client, learner, settings):
    settings.RATELIMIT_ENABLED = True
    statuses = [
        client.post(reverse("accounts:login"), {"username": learner.email, "password": "wrong"}).status_code
        for _ in range(10)
    ]
    assert statuses[0] == 200
    assert statuses[-1] == 429


def test_registration_is_rate_limited(client, db, settings):
    settings.RATELIMIT_ENABLED = True
    codes = []
    for i in range(7):
        codes.append(
            client.post(reverse("accounts:register"), {"email": f"x{i}@example.com", "password": "short"}).status_code
        )
    assert 429 in codes


def test_malformed_input_is_rejected_safely(auth_client, learner):
    url = reverse("learning:submit", args=["intermediate-debug"])
    assert auth_client.post(url, {"line": "DROP TABLE", "explanation": "x"}).status_code == 422
    assert auth_client.post(reverse("learning:submit", args=["nope-not-real"]), {}).status_code == 404
    assert auth_client.post(reverse("mentor:ask"), {"kind": "hack"}).status_code == 400
    assert auth_client.get("/app/history/?start=not-a-date&skill=../../etc").status_code == 200
    assert not LearningAttempt.objects.filter(user=learner).exists()


def test_rendered_user_content_is_escaped(auth_client, learner):
    attempt = attempt_service.submit_attempt(
        learner, version("basics-concept"), {"text": "<script>alert(1)</script> lazily memory"}
    )
    html = auth_client.get(reverse("learning:attempt", args=[attempt.pk])).content.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_rendering_is_sanitised():
    from apps.core.markdown import render_markdown

    html = render_markdown("[x](javascript:alert(1)) <img src=x onerror=alert(1)> <script>bad()</script>")
    assert "javascript:" not in html and "onerror" not in html and "<script" not in html


def test_htmx_errors_return_message_header(auth_client, learner, settings):
    settings.RATELIMIT_ENABLED = True
    for _ in range(31):
        response = auth_client.post(reverse("learning:hint", args=["basics-mcq"]), HTTP_HX_REQUEST="true")
    assert response.status_code == 429
    assert "too often" in response["X-SF-Message"]
