from __future__ import annotations

import ast
from typing import Any

from .base import MAX_CODE_CHARS, ChallengeSpec, Check, EvaluationResult, InvalidResponse, Misconception
from .runner import RunResult, run_tests


def syntax_error(code: str) -> str | None:
    """Parse (never execute) the code and describe the first syntax error, if any."""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"Line {exc.lineno}: {exc.msg}"
    return None


class PythonCodeEvaluator:
    """Runs learner code against curated test cases in the sandboxed runner."""

    version = "python-tests-v1"
    requires_runner = True

    def parse(self, spec: ChallengeSpec, data: dict[str, Any]) -> dict[str, Any]:
        code = str(data.get("code", ""))
        if not code.strip():
            raise InvalidResponse("Write some code before submitting.")
        if len(code) > MAX_CODE_CHARS:
            raise InvalidResponse(f"Keep your solution under {MAX_CODE_CHARS} characters.")
        return {"code": code}

    def evaluate(
        self, spec: ChallengeSpec, response: dict[str, Any], *, user_id: int | None = None
    ) -> EvaluationResult:
        code = response["code"]
        problem = syntax_error(code)
        if problem:
            return EvaluationResult(
                0.0,
                "Your code has a syntax error, so the tests could not run.",
                self.version,
                checks=[Check(label="Code parses", passed=False, detail=problem)],
                misconceptions=[Misconception("python-syntax-error", "Code did not parse", "syntax")],
                feedback=[problem],
                details={"runner_status": "not_run"},
            )
        tests = [{"id": str(t["order"]), "code": t["code"]} for t in spec.tests]
        result = run_tests(code, tests, user_id=user_id)
        return self._score(spec, result)

    def _score(self, spec: ChallengeSpec, result: RunResult) -> EvaluationResult:
        outcomes = {t.id: t for t in result.tests}
        total = sum(float(t.get("weight", 1)) for t in spec.tests) or 1.0
        earned = 0.0
        checks: list[Check] = []
        feedback: list[str] = []
        timed_out = result.status == "timeout"

        for test in spec.tests:
            outcome = outcomes.get(str(test["order"]))
            passed = outcome is not None and outcome.status == "passed"
            hidden = bool(test.get("is_hidden"))
            if passed:
                earned += float(test.get("weight", 1))
                detail = ""
            elif outcome is None or outcome.status == "not_run":
                detail = "Not run"
            elif hidden:
                detail = "Hidden test failed" + (" (time limit)" if outcome.status == "timeout" else "")
            else:
                detail = outcome.message or outcome.status
            checks.append(Check(label=str(test["name"]), passed=passed, detail=detail, hidden=hidden))

        if result.status == "compile_error":
            feedback.append(result.error or "Your code raised an error while loading.")
        if timed_out:
            feedback.append("Your code exceeded the time limit — look for infinite loops or very slow steps.")

        passed_count = sum(1 for c in checks if c.passed)
        summary = f"Passed {passed_count} of {len(checks)} tests."
        misconceptions = []
        if timed_out:
            misconceptions.append(Misconception("python-time-limit", "Solution exceeded the time limit", "performance"))
        return EvaluationResult(
            score=earned / total,
            summary=summary,
            evaluator_version=self.version,
            checks=checks,
            misconceptions=misconceptions,
            feedback=feedback,
            details={"runner_status": result.status, "duration_ms": result.duration_ms},
        )
