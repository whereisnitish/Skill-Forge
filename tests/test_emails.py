"""Email templates, content and delivery (locmem backend — nothing leaves the machine)."""

import io
import re
from datetime import UTC, datetime, timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from apps.core.emails import render_templated_email
from apps.learning.models import ReviewSchedule
from apps.learning.services import attempts as attempt_service
from apps.notifications.models import Notification
from apps.notifications.samples import EMAILS, sample_email
from apps.notifications.tasks import deliver_notification_email, send_daily_reminders, send_review_reminders
from config.env import normalise_smtp_password
from tests.learning.helpers import correct_answer, version

TRANSACTIONAL = {
    "verify_email",
    "verify_email_change",
    "password_reset",
    "payment_failed",
    "account",
    "contact_received",
}
LONDON_NINE = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)  # 09:00 BST


def test_gmail_app_passwords_are_normalised():
    assert normalise_smtp_password("abcd efgh ijkl mnop") == "abcdefghijklmnop"
    assert normalise_smtp_password(" abcdefghijklmnop ") == "abcdefghijklmnop"
    assert normalise_smtp_password("a real pass phrase") == "a real pass phrase"  # only the app-password shape


@pytest.mark.django_db
@pytest.mark.parametrize("name", EMAILS)
def test_every_email_renders_cleanly(name):
    template, context, headers = sample_email(name)
    subject, text, html = render_templated_email(template, context)
    assert subject and "\n" not in subject and "{" not in subject
    assert "&#x27;" not in subject + text and "&amp;" not in text  # plain text isn't HTML-escaped
    assert "{{" not in text + html and "{%" not in text + html
    assert html.lstrip().startswith("<!doctype html>") and "<title>" in html
    links = re.findall(r'href="([^"]+)"', html)
    assert any(link.startswith("http") for link in links), "every email needs an absolute link"
    assert all(not link.startswith("/") for link in links), "email links must be absolute"
    if name in TRANSACTIONAL:
        assert "unsubscribe" not in html.lower() and "List-Unsubscribe" not in headers
    else:
        assert "/app/notifications/unsubscribe/" in html and "List-Unsubscribe" in headers


@pytest.mark.django_db
def test_daily_reminder_shows_todays_real_challenge(make_learner, django_capture_on_commit_callbacks):
    user = make_learner("remind@example.com", tz="Europe/London", daily_reminder_enabled=True, reminder_hour=9)
    with django_capture_on_commit_callbacks(execute=True):
        assert send_daily_reminders(LONDON_NINE.isoformat()) == 1
    note = Notification.objects.get(user=user, kind="daily_reminder")
    assert note.data["challenge_title"] and note.data["reason"] and note.data["budget"] == 15
    message = mail.outbox[0]
    assert message.subject == f"Today's challenge: {note.data['challenge_title']}"
    html = message.alternatives[0][0]
    assert note.data["reason"] in html and "Start today's challenge" in html
    assert "/app/challenges/" in message.body and "09:00 (Europe/London)" in message.body
    assert message.extra_headers["List-Unsubscribe"].startswith("<http://testserver/app/notifications/unsubscribe/")


@pytest.mark.django_db
def test_review_reminder_lists_the_due_skills(make_learner, django_capture_on_commit_callbacks):
    user = make_learner("rev@example.com", tz="Europe/London", reminder_hour=9)
    attempt_service.submit_attempt(user, version("basics-mcq"), correct_answer("basics-mcq"))
    ReviewSchedule.objects.update(due_at=LONDON_NINE - timedelta(days=2))
    with django_capture_on_commit_callbacks(execute=True):
        send_review_reminders(LONDON_NINE.isoformat())
    message = mail.outbox[-1]
    assert message.subject == "1 skill ready for review: Basics"
    assert "Basics" in message.body and "overdue" in message.body
    assert "Overdue" in message.alternatives[0][0]


@pytest.mark.django_db
def test_achievement_and_milestone_emails_carry_details(make_learner, django_capture_on_commit_callbacks):
    from apps.billing.models import Subscription

    user = make_learner("ach@example.com")
    Subscription.objects.create(user=user, plan="pro", status="active", provider="stripe")
    with django_capture_on_commit_callbacks(execute=True):
        for slug in ("basics-mcq", "basics-short", "basics-concept", "basics-mcq", "basics-short"):
            attempt_service.submit_attempt(user, version(slug), correct_answer(slug))
        for slug in (
            "intermediate-mcq",
            "intermediate-mcq-2",
            "intermediate-debug",
            "intermediate-mcq",
            "intermediate-mcq-2",
        ):
            attempt_service.submit_attempt(user, version(slug), correct_answer(slug))
    subjects = [m.subject for m in mail.outbox]
    assert "Achievement unlocked: First steps" in subjects
    milestone = next(m for m in mail.outbox if m.subject.startswith("Milestone complete"))
    assert milestone.subject == "Milestone complete: First"
    assert "1 of 2 milestones complete" in milestone.body and "Up next: Second" in milestone.body


@pytest.mark.django_db
def test_payment_failed_email_is_transactional(learner, django_capture_on_commit_callbacks):
    from apps.billing.models import Subscription
    from apps.billing.services import process_stripe_event

    Subscription.objects.create(
        user=learner, plan="pro", status="active", provider="stripe", provider_subscription_id="sub_9"
    )
    with django_capture_on_commit_callbacks(execute=True):
        process_stripe_event(
            {
                "id": "evt_pf",
                "type": "invoice.payment_failed",
                "data": {"object": {"id": "in_1", "subscription": "sub_9"}},
            }
        )
    message = mail.outbox[0]
    assert message.subject == "Action needed: update your payment method"
    assert "Pro" in message.body and "http://testserver/billing/" in message.body
    assert "List-Unsubscribe" not in message.extra_headers


@pytest.mark.django_db
def test_contact_form_notifies_support_with_reply_to(client, settings, django_capture_on_commit_callbacks):
    settings.SUPPORT_EMAIL = "support@example.com"
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("marketing:contact"),
            {
                "name": "Ada",
                "email": "ada@example.com",
                "topic": "billing",
                "message": "How do invoices work for my plan?",
            },
        )
    message = mail.outbox[0]
    assert message.to == ["support@example.com"] and message.reply_to == ["ada@example.com"]
    assert message.subject == "[SkillForge contact] Billing — Ada"
    assert "How do invoices work" in message.body


@pytest.mark.django_db
def test_delivery_uses_kind_specific_template(learner, django_capture_on_commit_callbacks):
    from apps.notifications.services import notify

    with django_capture_on_commit_callbacks(execute=False):
        note = notify(
            learner,
            kind="achievement",
            title="x",
            dedupe_key="a:1",
            email=True,
            data={"name": "Ten down", "description": "Completed ten evaluated challenges.", "total": 3},
        )
    deliver_notification_email(note.pk)
    assert mail.outbox[0].subject == "Achievement unlocked: Ten down"


@pytest.mark.django_db
def test_preview_and_test_send_commands(tmp_path):
    call_command("preview_emails", out=tmp_path, stdout=io.StringIO())
    assert {p.stem for p in tmp_path.glob("*.html")} == {*EMAILS, "index"}
    call_command("send_test_email", to="qa@example.com", template=["all"], stdout=io.StringIO())
    assert len(mail.outbox) == len(EMAILS)
    assert all(m.subject.startswith("[Test] ") and m.to == ["qa@example.com"] for m in mail.outbox)
