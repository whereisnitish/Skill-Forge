from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Challenge
from apps.evaluation.base import EvaluationUnavailable, InvalidResponse
from apps.learning.models import (
    AttemptEvaluation,
    LearningAttempt,
    LearningEvent,
    Recommendation,
    ReviewRecord,
    ReviewSchedule,
    SkillEvidence,
    SkillMastery,
)
from apps.learning.services import attempts as attempt_service
from apps.learning.services.evaluation import evaluate_attempt
from apps.learning.services.learner_model import apply_learning_updates
from apps.learning.services.sessions import skip_recommendation, today_plan
from tests.learning.helpers import correct_answer, version, wrong_answer

pytestmark = pytest.mark.django_db


def test_today_plan_creates_a_persisted_explained_recommendation(learner):
    plan = today_plan(learner)
    rec = plan.current
    assert rec is not None
    assert rec.status == Recommendation.Status.PENDING
    assert rec.reason_code and rec.reason_text
    assert rec.reason_data["components"]
    # prerequisites enforced: nothing from "advanced" for a beginner with no evidence
    assert rec.challenge.skill.slug in {"basics", "other"}
    # reloading the page doesn't create another recommendation
    assert today_plan(learner).current.pk == rec.pk
    assert Recommendation.objects.filter(user=learner).count() == 1


def test_correct_submission_updates_learner_model(learner):
    rec = today_plan(learner).current
    slug = rec.challenge.slug
    attempt = attempt_service.submit_attempt(
        learner, rec.challenge_version, correct_answer(slug), recommendation_id=rec.pk
    )

    assert attempt.status == LearningAttempt.Status.EVALUATED
    evaluation = attempt.evaluation
    assert evaluation.passed and evaluation.score == 1.0
    assert evaluation.evaluator_version == rec.challenge_version.evaluation_version

    mastery = SkillMastery.objects.get(user=learner, skill=rec.challenge.skill)
    evidence = SkillEvidence.objects.get(attempt=attempt, skill=rec.challenge.skill)
    assert evidence.mastery_after > evidence.mastery_before
    assert mastery.evidence_count == 1

    schedule = ReviewSchedule.objects.get(user=learner, skill=rec.challenge.skill)
    assert schedule.due_at > attempt.submitted_at
    assert ReviewRecord.objects.get(attempt=attempt).outcome == "first_success"

    rec.refresh_from_db()
    assert rec.status == Recommendation.Status.COMPLETED
    types = set(LearningEvent.objects.filter(user=learner).values_list("event_type", flat=True))
    assert {
        "attempt_submitted",
        "attempt_evaluated",
        "mastery_updated",
        "review_scheduled",
        "achievement_earned",
    } <= types


def test_incorrect_submission_lowers_estimate_and_records_misconception(learner):
    v = version("basics-mcq")
    attempt = attempt_service.submit_attempt(learner, v, wrong_answer("basics-mcq"))
    evidence = SkillEvidence.objects.get(attempt=attempt)
    assert evidence.mastery_after < evidence.mastery_before
    assert attempt.evaluation.misconceptions[0]["code"] == "basics-confusion"
    assert attempt.evaluation.verdict == "incorrect"


def test_partial_scores_are_recorded(learner):
    attempt = attempt_service.submit_attempt(learner, version("basics-short"), {"answer": "O(log n)"})
    assert attempt.evaluation.verdict == "partial"
    assert attempt.evaluation.score == pytest.approx(0.4)


def test_next_recommendation_reflects_updated_state(learner):
    first = today_plan(learner).current
    attempt_service.submit_attempt(
        learner, first.challenge_version, wrong_answer(first.challenge.slug), recommendation_id=first.pk
    )
    nxt = today_plan(learner).current
    assert nxt is not None and nxt.pk != first.pk
    assert nxt.challenge_id != first.challenge_id
    assert nxt.position == 2


def test_failing_a_skill_repeatedly_produces_struggle_explanation(learner):
    for slug in ("basics-mcq", "basics-short"):
        attempt_service.submit_attempt(learner, version(slug), wrong_answer(slug))
    rec = today_plan(learner).current
    # basics is the only ready skill on the path; the two recently attempted challenges are skipped
    assert rec.challenge.slug == "basics-concept"
    assert rec.reason_code == "recent_struggle"
    assert "2 recent exercises" in rec.reason_text


