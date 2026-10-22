"""Skill mastery estimation — model `beta-evidence-v1`.

Each (learner, skill) pair holds a Beta(α, β) belief about the probability the
learner can succeed on a typical challenge for that skill.

* The prior is weak (two pseudo-observations) and centred on a mean derived
  from the self-reported level and the skill's difficulty.
* Every evaluated attempt adds weighted evidence: partial scores split between
  α and β; harder challenges make successes count more and failures less;
  hints and revealed solutions discount success evidence; a successful recall
  after a delay counts extra; a first attempt in a new format counts extra.
* Evidence decays toward the prior with a 45-day half-life, and each new
  observation slightly discounts older ones, so the estimate reflects current
  ability and old failures are not held against the learner forever. Total
  evidence is also capped so recent attempts keep influence.

The model is versioned and stateless; swap it by implementing the same
interface and changing `get_model()`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

MODEL_VERSION = "beta-evidence-v1"
PASS_SCORE = 0.7


class MasteryLevel(StrEnum):
    NOT_STARTED = "not_started"
    EXPLORING = "exploring"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    MASTERED = "mastered"


LEVEL_LABELS = {
    MasteryLevel.NOT_STARTED: "Not started",
    MasteryLevel.EXPLORING: "Exploring",
    MasteryLevel.DEVELOPING: "Developing",
    MasteryLevel.PROFICIENT: "Proficient",
    MasteryLevel.MASTERED: "Mastered",
}


@dataclass(frozen=True)
class MasteryState:
    alpha: float
    beta: float
    prior_alpha: float
    prior_beta: float
    evidence_count: int = 0
    success_count: int = 0
    delayed_successes: int = 0
    formats_seen: frozenset[str] = field(default_factory=frozenset)
    last_practiced_at: datetime | None = None
    model_version: str = MODEL_VERSION

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def std(self) -> float:
        a, b = self.alpha, self.beta
        n = a + b
        return math.sqrt((a * b) / (n * n * (n + 1)))

    @property
    def lower_bound(self) -> float:
        """A conservative estimate (mean minus one standard deviation)."""
        return max(0.0, self.mean - self.std)


@dataclass(frozen=True)
class Observation:
    """One piece of evaluated evidence about a skill."""

    score: float
    challenge_difficulty: int
    skill_difficulty: int
    kind: str
    occurred_at: datetime
    hints_used: int = 0
    hints_available: int = 0
    solution_revealed: bool = False
    weight: float = 1.0  # 1.0 for the primary skill, lower for secondary skills


@dataclass(frozen=True)
class EvidenceDetail:
    """How a single observation moved the estimate (persisted for transparency)."""

    success_increment: float
    failure_increment: float
    decay_factor: float
    delayed_recall: bool
    new_format: bool
    assistance_factor: float


class BetaEvidenceModel:
    version = MODEL_VERSION
    prior_strength = 2.0
    half_life_days = 45.0
    # Each new observation discounts older evidence slightly, so the estimate
    # reflects current ability (effective memory of roughly 12 attempts).
    recency_discount = 0.92
    max_evidence = 25.0
    delayed_recall_days = 2.0

    _LEVEL_MEANS = {"beginner": 0.25, "intermediate": 0.4, "advanced": 0.5}

    def prior(self, level: str, skill_difficulty: int) -> MasteryState:
        base = self._LEVEL_MEANS.get(level, 0.25)
        mean = min(0.6, max(0.05, base - 0.06 * (skill_difficulty - 2)))
        alpha = mean * self.prior_strength
        beta = (1 - mean) * self.prior_strength
        return MasteryState(alpha=alpha, beta=beta, prior_alpha=alpha, prior_beta=beta)

    def decay(self, state: MasteryState, now: datetime) -> tuple[MasteryState, float]:
        """Shrink evidence toward the prior according to time since last practice."""
        if state.last_practiced_at is None:
            return state, 1.0
        days = max(0.0, (now - state.last_practiced_at).total_seconds() / 86400)
        factor = 0.5 ** (days / self.half_life_days)
        alpha = state.prior_alpha + (state.alpha - state.prior_alpha) * factor
        beta = state.prior_beta + (state.beta - state.prior_beta) * factor
        return replace(state, alpha=alpha, beta=beta), factor

    def current(self, state: MasteryState, now: datetime) -> MasteryState:
        return self.decay(state, now)[0]

    def update(self, state: MasteryState, obs: Observation) -> tuple[MasteryState, EvidenceDetail]:
        score = min(1.0, max(0.0, obs.score))
        decayed, factor = self.decay(state, obs.occurred_at)

        relative = obs.challenge_difficulty - obs.skill_difficulty
        success_weight = min(1.5, max(0.5, 1 + 0.2 * relative))
        failure_weight = min(1.5, max(0.5, 1 - 0.2 * relative))

        if obs.solution_revealed:
            assistance = 0.15
        elif obs.hints_available > 0 and obs.hints_used > 0:
            assistance = 1 - 0.5 * min(1.0, obs.hints_used / obs.hints_available)
        else:
            assistance = 1.0

        delayed = False
        if state.last_practiced_at is not None and score >= PASS_SCORE and not obs.solution_revealed:
            gap_days = (obs.occurred_at - state.last_practiced_at).total_seconds() / 86400
            delayed = gap_days >= self.delayed_recall_days
        new_format = obs.kind not in state.formats_seen
        format_bonus = 1.1 if new_format and state.evidence_count > 0 else 1.0

        success_inc = obs.weight * score * success_weight * assistance * format_bonus
        if delayed:
            success_inc *= 1.25
        failure_inc = obs.weight * (1 - score) * failure_weight * format_bonus
        if obs.solution_revealed:
            failure_inc += 0.25 * obs.weight

        alpha = state.prior_alpha + (decayed.alpha - state.prior_alpha) * self.recency_discount + success_inc
        beta = state.prior_beta + (decayed.beta - state.prior_beta) * self.recency_discount + failure_inc
        alpha, beta = self._cap(alpha, beta, state.prior_alpha, state.prior_beta)

        primary = obs.weight >= 1.0
        new_state = replace(
            decayed,
            alpha=alpha,
            beta=beta,
            evidence_count=state.evidence_count + (1 if primary else 0),
            success_count=state.success_count + (1 if primary and score >= PASS_SCORE else 0),
            delayed_successes=state.delayed_successes + (1 if primary and delayed else 0),
            formats_seen=state.formats_seen | {obs.kind},
            last_practiced_at=obs.occurred_at,
            model_version=self.version,
        )
        detail = EvidenceDetail(
            success_increment=round(success_inc, 4),
            failure_increment=round(failure_inc, 4),
            decay_factor=round(factor, 4),
            delayed_recall=delayed,
            new_format=new_format,
            assistance_factor=round(assistance, 3),
        )
        return new_state, detail

    def _cap(self, alpha: float, beta: float, prior_alpha: float, prior_beta: float) -> tuple[float, float]:
        evidence_a = alpha - prior_alpha
        evidence_b = beta - prior_beta
        total = evidence_a + evidence_b
        if total <= self.max_evidence:
            return alpha, beta
        scale = self.max_evidence / total
        return prior_alpha + evidence_a * scale, prior_beta + evidence_b * scale

    def level(self, state: MasteryState | None) -> MasteryLevel:
        if state is None or state.evidence_count == 0:
            return MasteryLevel.NOT_STARTED
        mean = state.mean
        if mean >= 0.85 and state.evidence_count >= 6 and state.delayed_successes >= 1 and state.std <= 0.12:
            return MasteryLevel.MASTERED
        if mean >= 0.7 and state.evidence_count >= 4:
            return MasteryLevel.PROFICIENT
        if mean >= 0.4 and state.evidence_count >= 2:
            return MasteryLevel.DEVELOPING
        return MasteryLevel.EXPLORING

    def confidence(self, state: MasteryState | None) -> str:
        if state is None or state.evidence_count < 3 or state.std > 0.17:
            return "low"
        if state.std > 0.11:
            return "medium"
        return "high"


_MODEL = BetaEvidenceModel()


def get_model() -> BetaEvidenceModel:
    return _MODEL
