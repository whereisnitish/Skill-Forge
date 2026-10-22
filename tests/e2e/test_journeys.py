"""Critical browser journeys (Playwright). Run with: pytest -m e2e tests/e2e"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def answer_current_challenge(page: Page) -> None:
    """Answer whichever challenge type is shown, using the small test catalogue's keys."""
    if page.locator("input[name=selected]").count():
        page.locator("label[for='opt-a']").click()
    elif page.locator("input#answer").count():
        page.fill("input#answer", "O(1)")
    elif page.locator("input[name=line]").count():
        page.locator("label[for='line-3']").click()
        page.fill("textarea#explanation", "The + 1 at the end is wrong; remove it.")
    else:
        page.fill("textarea#text", "Generators produce values lazily, one at a time, which saves a lot of memory.")
    page.get_by_role("button", name=re.compile("Submit answer")).click()


def test_register_onboard_practise_and_review(page: Page, live_server, seeded, console_errors):
    base = live_server.url
    page.goto(base + "/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("Build skills that")
    page.get_by_role("link", name=re.compile("Start learning")).first.click()

    # 1. Register
    page.fill("input[name=display_name]", "Grace")
    page.fill("input[name=email]", "grace@example.com")
    page.fill("input[name=password]", "a-strong-browser-passphrase-1")
    page.check("input[name=accept_terms]")
    page.get_by_role("button", name="Create account").click()

    # 2. Onboarding (with the placement check)
    expect(page).to_have_url(re.compile("/onboarding/goal/"))
    page.locator("label[for='goal-python']").click()
    page.get_by_role("button", name=re.compile("Continue")).click()
    page.locator("label[for='level-intermediate']").click()
    page.get_by_role("button", name=re.compile("Continue")).click()
    expect(page.get_by_role("heading", name="A few quick questions")).to_be_visible()
    for radio in page.locator("input[type=radio][value='a']").all():
        page.locator(f"label[for='{radio.get_attribute('id')}']").click()
    page.get_by_role("button", name=re.compile("Check my answers")).click()
    page.locator("label[for='minutes-15']").click()
    page.get_by_role("button", name=re.compile("Continue")).click()
    page.locator("label[for='format-conceptual']").click()
    page.get_by_role("button", name=re.compile("Build my plan")).click()
    expect(page.get_by_role("heading", name="Your learning plan")).to_be_visible()
    page.get_by_role("button", name=re.compile("Start learning")).click()

    # 3. Today's challenge
    expect(page).to_have_url(re.compile("/app/$"))
    expect(page.get_by_text("Today's challenge")).to_be_visible()
    reason = page.locator("#current-challenge").inner_text()
    assert "Why this challenge" in page.content() or reason
    page.get_by_role("link", name=re.compile("Start challenge")).click()

    # 4. Submit an answer and 5. view feedback
    expect(page).to_have_url(re.compile("/app/challenges/"))
    answer_current_challenge(page)
    expect(page).to_have_url(re.compile("/app/attempts/\\d+/"))
    expect(page.get_by_role("heading", name="Learning update")).to_be_visible()
    expect(page.locator("#verdict")).to_contain_text(re.compile("Correct|Partially correct|Not quite"))
    attempt_url = page.url

    # 6. Updated progress on the dashboard
    page.get_by_role("link", name="Today", exact=True).first.click()
    expect(page.get_by_role("heading", name="Today's plan")).to_be_visible()
    expect(page.get_by_text("Recent progress")).to_be_visible()

    # 7. Revisit the previous attempt from history
    page.goto(base + "/app/history/")
    page.locator("#history-results a[href*='/app/attempts/']").first.click()
    expect(page).to_have_url(attempt_url)
    expect(page.get_by_role("heading", name="Your answer")).to_be_visible()

    assert not [e for e in console_errors if "favicon" not in e], console_errors


def test_mobile_navigation_and_theme(page: Page, live_server, seeded, console_errors, django_user_model):
    from django.utils import timezone

    from apps.catalog.models import LearningPath
    from apps.learning.services.goals import create_goal
    from apps.onboarding.models import OnboardingState

    user = django_user_model.objects.create_user(email="mobile@example.com", password="mobile-pass-phrase-77")
    goal = create_goal(
        user,
        title="Goal",
        goal_type="python",
        path=LearningPath.objects.get(slug="test-path"),
        experience_level="beginner",
        daily_minutes=15,
        primary=True,
    )
    OnboardingState.objects.create(user=user, completed_at=timezone.now(), goal=goal, step="plan")

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(live_server.url + "/accounts/login/")
    page.fill("input[name=username]", "mobile@example.com")
    page.fill("input[name=password]", "mobile-pass-phrase-77")
    page.get_by_role("button", name="Log in").click()
    expect(page).to_have_url(re.compile("/app/$"))

    # No horizontal overflow at phone width
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

    page.get_by_role("button", name="Open menu").click()
    drawer = page.locator("#app-drawer")
    expect(drawer).to_have_attribute("data-open", "true")
    drawer.get_by_role("link", name="Skill explorer").click()
    expect(page).to_have_url(re.compile("/app/skills/"))

    # Theme preference persists across page loads
    page.goto(live_server.url + "/settings/")
    page.locator("label[for='id_appearance-theme_1']").click()  # Dark (new accounts default to light)
    page.get_by_role("button", name="Save appearance").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert not console_errors, console_errors
