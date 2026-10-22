from __future__ import annotations

from typing import Any

from .base import ChallengeSpec, Check, EvaluationResult, InvalidResponse, Misconception, dedupe_misconceptions


class MultipleChoiceEvaluator:
    """Exact validation; 'select all that apply' earns partial credit."""

    version = "choice-v1"

    def parse(self, spec: ChallengeSpec, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("selected", [])
        selected = [raw] if isinstance(raw, str) else list(raw or [])
        valid = {str(o["id"]) for o in spec.content.get("options", [])}
        selected = sorted({str(s) for s in selected})
        if not selected:
            raise InvalidResponse("Choose an answer before submitting.")
        if any(s not in valid for s in selected):
            raise InvalidResponse("That option isn't part of this question.")
        if not spec.content.get("multiple") and len(selected) != 1:
            raise InvalidResponse("Choose exactly one answer.")
        return {"selected": selected}

    def evaluate(self, spec: ChallengeSpec, response: dict[str, Any]) -> EvaluationResult:
        options = {str(o["id"]): o for o in spec.content.get("options", [])}
        selected = set(response.get("selected", []))
        correct_ids = {oid for oid, o in options.items() if o.get("correct")}
        feedback: list[str] = []
        misconceptions: list[Misconception | None] = []
        checks: list[Check] = []

        for oid in sorted(selected):
            option = options.get(oid, {})
            if option.get("feedback"):
                feedback.append(str(option["feedback"]))
            if not option.get("correct"):
                misconceptions.append(Misconception.from_dict(option.get("misconception")))

        if spec.content.get("multiple"):
            hits = len(selected & correct_ids)
            wrong = len(selected - correct_ids)
            score = max(0.0, (hits - wrong) / len(correct_ids)) if correct_ids else 0.0
            missed = correct_ids - selected
            for oid in sorted(missed):
                checks.append(Check(label=f"Missed a correct option ({oid.upper()})", passed=False))
            summary = (
                "All correct options selected."
                if score == 1.0
                else f"{hits} of {len(correct_ids)} correct options selected"
                + (f", plus {wrong} incorrect." if wrong else ".")
            )
        else:
            score = 1.0 if selected == correct_ids else 0.0
            summary = "You chose the correct answer." if score == 1.0 else "That isn't the correct answer."

        return EvaluationResult(
            score=score,
            summary=summary,
            evaluator_version=self.version,
            checks=checks,
            misconceptions=dedupe_misconceptions(misconceptions),
            feedback=feedback,
            details={"selected": sorted(selected), "correct": sorted(correct_ids)},
        )
