"""Keyword-rubric scoring for free-text explanations and code reviews.

This is deliberately transparent: each criterion lists phrases that indicate a
key idea is present. It checks *coverage of key ideas*, not writing quality or
factual nuance, and the UI says so. AI feedback may comment on an answer but
never changes the rubric score.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .base import (
    MAX_TEXT_CHARS,
    ChallengeSpec,
    Check,
    EvaluationResult,
    InvalidResponse,
    Misconception,
    dedupe_misconceptions,
)

REQUIRED_MISS_CAP = 0.6
SHORT_ANSWER_CAP = 0.5


def normalise_text(text: str) -> str:
    text = text.casefold().replace("-", " ").replace("–", " ").replace("—", " ")
    return " ".join(text.split())


@lru_cache(maxsize=4096)
def entry_pattern(entry: str) -> re.Pattern[str]:
    if entry.startswith("re:"):
        return re.compile(entry[3:], re.IGNORECASE)
    words = normalise_text(entry).split(" ")
    body = r"\s+".join(re.escape(word) for word in words if word)
    return re.compile(r"(?<!\w)" + body, re.IGNORECASE)


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


# Long enough that quoting a short expression still counts, but pasting whole
# sentences of the prompt or lines of the shown code does not.
COPY_MIN_CHARS = 40


def strip_copied(normalised: str, reference: str) -> str:
    """Remove passages copied verbatim from the material shown to the learner."""
    for line in reference.splitlines():
        snippet = normalise_text(line).strip()
        if len(snippet) >= COPY_MIN_CHARS and snippet in normalised:
            normalised = normalised.replace(snippet, " ")
    return " ".join(normalised.split())


def score_rubric(
    content: dict[str, Any], text: str, reference: str = ""
) -> tuple[float, list[Check], list[Misconception], list[str]]:
    normalised = strip_copied(normalise_text(text), reference) if reference else normalise_text(text)
    criteria = content.get("criteria", [])
    total = sum(float(c.get("weight", 1)) for c in criteria) or 1.0
    earned = 0.0
    checks: list[Check] = []
    misconceptions: list[Misconception | None] = []
    feedback: list[str] = []
    required_missed = False

    for criterion in criteria:
        weight = float(criterion.get("weight", 1))
        met = any(entry_pattern(str(e)).search(normalised) for e in criterion.get("any", []))
        checks.append(Check(label=str(criterion["label"]), passed=met))
        if met:
            earned += weight
            continue
        feedback.append(str(criterion.get("missing_feedback", "")))
        misconceptions.append(Misconception.from_dict(criterion.get("misconception")))
        if criterion.get("required"):
            required_missed = True

    score = earned / total
    if required_missed:
        score = min(score, REQUIRED_MISS_CAP)
    min_words = int(content.get("min_words", 0))
    if min_words and word_count(normalised) < min_words:
        score = min(score, SHORT_ANSWER_CAP)
        feedback.append(f"Your answer is quite short — aim for at least {min_words} words.")
    return score, checks, dedupe_misconceptions(misconceptions), [f for f in feedback if f]


def parse_text(content: dict[str, Any], raw: Any, field_label: str = "answer") -> str:
    text = str(raw or "").strip()
    if not text:
        raise InvalidResponse(f"Write your {field_label} before submitting.")
    if len(text) > MAX_TEXT_CHARS:
        raise InvalidResponse(f"Keep your {field_label} under {MAX_TEXT_CHARS} characters.")
    max_words = int(content.get("max_words", 600))
    if word_count(text) > max_words:
        raise InvalidResponse(f"Keep your {field_label} under {max_words} words.")
    return text


class RubricEvaluator:
    version = "rubric-v1"

    def parse(self, spec: ChallengeSpec, data: dict[str, Any]) -> dict[str, Any]:
        return {"text": parse_text(spec.content, data.get("text"))}

    def evaluate(self, spec: ChallengeSpec, response: dict[str, Any]) -> EvaluationResult:
        score, checks, misconceptions, feedback = score_rubric(
            spec.content, response.get("text", ""), spec.reference_text
        )
        met = sum(1 for c in checks if c.passed)
        summary = f"Covered {met} of {len(checks)} key ideas."
        return EvaluationResult(
            score=score,
            summary=summary,
            evaluator_version=self.version,
            checks=checks,
            misconceptions=misconceptions,
            feedback=feedback,
            details={"scoring": "keyword-rubric"},
        )
