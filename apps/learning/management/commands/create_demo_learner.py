"""Development only: create a clearly-labelled demo learner with simulated practice history.

The history is produced by answering real recommendations through the real
services (backdated), so every number on the dashboard is derived from stored
attempts — nothing is hardcoded. Refuses to run unless DEBUG is on.
"""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Challenge, LearningPath
from apps.core.timeutils import get_zone
from apps.evaluation.base import EvaluationUnavailable, InvalidResponse
from apps.learning.services.attempts import ensure_draft, submit_attempt
from apps.learning.services.goals import create_goal
from apps.learning.services.sessions import today_plan
from apps.learning.services.snapshot import LearnerSnapshot
from apps.onboarding.models import OnboardingState

DEMO_EMAIL = "demo@skillforge.local"
DEMO_PASSWORD = "skillforge-demo-2026"  # noqa: S105 - local development only


def answer_for(challenge: Challenge, correct: bool) -> dict:
    content = challenge.current_version.content
    version = challenge.current_version
    if challenge.kind == "multiple_choice":
        options = content["options"]
        pick = [o["id"] for o in options if o.get("correct") == correct]
        return {"selected": pick[:1] if not content.get("multiple") else pick or [options[0]["id"]]}
    if challenge.kind == "short_answer":
        if correct:
            return {"answer": content["accepted"][0]}
        wrong = content.get("wrong") or []
        return {"answer": wrong[0]["answers"][0] if wrong else "not sure"}
    if challenge.kind in {"concept_explanation", "code_review"}:
        text = (
            version.solution
            if correct and version.solution
            else "I'm not completely sure here, it depends on the situation."
        )
        return {"text": text[:5000]}
    if challenge.kind == "debugging":
        line = content["bug_lines"][0] if correct else 1
        text = version.solution if correct and version.solution else "Something about this line looks wrong to me."
        return {"line": str(line), "explanation": text[:5000]}
    raise EvaluationUnavailable("unsupported in demo")


class Command(BaseCommand):
    help = "DEBUG only: create demo@skillforge.local with two weeks of simulated, genuinely evaluated practice."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("create_demo_learner only runs with DEBUG=True. Never create demo users in production.")
        if not Challenge.objects.published().exists():
            raise CommandError("Load the catalogue first: python manage.py seed_catalog")
        rng = random.Random(options["seed"])  # noqa: S311 - demo data, not security
        User.objects.filter(email=DEMO_EMAIL).delete()
        user = User.objects.create_user(email=DEMO_EMAIL, password=DEMO_PASSWORD, display_name="Demo Learner")
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        profile = user.profile
        profile.timezone = "Europe/London"
        profile.experience_level = "intermediate"
        profile.daily_minutes = 15
        profile.preferred_formats = ["conceptual", "debugging"]
        # The demo address is not a real mailbox: never send it email.
        profile.daily_reminder_enabled = False
        profile.review_reminder_enabled = False
        profile.milestone_emails_enabled = False
        profile.save()
        zone = get_zone(profile.timezone)
        start = timezone.now().astimezone(zone).date() - timedelta(days=options["days"])
        path = LearningPath.objects.get(slug="python-craftsman")
        goal = create_goal(
            user,
            title="Write better Python",
            goal_type="python",
            path=path,
            experience_level="intermediate",
            daily_minutes=15,
            primary=True,
        )
        OnboardingState.objects.create(
            user=user,
            step="plan",
            completed_at=timezone.now(),
            goal=goal,
            data={"goal_type": "python", "level": "intermediate"},
            diagnostic_completed=True,
        )
        attempts = 0
        for offset in range(options["days"]):
            if rng.random() < 0.2:
                continue  # realistic gaps
            day = start + timedelta(days=offset)
            moment = datetime.combine(day, time(hour=rng.randint(7, 21), minute=rng.randint(0, 59)), tzinfo=zone)
            for _ in range(rng.randint(2, 4)):
                plan = today_plan(user, now=moment)
                rec = plan.current
                if rec is None:
                    break
                snapshot = LearnerSnapshot.load(user, now=moment, level="intermediate")
                p_correct = min(0.9, 0.35 + snapshot.mean(rec.challenge.skill_id) * 0.7)
                # Opening the workspace starts a draft; time spent is measured from it.
                draft = ensure_draft(user, rec.challenge_version, rec)
                draft.started_at = moment
                draft.save(update_fields=["started_at"])
                moment += timedelta(minutes=rec.challenge.estimated_minutes + rng.randint(-1, 3))
                try:
                    submit_attempt(
                        user,
                        rec.challenge_version,
                        answer_for(rec.challenge, rng.random() < p_correct),
                        recommendation_id=rec.pk,
                        now=moment,
                        enforce_limits=False,
                    )
                    attempts += 1
                except (InvalidResponse, EvaluationUnavailable):
                    from apps.learning.services.sessions import skip_recommendation

                    skip_recommendation(rec, now=moment)
                moment += timedelta(minutes=rng.randint(4, 12))
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo learner ready: {DEMO_EMAIL} / {DEMO_PASSWORD} "
                f"({attempts} evaluated attempts). Local development only."
            )
        )
