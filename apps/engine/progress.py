"""Streaks and recurring-mistake summaries computed from attempt history."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise


def streaks(active_days: Iterable[date], today: date) -> tuple[int, int]:
    """Return (current, longest) streaks of consecutive active local days.

    The current streak survives until the end of today: if the learner practised
    yesterday but not yet today, the streak is still alive.
    """
    days = sorted(set(active_days))
    if not days:
        return 0, 0

    longest = run = 1
    for previous, current in pairwise(days):
        run = run + 1 if current - previous == timedelta(days=1) else 1
        longest = max(longest, run)

    day_set = set(days)
    anchor = today if today in day_set else today - timedelta(days=1)
    current_streak = 0
    while anchor in day_set:
        current_streak += 1
        anchor -= timedelta(days=1)
    return current_streak, longest


@dataclass(frozen=True)
class MisconceptionSummary:
    code: str
    label: str
    category: str
    count: int
    last_seen: datetime


def recurring_misconceptions(
    occurrences: Iterable[tuple[str, str, str, datetime]],
    *,
    now: datetime,
    window_days: int = 30,
    min_count: int = 2,
) -> list[MisconceptionSummary]:
    """Group (code, label, category, when) occurrences seen at least `min_count` times."""
    cutoff = now - timedelta(days=window_days)
    counts: Counter[str] = Counter()
    latest: dict[str, tuple[str, str, datetime]] = {}
    for code, label, category, when in occurrences:
        if when < cutoff:
            continue
        counts[code] += 1
        if code not in latest or when > latest[code][2]:
            latest[code] = (label, category, when)
    summaries = [
        MisconceptionSummary(code, latest[code][0], latest[code][1], count, latest[code][2])
        for code, count in counts.items()
        if count >= min_count
    ]
    summaries.sort(key=lambda s: (-s.count, -s.last_seen.timestamp(), s.code))
    return summaries
