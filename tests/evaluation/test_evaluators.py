import pytest

from apps.evaluation.base import ChallengeSpec, InvalidResponse
from apps.evaluation.choice import MultipleChoiceEvaluator
from apps.evaluation.code import PythonCodeEvaluator
from apps.evaluation.debugging import DebuggingEvaluator
from apps.evaluation.rubric import RubricEvaluator
from apps.evaluation.runner import CaseOutcome, RunnerUnavailable, RunResult
from apps.evaluation.short_answer import ShortAnswerEvaluator, normalise_answer
from tests.factories import concept, debugging, mcq, short


def spec(challenge: dict, reference: str = "") -> ChallengeSpec:
    tests = [
        {"order": i, **t, "is_hidden": t.get("hidden", False)} for i, t in enumerate(challenge.get("tests", []), 1)
    ]
    return ChallengeSpec(kind=challenge["kind"], content=challenge["content"], tests=tests, reference_text=reference)


class TestMultipleChoice:
    ev = MultipleChoiceEvaluator()

    def test_correct_and_incorrect(self):
        s = spec(mcq("m", "basics"))
        right = self.ev.evaluate(s, self.ev.parse(s, {"selected": ["a"]}))
        wrong = self.ev.evaluate(s, self.ev.parse(s, {"selected": "b"}))
        assert right.score == 1.0 and right.verdict == "correct"
        assert wrong.score == 0.0 and wrong.verdict == "incorrect"
        assert wrong.misconceptions[0].code == "basics-confusion"
        assert wrong.feedback == ["No."]

    def test_rejects_unknown_or_missing_options(self):
        s = spec(mcq("m", "basics"))
        for data in ({"selected": []}, {"selected": ["z"]}, {"selected": ["a", "b"]}):
            with pytest.raises(InvalidResponse):
                self.ev.parse(s, data)

    def test_select_all_that_apply_gives_partial_credit(self):
        content = {
            "multiple": True,
            "options": [
                {"id": "a", "text": "A", "correct": True, "feedback": "."},
                {"id": "b", "text": "B", "correct": True, "feedback": "."},
                {"id": "c", "text": "C", "feedback": "."},
            ],
        }
        s = ChallengeSpec("multiple_choice", content)
        assert self.ev.evaluate(s, {"selected": ["a", "b"]}).score == 1.0
        assert self.ev.evaluate(s, {"selected": ["a"]}).score == 0.5
        assert self.ev.evaluate(s, {"selected": ["a", "c"]}).score == 0.0


class TestShortAnswer:
    ev = ShortAnswerEvaluator()

    def test_normalisation(self):
        assert normalise_answer("  `O( 1 )`. ", ignore_spaces=True) == "o(1)"
        assert normalise_answer("Constant  Time") == "constant time"

    def test_accepted_partial_wrong_and_unknown(self):
        s = spec(short("s", "basics"))
        assert self.ev.evaluate(s, {"answer": "o(1)"}).score == 1.0
        assert self.ev.evaluate(s, {"answer": "Constant"}).score == 1.0
        partial = self.ev.evaluate(s, {"answer": "O(log n)"})
        assert partial.score == 0.4 and partial.verdict == "partial"
        wrong = self.ev.evaluate(s, {"answer": "O(n)"})
        assert wrong.score == 0 and wrong.misconceptions[0].code == "dict-is-linear"
        assert self.ev.evaluate(s, {"answer": "banana"}).score == 0

    def test_validation(self):
        s = spec(short("s", "basics"))
        with pytest.raises(InvalidResponse):
            self.ev.parse(s, {"answer": "   "})
        with pytest.raises(InvalidResponse):
            self.ev.parse(s, {"answer": "x" * 400})

    def test_patterns_and_numeric(self):
        s = ChallengeSpec(
            "short_answer", {"accepted": ["7000"], "patterns": [r"~?7k"], "numeric": {"value": 6944, "tolerance": 100}}
        )
        assert self.ev.evaluate(s, {"answer": "~7k"}).score == 1.0
        assert self.ev.evaluate(s, {"answer": "6,950"}).score == 1.0
        assert self.ev.evaluate(s, {"answer": "9000"}).score == 0


