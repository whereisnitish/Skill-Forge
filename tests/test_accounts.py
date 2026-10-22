import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from apps.learning.models import LearningAttempt
from apps.learning.services import attempts as attempt_service
from tests.learning.helpers import correct_answer, version

pytestmark = pytest.mark.django_db
User = get_user_model()


def extract_link(body: str) -> str:
    return re.search(r"http://testserver(/\S+)", body).group(1)


def register(client, **overrides):
    data = {
        "email": "Ada@Example.com",
        "password": "ample-violet-staircase-7",
        "display_name": "Ada",
        "timezone": "Europe/Paris",
        "accept_terms": "on",
    }
    data.update(overrides)
    with_callbacks = client.post(reverse("accounts:register"), data)
    return with_callbacks


def test_registration_creates_profile_logs_in_and_sends_verification(client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = register(client)
    assert response.url == reverse("onboarding:start")
    user = User.objects.get(email="ada@example.com")
    assert user.profile.timezone == "Europe/Paris"
    assert not user.is_email_verified
    assert len(mail.outbox) == 1 and mail.outbox[0].subject == "Confirm your email for SkillForge"
    # verification link works once
    link = extract_link(mail.outbox[0].body)
    assert client.get(link).status_code == 200
    user.refresh_from_db()
    assert user.is_email_verified
    assert client.get(link).context["status"] == "already"


def test_registration_validation(client):
    register(client)
    client.logout()
    dup = register(client, email="ADA@example.com")
    assert dup.status_code == 200 and "already exists" in dup.content.decode()
    weak = register(client, email="b@example.com", password="12345678")
    assert weak.status_code == 200 and weak.context["form"].errors["password"]
    no_terms = register(client, email="c@example.com", accept_terms="")
    assert "accept_terms" in no_terms.context["form"].errors
    bad_tz = register(client, email="d@example.com", timezone="Mars/Olympus")
    assert bad_tz.status_code == 302
    assert User.objects.get(email="d@example.com").profile.timezone == "UTC"


def test_invalid_verification_token(client, make_user):
    user = make_user(verified=False)
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    response = client.get(reverse("accounts:verify_email", args=[uid, "bad-token"]))
    assert response.status_code == 400
    user.refresh_from_db()
    assert not user.is_email_verified


def test_login_logout(client, learner, password):
    bad = client.post(reverse("accounts:login"), {"username": learner.email, "password": "nope"})
    assert bad.status_code == 200 and "match our records" in bad.content.decode()
    ok = client.post(reverse("accounts:login"), {"username": learner.email.upper(), "password": password})
    assert ok.status_code == 302
    assert client.get("/app/").status_code == 200
    assert client.get(reverse("accounts:logout")).status_code == 405  # logout requires POST
    client.post(reverse("accounts:logout"))
    assert client.get("/app/").status_code == 302


def test_password_reset_flow(client, learner, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("accounts:password_reset"), {"email": learner.email})
    assert response.url == reverse("accounts:password_reset_done")
    assert len(mail.outbox) == 1
    link = extract_link(mail.outbox[0].body)
    form_page = client.get(link, follow=True)
    assert form_page.context["validlink"]
    done = client.post(
        form_page.redirect_chain[-1][0],
        {"new_password1": "brand-new-passphrase-99", "new_password2": "brand-new-passphrase-99"},
    )
    assert done.url == reverse("accounts:password_reset_complete")
    learner.refresh_from_db()
    assert learner.check_password("brand-new-passphrase-99")
    # the link can't be reused
    assert not client.get(link, follow=True).context["validlink"]


def test_password_reset_does_not_reveal_unknown_emails(client, db, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
    assert response.url == reverse("accounts:password_reset_done")
    assert mail.outbox == []


def test_settings_update_and_preferences_take_effect(auth_client, learner):
    response = auth_client.post(
        reverse("accounts_settings:learning"),
        {
            "learning-daily_minutes": "30",
            "learning-difficulty_preference": "stretch",
            "learning-preferred_formats": ["debugging"],
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200 and "Saved" in response.content.decode()
    learner.profile.refresh_from_db()
    assert learner.profile.daily_minutes == 30 and learner.profile.preferred_formats == ["debugging"]
    assert learner.goals.get(is_primary=True).daily_minutes == 30
    appearance = auth_client.post(
        reverse("accounts_settings:appearance"),
        {"appearance-theme": "light", "appearance-text_scale": "large", "appearance-reduce_motion": "on"},
    )
    assert appearance.status_code == 302
    html = auth_client.get("/app/").content.decode()
    assert 'data-theme="light"' in html and 'data-motion="reduce"' in html and 'data-text-scale="large"' in html
    invalid = auth_client.post(
        reverse("accounts_settings:notifications"), {"notifications-reminder_hour": "99"}, HTTP_HX_REQUEST="true"
    )
    assert "Please fix" in invalid.content.decode()


def test_email_change_requires_password_and_resets_verification(
    auth_client, learner, password, django_capture_on_commit_callbacks
):
    wrong = auth_client.post(
        reverse("accounts_settings:email"), {"email-email": "new@example.com", "email-current_password": "x"}
    )
    assert wrong.status_code == 200
    learner.refresh_from_db()
    assert learner.email == "learner@example.com"
    with django_capture_on_commit_callbacks(execute=True):
        auth_client.post(
            reverse("accounts_settings:email"), {"email-email": "new@example.com", "email-current_password": password}
        )
    learner.refresh_from_db()
    assert learner.email == "new@example.com" and not learner.is_email_verified
    assert [m.to for m in mail.outbox] == [["new@example.com"]]
    assert mail.outbox[0].subject == "Confirm your new SkillForge email address"
    assert "Reset your password" in mail.outbox[0].alternatives[0][0]


def test_account_deletion_removes_learning_data(auth_client, learner, password):
    attempt_service.submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    refused = auth_client.post(
        reverse("accounts_settings:delete"), {"current_password": password, "confirmation": "delete"}
    )
    assert refused.status_code == 200 and User.objects.filter(pk=learner.pk).exists()
    done = auth_client.post(
        reverse("accounts_settings:delete"), {"current_password": password, "confirmation": "DELETE"}
    )
    assert done.status_code == 302
    assert not User.objects.filter(pk=learner.pk).exists()
    assert not LearningAttempt.objects.exists()
    assert auth_client.get("/app/").status_code == 302


def test_theme_quick_switch_works_signed_out(client, db):
    response = client.post(reverse("accounts_settings:theme"), {"theme": "light"})
    assert response.status_code == 204 and response.cookies["sf_theme"].value == "light"
    assert 'data-theme="light"' in client.get("/").content.decode()
    assert client.post(reverse("accounts_settings:theme"), {"theme": "neon"}).status_code == 400
