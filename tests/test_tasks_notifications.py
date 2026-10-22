"""Background jobs: reminders, delivery, retries, duplicate prevention and maintenance."""

import smtplib
from datetime import UTC, datetime, timedelta

import pytest
from celery.exceptions import Retry
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.learning.models import LearningAttempt, LearningSession, ReviewSchedule
from apps.learning.services import attempts as attempt_service
from apps.learning.tasks import prepare_daily_sessions, retry_pending_evaluations
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.notifications.tasks import (
    deliver_notification_email,
    send_daily_reminders,
    send_review_reminders,
    unsubscribe_token,
)
from tests.learning.helpers import correct_answer, version

pytestmark = pytest.mark.django_db

# 09:00 in London (BST, UTC+1) on 22 Oct 2026 is 08:00 UTC.
LONDON_NINE = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def reminder_user(make_learner):
    return make_learner("remind@example.com", tz="Europe/London", daily_reminder_enabled=True, reminder_hour=9)


def test_daily_reminder_respects_local_hour_preferences_and_dedupes(
    reminder_user, make_learner, django_capture_on_commit_callbacks
):
    make_learner("optout@example.com", tz="Europe/London", daily_reminder_enabled=False, reminder_hour=9)
    with django_capture_on_commit_callbacks(execute=True):
        assert send_daily_reminders(LONDON_NINE.isoformat()) == 1
        assert send_daily_reminders(LONDON_NINE.isoformat()) == 1  # re-run (e.g. retried beat) …
    assert Notification.objects.filter(kind="daily_reminder").count() == 1  # … still one notification
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["remind@example.com"]
    assert "List-Unsubscribe" in mail.outbox[0].extra_headers
    # wrong local hour → nothing
    assert send_daily_reminders((LONDON_NINE + timedelta(hours=1)).isoformat()) == 0


def test_no_daily_reminder_after_practising_today(reminder_user):
    attempt_service.submit_attempt(
        reminder_user, version("basics-mcq"), correct_answer("basics-mcq"), now=LONDON_NINE - timedelta(hours=1)
    )
    assert send_daily_reminders(LONDON_NINE.isoformat()) == 0


def test_unverified_users_get_in_app_notification_but_no_email(make_learner, django_capture_on_commit_callbacks):
    make_learner(
        "unverified@example.com", tz="Europe/London", verified=False, daily_reminder_enabled=True, reminder_hour=9
    )
    with django_capture_on_commit_callbacks(execute=True):
        send_daily_reminders(LONDON_NINE.isoformat())
    note = Notification.objects.get()
    assert note.email_status == "skipped" and mail.outbox == []


def test_review_reminders_only_when_reviews_are_due(reminder_user, django_capture_on_commit_callbacks):
    assert send_review_reminders(LONDON_NINE.isoformat()) == 0
    attempt_service.submit_attempt(reminder_user, version("basics-mcq"), correct_answer("basics-mcq"))
    ReviewSchedule.objects.update(due_at=LONDON_NINE - timedelta(days=1))
    with django_capture_on_commit_callbacks(execute=True):
        assert send_review_reminders(LONDON_NINE.isoformat()) == 1
        send_review_reminders(LONDON_NINE.isoformat())
    assert Notification.objects.filter(kind="review_due").count() == 1


def test_delivery_is_idempotent(learner, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=False):
        note = notify(learner, kind="milestone", title="Done", dedupe_key="m:1", email=True)
    assert note.email_status == "pending"
    deliver_notification_email(note.pk)
    deliver_notification_email(note.pk)  # duplicate delivery from the broker
    assert len(mail.outbox) == 1
    note.refresh_from_db()
    assert note.email_status == "sent" and note.email_attempts == 1