class TestRubric:
    ev = RubricEvaluator()

    def test_prefix_matching_and_weights(self):
        s = spec(concept("c", "basics"))
        full = self.ev.evaluate(
            s, {"text": "Generators compute values lazily, one at a time, so they save memory overall."}
        )
        assert full.score == 1.0
        partial = self.ev.evaluate(
            s, {"text": "Values are produced on demand so it is efficient enough for big inputs."}
        )
        assert partial.score == pytest.approx(2 / 3, abs=0.01)
        assert [c.passed for c in partial.checks] == [True, False]

    def test_missing_required_criterion_caps_score(self):
        s = spec(concept("c", "basics"))
        result = self.ev.evaluate(s, {"text": "They use far less memory and RAM than lists for large inputs."})
        assert result.score <= 0.6 and not result.passed
        assert result.misconceptions[0].code == "gen-eager"

    def test_short_answers_are_capped(self):
        s = spec(concept("c", "basics"))
        result = self.ev.evaluate(s, {"text": "lazily, memory."})
        assert result.score <= 0.5

    def test_copied_prompt_earns_no_credit(self):
        challenge = concept("c", "basics")
        reference = challenge["prompt"]
        pasted = reference + " " + reference
        result = self.ev.evaluate(spec(challenge, reference), {"text": pasted})
        assert result.score < 0.5

    def test_hyphens_are_treated_as_spaces_and_regexes_work(self):
        content = {
            "criteria": [
                {"id": "x", "label": "x", "any": ["on demand"], "missing_feedback": "."},
                {"id": "y", "label": "y", "any": [r"re:\bO\(1\)"], "missing_feedback": "."},
            ]
        }
        result = self.ev.evaluate(
            ChallengeSpec("concept_explanation", content), {"text": "Values come on-demand with O(1) cost."}
        )
        assert result.score == 1.0

    def test_word_limit_validation(self):
        s = spec(concept("c", "basics"))
        with pytest.raises(InvalidResponse):
            self.ev.parse(s, {"text": "word " * 250})
        with pytest.raises(InvalidResponse):
            self.ev.parse(s, {"text": ""})


class TestDebugging:
    ev = DebuggingEvaluator()

    def test_line_and_explanation_combine(self):
        s = spec(debugging("d", "basics"))
        both = self.ev.evaluate(
            s, self.ev.parse(s, {"line": "3", "explanation": "The + 1 at the end is wrong; remove it."})
        )
        line_only = self.ev.evaluate(
            s, self.ev.parse(s, {"line": "3", "explanation": "Something is off here somewhere."})
        )
        wrong_line = self.ev.evaluate(s, self.ev.parse(s, {"line": "1", "explanation": "There is an extra one added."}))
        assert both.score == 1.0
        assert line_only.score == pytest.approx(0.4)
        assert wrong_line.score == pytest.approx(0.6)
        assert not wrong_line.checks[0].passed

    def test_rejects_out_of_range_lines(self):
        s = spec(debugging("d", "basics"))
        for line in ("0", "99", "abc"):
            with pytest.raises(InvalidResponse):
                self.ev.parse(s, {"line": line, "explanation": "the + 1 is wrong"})


class TestPythonCode:
    ev = PythonCodeEvaluator()
    challenge = {
        "kind": "python_code",
        "content": {"starter_code": "", "reference_solution": ""},
        "tests": [
            {"name": "visible", "code": "assert f() == 1"},
            {"name": "secret", "code": "assert f() != 2", "hidden": True},
        ],
    }

    def test_syntax_errors_fail_without_running(self, monkeypatch):
        called = []
        monkeypatch.setattr("apps.evaluation.code.run_tests", lambda *a, **k: called.append(1))
        result = self.ev.evaluate(spec(self.challenge), {"code": "def f(:\n  pass"})
        assert result.score == 0 and "Line 1" in result.feedback[0]
        assert called == []

    def test_unconfigured_runner_raises_instead_of_passing(self, settings):
        settings.CODE_RUNNER_URL = ""
        with pytest.raises(RunnerUnavailable):
            self.ev.evaluate(spec(self.challenge), {"code": "def f():\n    return 1\n"})

    def test_scores_runner_results_and_redacts_hidden_tests(self, monkeypatch):
        result = RunResult(
            status="completed",
            tests=[CaseOutcome("1", "passed"), CaseOutcome("2", "failed", "AssertionError: secret detail")],
        )
        monkeypatch.setattr("apps.evaluation.code.run_tests", lambda *a, **k: result)
        evaluation = self.ev.evaluate(spec(self.challenge), {"code": "def f():\n    return 1\n"})
        assert evaluation.score == 0.5
        hidden = evaluation.checks[1]
        assert hidden.hidden and "secret detail" not in hidden.detail

    def test_timeouts_are_reported(self, monkeypatch):
        result = RunResult(status="timeout", tests=[CaseOutcome("1", "timeout"), CaseOutcome("2", "not_run")])
        monkeypatch.setattr("apps.evaluation.code.run_tests", lambda *a, **k: result)
        evaluation = self.ev.evaluate(spec(self.challenge), {"code": "while True:\n    pass\n"})
        assert evaluation.score == 0
        assert any(m.code == "python-time-limit" for m in evaluation.misconceptions)