def test_invalid_responses_create_no_attempt(learner):
    with pytest.raises(InvalidResponse):
        attempt_service.submit_attempt(learner, version("basics-mcq"), {"selected": ["zzz"]})
    assert not LearningAttempt.objects.filter(user=learner).exists()


def test_attempts_are_immutable(learner):
    attempt = attempt_service.submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    attempt.response = {"selected": ["b"]}
    with pytest.raises(ValidationError):
        attempt.save()
    attempt.refresh_from_db()
    assert attempt.response == {"selected": ["a"]}


def test_evaluation_and_learner_updates_are_idempotent(learner):
    attempt = attempt_service.submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    first = SkillMastery.objects.get(user=learner).alpha
    again = evaluate_attempt(attempt.pk)
    assert again.pk == attempt.evaluation.pk
    apply_learning_updates(attempt, attempt.evaluation)  # e.g. a retried task
    assert AttemptEvaluation.objects.filter(attempt=attempt).count() == 1
    assert SkillEvidence.objects.filter(attempt=attempt).count() == 1
    assert ReviewRecord.objects.filter(attempt=attempt).count() == 1
    assert SkillMastery.objects.get(user=learner).alpha == first


def test_hints_and_reveals_are_tracked_server_side(learner):
    v = version("basics-mcq")
    attempt_service.reveal_hint(learner, v)
    attempt_service.reveal_hint(learner, v)
    attempt_service.reveal_hint(learner, v)  # only two hints exist
    attempt_service.reveal_solution(learner, v)
    attempt = attempt_service.submit_attempt(learner, v, correct_answer("basics-mcq"))
    assert attempt.hints_used == 2
    assert attempt.solution_revealed
    clean = attempt_service.submit_attempt(learner, version("other-mcq"), correct_answer("other-mcq"))
    assisted_gain = SkillEvidence.objects.get(attempt=attempt)
    clean_gain = SkillEvidence.objects.get(attempt=clean)
    assert (assisted_gain.mastery_after - assisted_gain.mastery_before) < (
        clean_gain.mastery_after - clean_gain.mastery_before
    )


def test_autosave_draft_is_restored_and_cleared_on_submit(learner):
    v = version("basics-concept")
    attempt_service.autosave(learner, v, {"text": "draft text", "evil": "x" * 10})
    draft = attempt_service.get_draft(learner, v)
    assert draft.response == {"text": "draft text"}
    attempt_service.submit_attempt(learner, v, correct_answer("basics-concept"))
    assert attempt_service.get_draft(learner, v) is None


def test_review_due_is_recommended_with_review_reason(learner):
    attempt_service.submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    ReviewSchedule.objects.filter(user=learner).update(due_at=datetime(2020, 1, 1, tzinfo=UTC))
    # expire today's pending recommendation so a fresh pick is made from the new state
    Recommendation.objects.filter(user=learner, status="pending").update(status="expired")
    rec = today_plan(learner).current
    assert rec.challenge.skill.slug == "basics"
    assert rec.challenge.slug != "basics-mcq"  # the exact challenge seen recently is not repeated
    assert rec.reason_code == "review_due"
    assert rec.is_review


def test_off_goal_reviews_stay_reviewable_but_goal_work_wins_by_formula(learner):
    attempt_service.submit_attempt(learner, version("other-mcq"), correct_answer("other-mcq"))
    ReviewSchedule.objects.filter(user=learner).update(due_at=datetime(2020, 1, 1, tzinfo=UTC))
    Recommendation.objects.filter(user=learner, status="pending").update(status="expired")
    rec = today_plan(learner).current
    # weakness + goal relevance + dependency importance of the foundational path skill outweigh
    # the review urgency of a skill that isn't part of the goal at all.
    assert rec.challenge.skill.slug == "basics"
    assert rec.reason_data["components"]["dependency_importance"] > 0


def test_skipping_recommends_something_else(learner):
    first = today_plan(learner).current
    skip_recommendation(first)
    first.refresh_from_db()
    assert first.status == Recommendation.Status.SKIPPED
    nxt = today_plan(learner).current
    assert nxt.challenge_id != first.challenge_id
    assert LearningEvent.objects.filter(user=learner, event_type="recommendation_skipped").exists()


