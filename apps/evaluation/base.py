from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

PASS_THRESHOLD = 0.8
PARTIAL_THRESHOLD = 0.3
MAX_TEXT_CHARS = 6000
MAX_CODE_CHARS = 20000


class InvalidResponse(ValueError):
    """The submitted response is malformed (shown to the learner as a form error)."""


class EvaluationUnavailable(RuntimeError):
    """The evaluator cannot run right now (e.g. the code runner is not configured or down)."""


@dataclass(frozen=True)
class ChallengeSpec:
    kind: str
    content: dict[str, Any]
    tests: list[dict[str, Any]] = field(default_factory=list)
    # Text shown to the learner (prompt, code under review); copied passages earn no rubric credit.
    reference_text: str = ""


@dataclass(frozen=True)
class Misconception:
    code: str
    label: str
    category: str

    @classmethod
    def from_dict(cls, data: dict | None) -> Misconception | None:
        if not data:
            return None
        return cls(str(data["code"]), str(data["label"]), str(data.get("category", "conceptual")))


@dataclass(frozen=True)
class Check:
    label: str
    passed: bool
    detail: str = ""
    hidden: bool = False


@dataclass
class EvaluationResult:
    score: float
    summary: str
    evaluator_version: str
    checks: list[Check] = field(default_factory=list)
    misconceptions: list[Misconception] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = round(max(0.0, min(1.0, float(self.score))), 4)

    @property
    def verdict(self) -> str:
        if self.score >= PASS_THRESHOLD:
            return "correct"
        if self.score >= PARTIAL_THRESHOLD:
            return "partial"
        return "incorrect"

    @property
    def passed(self) -> bool:
        return self.score >= PASS_THRESHOLD

    def to_feedback_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "feedback": list(self.feedback),
            "checks": [asdict(c) for c in self.checks],
            "details": self.details,
        }


class Evaluator(Protocol):
    version: str

    def parse(self, spec: ChallengeSpec, data: dict[str, Any]) -> dict[str, Any]:
        """Validate raw form data into a canonical response dict (raises InvalidResponse)."""

    def evaluate(self, spec: ChallengeSpec, response: dict[str, Any]) -> EvaluationResult:
        """Score a canonical response."""


def dedupe_misconceptions(items: list[Misconception | None]) -> list[Misconception]:
    seen: set[str] = set()
    result: list[Misconception] = []
    for item in items:
        if item and item.code not in seen:
            seen.add(item.code)
            result.append(item)
    return result
