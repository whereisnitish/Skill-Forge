from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.engine.mastery import BetaEvidenceModel, MasteryLevel, Observation

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
model = BetaEvidenceModel()


def obs(score: float, when=NOW, **kw) -> Observation:
    defaults = {"challenge_difficulty": 2, "skill_difficulty": 2, "kind": "multiple_choice", "occurred_at": when}
    defaults.update(kw)
    return Observation(score=score, **defaults)


def test_prior_reflects_level_and_difficulty_but_is_weak():
    beginner = model.prior("beginner", 2)
    advanced = model.prior("advanced", 2)
    hard = model.prior("advanced", 5)
    assert beginner.mean < advanced.mean
    assert hard.mean < advanced.mean
    assert beginner.alpha + beginner.beta == pytest.approx(model.prior_strength)
    assert model.level(beginner) == MasteryLevel.NOT_STARTED


def test_correct_answer_raises_and_incorrect_lowers_estimate():
    prior = model.prior("intermediate", 2)
    up, _ = model.update(prior, obs(1.0))
    down, _ = model.update(prior, obs(0.0))
    assert up.mean > prior.mean > down.mean
    assert up.evidence_count == 1 and up.success_count == 1
    assert down.success_count == 0


def test_one_easy_correct_answer_is_not_mastery():
    state, _ = model.update(model.prior("advanced", 2), obs(1.0, challenge_difficulty=1))
    assert model.level(state) == MasteryLevel.EXPLORING
    assert model.confidence(state) == "low"


def test_mastered_requires_repeated_evidence_and_delayed_recall():
    state = model.prior("intermediate", 2)
    when = NOW
    for _ in range(7):
        state, _ = model.update(state, obs(1.0, when=when, challenge_difficulty=3))
        when += timedelta(hours=6)
    assert state.mean > 0.85
    assert state.delayed_successes == 0
    assert model.level(state) == MasteryLevel.PROFICIENT  # no delayed recall yet

    state, detail = model.update(state, obs(1.0, when=when + timedelta(days=4), challenge_difficulty=3))
    assert detail.delayed_recall is True
    assert model.level(state) == MasteryLevel.MASTERED


def test_hints_and_revealed_solutions_reduce_credit():
    prior = model.prior("beginner", 2)
    clean, _ = model.update(prior, obs(1.0))
    hinted, d1 = model.update(prior, obs(1.0, hints_used=2, hints_available=2))
    revealed, d2 = model.update(prior, obs(1.0, solution_revealed=True))
    assert clean.mean > hinted.mean > revealed.mean
    assert d1.assistance_factor == pytest.approx(0.5)
    assert d2.assistance_factor == pytest.approx(0.15)


def test_harder_successes_count_more_and_harder_failures_count_less():
    prior = model.prior("intermediate", 3)
    easy_win, _ = model.update(prior, obs(1.0, challenge_difficulty=1, skill_difficulty=3))
    hard_win, _ = model.update(prior, obs(1.0, challenge_difficulty=5, skill_difficulty=3))
    easy_loss, _ = model.update(prior, obs(0.0, challenge_difficulty=1, skill_difficulty=3))
    hard_loss, _ = model.update(prior, obs(0.0, challenge_difficulty=5, skill_difficulty=3))
    assert hard_win.mean > easy_win.mean
    assert hard_loss.mean > easy_loss.mean


def test_partial_scores_split_evidence():
    prior = model.prior("intermediate", 2)
    partial, _ = model.update(prior, obs(0.5))
    full, _ = model.update(prior, obs(1.0))
    zero, _ = model.update(prior, obs(0.0))
    assert zero.mean < partial.mean < full.mean


def test_secondary_evidence_weighs_less_and_does_not_count_as_attempt():
    prior = model.prior("beginner", 2)
    primary, _ = model.update(prior, obs(1.0))
    secondary, _ = model.update(prior, obs(1.0, weight=0.4))
    assert primary.mean > secondary.mean > prior.mean
    assert secondary.evidence_count == 0


def test_evidence_decays_toward_prior_over_time():
    state = model.prior("beginner", 2)
    for _ in range(5):
        state, _ = model.update(state, obs(1.0))
    soon = model.current(state, NOW + timedelta(days=1))
    later = model.current(state, NOW + timedelta(days=180))
    assert soon.mean > later.mean > state.prior_alpha / (state.prior_alpha + state.prior_beta)
    assert later.std > soon.std  # less certain after a long gap


def test_failures_are_not_permanent():
    state = model.prior("intermediate", 2)
    for _ in range(4):
        state, _ = model.update(state, obs(0.0))
    low = state.mean
    when = NOW
    for _ in range(6):
        when += timedelta(days=3)
        state, _ = model.update(state, obs(1.0, when=when))
    assert low < 0.2
    assert state.mean > 0.65
    assert model.level(state) == MasteryLevel.DEVELOPING


def test_total_evidence_is_capped_so_recent_attempts_matter():
    state = model.prior("intermediate", 2)
    for _ in range(60):
        state, _ = model.update(state, obs(1.0))
    assert state.alpha + state.beta <= model.prior_strength + model.max_evidence + 1e-9
    after_failures = state
    for _ in range(5):
        after_failures, _ = model.update(after_failures, obs(0.0))
    assert state.mean - after_failures.mean > 0.1


def test_new_format_gets_a_small_bonus_after_first_attempt():
    state, _ = model.update(model.prior("beginner", 2), obs(1.0, kind="multiple_choice"))
    same, d_same = model.update(state, obs(1.0, kind="multiple_choice"))
    new, d_new = model.update(state, obs(1.0, kind="short_answer"))
    assert d_new.new_format and not d_same.new_format
    assert new.mean > same.mean


def test_scores_are_clamped():
    state, _ = model.update(model.prior("beginner", 2), obs(1.7))
    capped, _ = model.update(model.prior("beginner", 2), obs(1.0))
    assert state.mean == pytest.approx(capped.mean)
    assert replace(state).model_version == "beta-evidence-v1"