def test_daily_budget_completion(make_learner):
    user = make_learner(daily_minutes=10)
    for _ in range(6):
        plan = today_plan(user)
        if plan.current is None:
            break
        rec = plan.current
        attempt_service.submit_attempt(
            user, rec.challenge_version, correct_answer(rec.challenge.slug), recommendation_id=rec.pk
        )
    plan = today_plan(user)
    assert plan.minutes_used >= 10
    assert plan.is_complete
    assert plan.session.status == "completed"


def test_prerequisite_unlocks_after_evidence(learner):
    for slug in ("basics-mcq", "basics-short", "basics-concept"):
        attempt_service.submit_attempt(learner, version(slug), correct_answer(slug))
    from apps.learning.services.snapshot import LearnerSnapshot

    snapshot = LearnerSnapshot.load(learner)
    intermediate = Challenge.objects.get(slug="intermediate-mcq").skill_id
    assert snapshot.readiness(intermediate).ready


def test_code_challenges_are_never_passed_without_the_runner(learner, settings):
    settings.CODE_RUNNER_URL = ""
    with pytest.raises(EvaluationUnavailable):
        attempt_service.submit_attempt(
            learner, version("advanced-code"), {"code": "def double(x):\n    return x * 2\n"}
        )
    assert not LearningAttempt.objects.filter(user=learner).exists()


def test_code_challenges_are_evaluated_asynchronously_with_runner(
    learner, settings, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.evaluation.runner import CaseOutcome, RunResult

    settings.CODE_RUNNER_URL = "http://runner.invalid"
    settings.CODE_RUNNER_TOKEN = "token"
    monkeypatch.setattr(
        "apps.evaluation.code.run_tests",
        lambda code, tests, user_id=None: RunResult("completed", [CaseOutcome(t["id"], "passed") for t in tests]),
    )
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        attempt = attempt_service.submit_attempt(
            learner, version("advanced-code"), {"code": "def double(x):\n    return x * 2\n"}
        )
    assert attempt.status == LearningAttempt.Status.QUEUED  # never evaluated inside the request
    for callback in callbacks:
        callback()  # dispatches the Celery task (eager in tests)
    attempt.refresh_from_db()
    assert attempt.status == LearningAttempt.Status.EVALUATED
    assert attempt.evaluation.score == 1.0


def test_free_plan_daily_submission_limit(learner, monkeypatch):
    monkeypatch.setattr("apps.billing.entitlements.daily_submission_limit", lambda user: 1)
    attempt_service.submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    with pytest.raises(attempt_service.SubmissionLimitReached):
        attempt_service.submit_attempt(learner, version("other-mcq"), correct_answer("other-mcq"))


def test_attempt_local_date_uses_learner_timezone(make_learner):
    user = make_learner(tz="America/New_York")
    late_evening_utc = datetime(2026, 10, 22, 2, 30, tzinfo=UTC)  # 22:30 on the 21st in New York
    attempt = attempt_service.submit_attempt(
        user, version("basics-mcq"), correct_answer("basics-mcq"), now=late_evening_utc
    )
    assert attempt.local_date.isoformat() == "2026-10-21"
    plan = today_plan(user, now=late_evening_utc)
    assert plan.session.local_date.isoformat() == "2026-10-21"
    next_morning = today_plan(user, now=late_evening_utc + timedelta(hours=10))
    assert next_morning.session.local_date.isoformat() == "2026-10-22"


def test_dashboard_query_count_is_bounded(auth_client, learner):
    for slug in ("basics-mcq", "basics-short", "other-mcq"):
        attempt_service.submit_attempt(learner, version(slug), correct_answer(slug))
    auth_client.get("/app/")  # warm-up creates today's recommendation
    with CaptureQueriesContext(connection) as ctx:
        response = auth_client.get("/app/")
    assert response.status_code == 200
    assert len(ctx.captured_queries) <= 40, len(ctx.captured_queries)


def test_history_query_count_does_not_grow_with_attempts(auth_client, learner):
    attempt_service.submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    auth_client.get("/app/history/")  # warm-up: session bookkeeping happens on first request
    with CaptureQueriesContext(connection) as small:
        auth_client.get("/app/history/")
    for slug in ("basics-short", "other-mcq", "other-short", "basics-concept"):
        attempt_service.submit_attempt(learner, version(slug), correct_answer(slug))
    with CaptureQueriesContext(connection) as large:
        auth_client.get("/app/history/")
    assert len(large.captured_queries) == len(small.captured_queries)
