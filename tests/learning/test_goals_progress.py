from datetime import timedelta

import pytest
from django.utils import timezone

from apps.catalog.models import LearningPath, Skill
from apps.learning.forms import GoalForm
from apps.learning.models import LearningEvent, LearningGoal, MilestoneCompletion, Recommendation, UserAchievement
from apps.learning.services import analytics
from apps.learning.services import attempts as attempt_service
from apps.learning.services.goals import create_goal, make_primary, set_goal_status, update_goal
from apps.learning.services.sessions import today_plan
from apps.notifications.models import Notification
from tests.learning.helpers import correct_answer, version

pytestmark = pytest.mark.django_db


def test_goal_form_validates_target_date_and_requires_path_or_focus(learner):
    path = LearningPath.objects.get(slug="test-path")
    base = {"title": "x", "goal_type": "python", "experience_level": "beginner", "daily_minutes": 15}
    past = GoalForm(
        {**base, "path": path.pk, "target_date": (timezone.localdate() - timedelta(days=1)).isoformat()}, user=learner
    )
    assert not past.is_valid() and "target_date" in past.errors
    far = GoalForm(
        {**base, "path": path.pk, "target_date": (timezone.localdate() + timedelta(days=5000)).isoformat()},
        user=learner,
    )
    assert not far.is_valid()
    empty = GoalForm(base, user=learner)
    assert not empty.is_valid() and "__all__" in empty.errors
    ok = GoalForm({**base, "focus_skills": [Skill.objects.get(slug="other").pk]}, user=learner)
    assert ok.is_valid(), ok.errors


def test_premium_path_requires_entitlement(learner):
    premium = LearningPath.objects.get(slug="premium-path")
    form = GoalForm(
        {"title": "p", "goal_type": "python", "experience_level": "beginner", "daily_minutes": 15, "path": premium.pk},
        user=learner,
    )
    assert not form.is_valid() and "path" in form.errors


def test_only_one_primary_goal_and_pausing_promotes_another(learner):
    first = LearningGoal.objects.get(user=learner)
    second = create_goal(
        learner,
        title="Second",
        goal_type="python",
        experience_level="beginner",
        daily_minutes=10,
        focus_skills=[Skill.objects.get(slug="other")],
    )
    assert not second.is_primary
    make_primary(second)
    first.refresh_from_db()
    assert second.is_primary and not first.is_primary
    set_goal_status(second, LearningGoal.Status.PAUSED)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_primary and not second.is_primary
    assert LearningEvent.objects.filter(goal=second, event_type="goal_status_changed").exists()


def test_changing_goal_expires_unstarted_recommendations_but_keeps_history(learner):
    rec = today_plan(learner).current
    attempt = attempt_service.submit_attempt(learner, version("other-mcq"), correct_answer("other-mcq"))
    goal = LearningGoal.objects.get(user=learner)
    update_goal(goal, changes={"daily_minutes": 30}, focus_skills=[Skill.objects.get(slug="other")])
    rec.refresh_from_db()
    assert rec.status == Recommendation.Status.EXPIRED
    attempt.refresh_from_db()
    assert attempt.evaluation.passed  # history untouched
    new = today_plan(learner)
    assert new.minutes_budget == 30
    assert new.current.challenge.skill.slug in {"other", "basics"}
    assert LearningEvent.objects.filter(goal=goal, event_type="goal_updated").exists()


def test_focus_skill_is_prioritised_and_explained(learner):
    goal = LearningGoal.objects.get(user=learner)
    update_goal(goal, changes={}, focus_skills=[Skill.objects.get(slug="other")])
    rec = today_plan(learner).current
    assert rec.challenge.skill.slug == "other"
    assert rec.reason_code == "goal_priority"


def test_milestone_completion_and_achievements(make_learner):
    from apps.billing.models import Subscription

    user = make_learner("ms@example.com")
    Subscription.objects.create(user=user, plan="pro", status="active", provider="stripe")
    # Raise basics and intermediate above target with enough evidence.
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
    assert MilestoneCompletion.objects.filter(user=user, milestone__title="First").exists()
    assert Notification.objects.filter(user=user, kind="milestone").count() == 1
    codes = set(UserAchievement.objects.filter(user=user).values_list("code", flat=True))
    assert {"first_steps", "ten_challenges"} <= codes
    assert "first_mastered" not in codes  # no delayed recall yet — honest labelling


def test_analytics_handle_empty_and_populated_data(learner):
    empty = analytics.totals(learner)
    assert empty.attempts == 0 and empty.pass_rate is None
    assert analytics.weekly_trends(learner)["enough"] is False
    assert analytics.error_categories(learner)["total"] == 0
    assert analytics.retention(learner)["rate"] is None
    for slug in ("basics-mcq", "basics-short", "other-mcq", "other-short", "basics-concept"):
        attempt_service.submit_attempt(learner, version(slug), correct_answer(slug))
    attempt_service.submit_attempt(learner, version("intermediate-mcq"), {"selected": ["b"]})
    totals = analytics.totals(learner)
    assert totals.attempts == 6 and totals.evaluated == 6 and totals.passed == 5
    trends = analytics.weekly_trends(learner)
    assert trends["enough"] and trends["sample"] == 6
    assert analytics.error_categories(learner)["categories"][0]["key"] == "conceptual"
    assert analytics.skill_performance(learner)[0]["attempts"] >= 1