def test_delivery_retries_transient_smtp_errors(learner, monkeypatch, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=False):
        note = notify(learner, kind="milestone", title="Done", dedupe_key="m:2", email=True)

    def fail(*args, **kwargs):
        raise smtplib.SMTPServerDisconnected("down")

    monkeypatch.setattr("apps.notifications.tasks.send_templated_email", fail)
    with pytest.raises(Retry):
        deliver_notification_email.apply(args=[note.pk], throw=True)
    note.refresh_from_db()
    assert note.email_status == "pending" and note.email_attempts == 1 and note.email_error == "SMTPServerDisconnected"


def test_unsubscribe_link_disables_preference(client, reminder_user):
    token = unsubscribe_token(reminder_user.pk, "daily_reminder")
    url = reverse("notifications:unsubscribe", args=[token])
    assert client.get(url).context["status"] == "confirm"
    client.post(url)
    reminder_user.profile.refresh_from_db()
    assert reminder_user.profile.daily_reminder_enabled is False
    assert client.get(reverse("notifications:unsubscribe", args=["tampered"])).status_code == 400


def test_prepare_daily_sessions_is_idempotent(make_learner):
    user = make_learner("early@example.com", tz="Asia/Tokyo")
    four_am_tokyo = datetime(2026, 10, 22, 19, 30, tzinfo=UTC)  # 04:30 on the 23rd in Tokyo
    assert prepare_daily_sessions(four_am_tokyo.isoformat()) == 1
    assert prepare_daily_sessions(four_am_tokyo.isoformat()) == 0
    session = LearningSession.objects.get(user=user)
    assert session.local_date.isoformat() == "2026-10-23"
    assert session.recommendations.count() == 1


def test_retry_pending_evaluations_redispatches_queued_attempts(learner, monkeypatch):
    attempt = LearningAttempt.objects.create(
        user=learner,
        challenge=version("basics-mcq").challenge,
        challenge_version=version("basics-mcq"),
        response={"selected": ["a"]},
        started_at=timezone.now(),
        submitted_at=timezone.now() - timedelta(minutes=10),
        local_date=timezone.localdate(),
        status="queued",
    )
    assert retry_pending_evaluations() == 1
    attempt.refresh_from_db()
    assert attempt.status == "evaluated"


def test_runner_outage_keeps_attempt_queued_and_records_failure(learner, settings, monkeypatch):
    from apps.evaluation.runner import RunnerUnavailable
    from apps.learning.services.evaluation import MAX_EVALUATION_ATTEMPTS, evaluate_attempt

    settings.CODE_RUNNER_URL = "http://runner.invalid"
    settings.CODE_RUNNER_TOKEN = "t"

    def down(*args, **kwargs):
        raise RunnerUnavailable("down")

    monkeypatch.setattr("apps.evaluation.code.run_tests", down)
    v = version("advanced-code")
    attempt = LearningAttempt.objects.create(
        user=learner,
        challenge=v.challenge,
        challenge_version=v,
        response={"code": "def double(x):\n    return x*2\n"},
        started_at=timezone.now(),
        local_date=timezone.localdate(),
    )
    for _ in range(MAX_EVALUATION_ATTEMPTS):
        with pytest.raises(RunnerUnavailable):
            evaluate_attempt(attempt.pk)
    attempt.refresh_from_db()
    assert attempt.status == "failed" and not hasattr(attempt, "evaluation")


def test_task_failures_are_recorded(db):
    from apps.core.models import TaskFailure
    from apps.core.signals import record_task_failure

    record_task_failure(sender=type("T", (), {"name": "demo.task"}), task_id="abc", exception=ValueError("boom"))
    failure = TaskFailure.objects.get()
    assert failure.task_name == "demo.task" and failure.exception_type == "ValueError"


def test_cleanup_task(learner):
    from apps.core.tasks import cleanup_stale_data
    from apps.learning.models import AttemptDraft

    AttemptDraft.objects.create(user=learner, challenge_version=version("basics-mcq"))
    AttemptDraft.objects.update(updated_at=timezone.now() - timedelta(days=40))
    result = cleanup_stale_data()
    assert result["drafts"] == 1
    assert not AttemptDraft.objects.exists()
