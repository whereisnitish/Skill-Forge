from __future__ import annotations

from typing import Any

from .base import ChallengeSpec, Check, EvaluationResult, InvalidResponse
from .rubric import parse_text, score_rubric


class DebuggingEvaluator:
    """Score = line identification (default 40%) + explanation rubric (60%)."""

    version = "debugging-v1"

    def parse(self, spec: ChallengeSpec, data: dict[str, Any]) -> dict[str, Any]:
        code = str(spec.content.get("code", ""))
        line_count = code.rstrip("\n").count("\n") + 1
        try:
            line = int(str(data.get("line", "")).strip())
        except ValueError as exc:
            raise InvalidResponse("Select the line that contains the defect.") from exc
        if not 1 <= line <= line_count:
            raise InvalidResponse(f"Choose a line between 1 and {line_count}.")
        explanation = parse_text(spec.content, data.get("explanation"), "explanation")
        return {"line": line, "explanation": explanation}

    def evaluate(self, spec: ChallengeSpec, response: dict[str, Any]) -> EvaluationResult:
        content = spec.content
        line_weight = float(content.get("line_weight", 0.4))
        bug_lines = {int(n) for n in content.get("bug_lines", [])}
        line_ok = int(response.get("line", 0)) in bug_lines
        rubric_score, checks, misconceptions, feedback = score_rubric(
            content, response.get("explanation", ""), spec.reference_text
        )

        line_check = Check(
            label="Identified the line with the defect",
            passed=line_ok,
            detail="" if line_ok else f"The defect isn't on line {response.get('line')}.",
        )
        score = line_weight * (1.0 if line_ok else 0.0) + (1 - line_weight) * rubric_score
        if not line_ok:
            feedback.insert(0, "Re-read the code around the reported symptom — the defect is elsewhere.")
        summary = (
            "You found the defect and explained the fix."
            if line_ok and rubric_score >= 0.8
            else "You found the right line."
            if line_ok
            else "The defect is on a different line."
        )
        return EvaluationResult(
            score=score,
            summary=summary,
            evaluator_version=self.version,
            checks=[line_check, *checks],
            misconceptions=misconceptions,
            feedback=feedback,
            details={"line": response.get("line"), "bug_lines": sorted(bug_lines)},
        )
