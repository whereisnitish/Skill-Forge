from __future__ import annotations

import os

import pytest
from django.core.cache import cache

# Playwright's sync API runs an event loop; Django must allow sync DB access from it in tests.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

PASSWORD = "a-strong-test-passphrase-42"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def catalog(db):
    from tests.factories import load_small_catalog

    load_small_catalog()


@pytest.fixture
def make_user(db):
    from django.utils import timezone

    from apps.accounts.models import User

    counter = {"n": 0}

    def factory(email: str | None = None, *, tz: str = "UTC", verified: bool = True, **profile) -> User:
        counter["n"] += 1
        user = User.objects.create_user(
            email=email or f"learner{counter['n']}@example.com",
            password=PASSWORD,
            display_name=f"Learner {counter['n']}",
        )
        if verified:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        p = user.profile
        p.timezone = tz
        for key, value in profile.items():
            setattr(p, key, value)
        p.save()
        return user

    return factory


@pytest.fixture
def make_learner(make_user, catalog):
    """A user who has finished onboarding with a primary goal on the test path."""
    from django.utils import timezone

    from apps.catalog.models import LearningPath
    from apps.learning.services.goals import create_goal
    from apps.onboarding.models import OnboardingState

    def factory(email: str | None = None, *, level: str = "beginner", daily_minutes: int = 15, **kwargs):
        user = make_user(email, experience_level=level, daily_minutes=daily_minutes, **kwargs)
        path = LearningPath.objects.get(slug="test-path")
        goal = create_goal(
            user,
            title="Test goal",
            goal_type="python",
            path=path,
            experience_level=level,
            daily_minutes=daily_minutes,
            primary=True,
        )
        OnboardingState.objects.create(user=user, step="plan", completed_at=timezone.now(), goal=goal, data={})
        return user

    return factory


@pytest.fixture
def learner(make_learner):
    return make_learner("learner@example.com")


@pytest.fixture
def auth_client(client, learner):
    client.force_login(learner)
    return client


@pytest.fixture
def password():
    return PASSWORD
