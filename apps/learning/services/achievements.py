"""Achievements earned from real, evaluated learning activity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.core.timeutils import local_date
from apps.engine.mastery import MasteryLevel, get_model
from apps.engine.progress import streaks

from ..models import (
    AttemptEvaluation,
    LearningAttempt,
    LearningEvent,
    ReviewRecord,
    SkillMastery,
    UserAchievement,
)
from .snapshot import mastery_state_from_row


@dataclass(frozen=True)
class AchievementDef:
    code: str
    name: str
    description: str
    icon: str


ACHIEVEMENTS: dict[str, AchievementDef] = {
    a.code: a
    for a in [
        AchievementDef("first_steps", "First steps", "Completed your first evaluated challenge.", "footprints"),
        AchievementDef("streak_3", "Three-day rhythm", "Practised three days in a row.", "flame"),
        AchievementDef("streak_7", "A week of practice", "Practised seven days in a row.", "calendar-check"),
        AchievementDef("ten_challenges", "Ten down", "Completed ten evaluated challenges.", "target"),
        AchievementDef("first_proficient", "Proficient", "Reached proficiency in a skill.", "trending-up"),
        AchievementDef("first_mastered", "Mastered", "Mastered a skill, including a successful delayed recall.", "gem"),
        AchievementDef("it_stuck", "It stuck", "Passed a review spaced six or more days after the last one.", "brain"),
        AchievementDef("persistence", "Persistence", "Passed a challenge you had previously missed.", "rotate-ccw"),
    ]
}


def award(user, code: str, *, now: datetime, context: dict | None = None) -> bool:
    definition = ACHIEVEMENTS[code]
    try:
        with transaction.atomic():
            _, created = UserAchievement.objects.get_or_create(
                user=user, code=code, defaults={"earned_at": now, "context": context or {}}
            )
    except IntegrityError:
        return False
    if not created:
        return False
    LearningEvent.objects.create(
        user=user,
        event_type=LearningEvent.Type.ACHIEVEMENT_EARNED,
        occurred_at=now,
        payload={"code": code},
    )
    from apps.notifications.models import Notification
    from apps.notifications.services import notify

    notify(
        user,
        kind=Notification.Kind.ACHIEVEMENT,
        title=f"Achievement unlocked: {definition.name}",
        body=definition.description,
        url=reverse("learning:progress"),
        data={
            "code": code,
            "name": definition.name,
            "description": definition.description,
            "total": UserAchievement.objects.filter(user=user).count(),
        },
        dedupe_key=f"achievement:{code}",
        email=user.profile.milestone_emails_enabled,
    )
    return True


def check_achievements(attempt: LearningAttempt, evaluation: AttemptEvaluation, *, now: datetime) -> list[str]:
    user = attempt.user
    earned = set(UserAchievement.objects.filter(user=user).values_list("code", flat=True))
    newly: list[str] = []

    def grant(code: str, **context) -> None:
        if code not in earned and award(user, code, now=now, context=context):
            newly.append(code)
            earned.add(code)

    evaluated = LearningAttempt.objects.filter(user=user, status=LearningAttempt.Status.EVALUATED)
    total = evaluated.count()
    if total >= 1:
        grant("first_steps")
    if total >= 10:
        grant("ten_challenges")

    if not {"streak_3", "streak_7"} <= earned:
        days = evaluated.values_list("local_date", flat=True).distinct()
        current, _ = streaks(days, local_date(user, now))
        if current >= 3:
            grant("streak_3", streak=current)
        if current >= 7:
            grant("streak_7", streak=current)

    if not {"first_proficient", "first_mastered"} <= earned:
        model = get_model()
        levels = {
            model.level(model.current(mastery_state_from_row(row), now))
            for row in SkillMastery.objects.filter(user=user, evidence_count__gt=0)
        }
        if levels & {MasteryLevel.PROFICIENT, MasteryLevel.MASTERED}:
            grant("first_proficient")
        if MasteryLevel.MASTERED in levels:
            grant("first_mastered")

    record = ReviewRecord.objects.filter(attempt=attempt).first()
    if record and record.outcome == "success" and (record.previous_interval_days or 0) >= 6:
        grant("it_stuck", skill=attempt.challenge.skill.slug)

    if evaluation.passed:
        missed_before = AttemptEvaluation.objects.filter(
            attempt__user=user, attempt__challenge_id=attempt.challenge_id, passed=False
        ).exclude(attempt=attempt)
        if missed_before.exists():
            grant("persistence", challenge=attempt.challenge.slug)
    return newly
