from __future__ import annotations

import re
from typing import Any

from .base import ChallengeSpec, EvaluationResult, InvalidResponse, Misconception

MAX_ANSWER_CHARS = 300


def normalise_answer(value: str, ignore_spaces: bool = False) -> str:
    text = value
    previous = None
    while text != previous:  # peel wrapping quotes, backticks and a trailing full stop in any order
        previous = text
        text = text.strip().strip("`'\"“”‘’").rstrip(".")
    text = " ".join(text.split()).casefold()
    if ignore_spaces:
        text = "".join(text.split())
    return text


class ShortAnswerEvaluator:
    version = "short-answer-v1"

    def parse(self, spec: ChallengeSpec, data: dict[str, Any]) -> dict[str, Any]:
        answer = str(data.get("answer", "")).strip()
        if not answer:
            raise InvalidResponse("Type an answer before submitting.")
        if len(answer) > MAX_ANSWER_CHARS:
            raise InvalidResponse(f"Keep short answers under {MAX_ANSWER_CHARS} characters.")
        return {"answer": answer}

    def evaluate(self, spec: ChallengeSpec, response: dict[str, Any]) -> EvaluationResult:
        content = spec.content
        ignore_spaces = bool(content.get("ignore_spaces"))
        answer = normalise_answer(response.get("answer", ""), ignore_spaces)

        def matches(candidates: list[str]) -> bool:
            return any(answer == normalise_answer(c, ignore_spaces) for c in candidates)

        if matches(content.get("accepted", [])) or any(
            re.fullmatch(pattern, answer, re.IGNORECASE) for pattern in content.get("patterns", [])
        ):
            return EvaluationResult(1.0, "Your answer matches an accepted answer.", self.version)

        numeric = content.get("numeric")
        if numeric:
            try:
                value = float(answer.replace(",", ""))
            except ValueError:
                value = None
            if value is not None and abs(value - float(numeric["value"])) <= float(numeric.get("tolerance", 0)):
                return EvaluationResult(1.0, "Your answer is within the accepted range.", self.version)

        for entry in content.get("partial", []):
            if matches(entry.get("answers", [])):
                return EvaluationResult(
                    float(entry["score"]),
                    "Partly right.",
                    self.version,
                    feedback=[entry["feedback"]] if entry.get("feedback") else [],
                )

        for entry in content.get("wrong", []):
            if matches(entry.get("answers", [])):
                misconception = Misconception.from_dict(entry.get("misconception"))
                return EvaluationResult(
                    0.0,
                    "Not quite.",
                    self.version,
                    misconceptions=[misconception] if misconception else [],
                    feedback=[entry["feedback"]],
                )

        return EvaluationResult(
            0.0,
            "That doesn't match an accepted answer.",
            self.version,
            feedback=["Compare your answer with the explanation below."],
        )
