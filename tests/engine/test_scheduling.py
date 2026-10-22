from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.engine.scheduling import Sm2LiteScheduler, review_urgency

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
s = Sm2LiteScheduler()


def test_quality_mapping_accounts_for_hints_and_reveals():
    assert s.quality(1.0) == 5
    assert s.quality(1.0, hints_used=1) == 4
    assert s.quality(1.0, hints_used=5) == 3
    assert s.quality(1.0, solution_revealed=True) == 1
    assert s.quality(0.0) == 0


def test_first_success_uses_skill_base_interval():
    state, decision = s.schedule(None, score=1.0, now=NOW, base_interval_days=3)
    assert decision.outcome == "first_success"
    assert state.interval_days == 3
    assert state.due_at == NOW + timedelta(days=3)


def test_first_failure_comes_back_tomorrow():
    state, decision = s.schedule(None, score=0.2, now=NOW, base_interval_days=3)
    assert decision.outcome == "first_failure"
    assert state.interval_days == 1
    assert state.repetitions == 0


def test_successful_reviews_grow_the_interval():
    state, _ = s.schedule(None, score=1.0, now=NOW, base_interval_days=2)
    when = state.due_at
    intervals = [state.interval_days]
    for _ in range(4):
        state, decision = s.schedule(state, score=1.0, now=when, base_interval_days=2)
        assert decision.outcome == "success"
        intervals.append(state.interval_days)
        when = state.due_at
    assert intervals == sorted(intervals)
    assert intervals[-1] > intervals[1] * 2


def test_failed_review_shortens_interval_and_counts_a_lapse():
    state, _ = s.schedule(None, score=1.0, now=NOW, base_interval_days=2)
    state, _ = s.schedule(state, score=1.0, now=state.due_at, base_interval_days=2)
    long_interval = state.interval_days
    failed, decision = s.schedule(state, score=0.1, now=state.due_at, base_interval_days=2)
    assert decision.outcome == "lapse"
    assert failed.interval_days == 1 < long_interval
    assert failed.lapses == 1
    assert failed.ease < state.ease


def test_cramming_early_does_not_extend_schedule():
    state, _ = s.schedule(None, score=1.0, now=NOW, base_interval_days=4)
    early, decision = s.schedule(state, score=1.0, now=NOW + timedelta(hours=6), base_interval_days=4)
    assert decision.outcome == "early_review"
    assert early.due_at == state.due_at
    assert early.interval_days == state.interval_days


def test_late_successful_recall_earns_extra_credit():
    state, _ = s.schedule(None, score=1.0, now=NOW, base_interval_days=2)
    state, _ = s.schedule(state, score=1.0, now=state.due_at, base_interval_days=2)
    on_time, _ = s.schedule(state, score=1.0, now=state.due_at, base_interval_days=2)
    late, _ = s.schedule(state, score=1.0, now=state.due_at + timedelta(days=10), base_interval_days=2)
    assert late.interval_days > on_time.interval_days


def test_interval_is_capped():
    state, _ = s.schedule(None, score=1.0, now=NOW, base_interval_days=30)
    for _ in range(12):
        state, _ = s.schedule(state, score=1.0, now=state.due_at, base_interval_days=30)
    assert state.interval_days <= s.max_interval_days


@pytest.mark.parametrize(
    ("due_offset", "expected_min", "expected_max"),
    [
        (timedelta(days=-3), 0.6, 1.0),
        (timedelta(hours=-1), 0.6, 0.7),
        (timedelta(hours=3), 0.4, 0.4),
        (timedelta(days=3), 0, 0),
    ],
)
def test_review_urgency(due_offset, expected_min, expected_max):
    state, _ = s.schedule(None, score=1.0, now=NOW - timedelta(days=5), base_interval_days=2)
    state = replace(state, due_at=NOW + due_offset)
    urgency = review_urgency(state, NOW, NOW + timedelta(hours=8))
    assert expected_min <= urgency <= expected_max


def test_no_state_means_no_urgency():
    assert review_urgency(None, NOW, NOW) == 0.0
