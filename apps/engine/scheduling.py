"""Spaced-repetition review scheduling — algorithm `sm2-lite-v1`.

A simplified SM-2 variant operating per (learner, skill):

* Score and assistance are mapped to a recall quality 0–5.
* Quality < 3 is a lapse: the interval resets to one day and ease drops.
* A successful review grows the interval (base → ~3× base → × ease), crediting
  extra time if the review happened late (successful delayed recall).
* Practising well before the due date does not grow the interval, so cramming
  cannot inflate it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

SCHEDULER_VERSION = "sm2-lite-v1"


@dataclass(frozen=True)
class ReviewState:
    interval_days: float
    ease: float
    repetitions: int
    lapses: int
    due_at: datetime
    last_reviewed_at: datetime | None
    last_score: float | None
    algorithm_version: str = SCHEDULER_VERSION


@dataclass(frozen=True)
class ScheduleDecision:
    outcome: str  # first_success | first_failure | success | lapse | early_review
    quality: int
    previous_interval_days: float | None
    previous_due_at: datetime | None
    new_interval_days: float
    new_due_at: datetime


class Sm2LiteScheduler:
    version = SCHEDULER_VERSION
    initial_ease = 2.5
    min_ease = 1.3
    max_ease = 2.8
    max_interval_days = 120.0

    def quality(self, score: float, hints_used: int = 0, solution_revealed: bool = False) -> int:
        q = round(max(0.0, min(1.0, score)) * 5)
        q -= min(2, max(0, hints_used))
        if solution_revealed:
            q = min(q, 1)
        return max(0, min(5, q))

    def _next_ease(self, ease: float, quality: int) -> float:
        delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        return max(self.min_ease, min(self.max_ease, ease + delta))

    def schedule(
        self,
        state: ReviewState | None,
        *,
        score: float,
        now: datetime,
        base_interval_days: float = 2.0,
        hints_used: int = 0,
        solution_revealed: bool = False,
    ) -> tuple[ReviewState, ScheduleDecision]:
        quality = self.quality(score, hints_used, solution_revealed)
        base = max(1.0, float(base_interval_days))

        if state is None:
            if quality >= 3:
                interval, reps, outcome = base, 1, "first_success"
            else:
                interval, reps, outcome = 1.0, 0, "first_failure"
            ease = self._next_ease(self.initial_ease, quality)
            new_state = ReviewState(
                interval_days=interval,
                ease=ease,
                repetitions=reps,
                lapses=0,
                due_at=now + timedelta(days=interval),
                last_reviewed_at=now,
                last_score=score,
            )
            return new_state, ScheduleDecision(outcome, quality, None, None, interval, new_state.due_at)

        elapsed_days = 0.0
        if state.last_reviewed_at is not None:
            elapsed_days = max(0.0, (now - state.last_reviewed_at).total_seconds() / 86400)

        if quality < 3:
            new_state = replace(
                state,
                interval_days=1.0,
                ease=max(self.min_ease, state.ease - 0.2),
                repetitions=0,
                lapses=state.lapses + 1,
                due_at=now + timedelta(days=1),
                last_reviewed_at=now,
                last_score=score,
                algorithm_version=self.version,
            )
            outcome = "lapse"
        elif elapsed_days < 0.5 * state.interval_days:
            # Early practice: record it, but keep the existing schedule.
            new_state = replace(state, last_reviewed_at=now, last_score=score, algorithm_version=self.version)
            outcome = "early_review"
        else:
            reps = state.repetitions + 1
            if reps == 1:
                interval = base
            elif reps == 2:
                interval = max(3.0, base * 3)
            else:
                credited = max(state.interval_days, min(elapsed_days, 2 * state.interval_days))
                interval = credited * state.ease
            interval = min(self.max_interval_days, round(interval, 2))
            new_state = replace(
                state,
                interval_days=interval,
                ease=self._next_ease(state.ease, quality),
                repetitions=reps,
                due_at=now + timedelta(days=interval),
                last_reviewed_at=now,
                last_score=score,
                algorithm_version=self.version,
            )
            outcome = "success"

        decision = ScheduleDecision(
            outcome=outcome,
            quality=quality,
            previous_interval_days=state.interval_days,
            previous_due_at=state.due_at,
            new_interval_days=new_state.interval_days,
            new_due_at=new_state.due_at,
        )
        return new_state, decision


def review_urgency(state: ReviewState | None, now: datetime, day_end: datetime) -> float:
    """0 when nothing is due today; 0.4 when due later today; 0.6–1.0 when overdue."""
    if state is None:
        return 0.0
    if state.due_at <= now:
        overdue_days = (now - state.due_at).total_seconds() / 86400
        return min(1.0, 0.6 + 0.4 * overdue_days / max(state.interval_days, 1.0))
    if state.due_at <= day_end:
        return 0.4
    return 0.0


_SCHEDULER = Sm2LiteScheduler()


def get_scheduler() -> Sm2LiteScheduler:
    return _SCHEDULER
