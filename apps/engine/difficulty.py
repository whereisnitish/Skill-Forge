"""Difficulty progression: choose challenges slightly ahead of current ability."""

from __future__ import annotations

from collections.abc import Sequence

PREFERENCE_OFFSET = {"gentle": -0.5, "balanced": 0.0, "stretch": 0.5}


def target_difficulty(mean: float, recent_scores: Sequence[float], preference: str = "balanced") -> float:
    """Map estimated mastery to a 1–5 difficulty, nudged by recent momentum.

    Three strong results in a row step up; two weak results step down so a
    struggling learner gets a confidence-building challenge next.
    """
    target = 1.0 + 4.0 * max(0.0, min(1.0, mean))
    recent = list(recent_scores)[-3:]
    if len(recent) >= 3 and all(score >= 0.8 for score in recent):
        target += 0.5
    elif len(recent) >= 2 and all(score < 0.5 for score in recent[-2:]):
        target -= 0.75
    target += PREFERENCE_OFFSET.get(preference, 0.0)
    return max(1.0, min(5.0, target))


def difficulty_fit(challenge_difficulty: int, target: float) -> float:
    """Multiplicative fit in [0.4, 1.0]; 1.0 when the challenge matches the target."""
    return max(0.4, 1.0 - 0.18 * abs(challenge_difficulty - target))
