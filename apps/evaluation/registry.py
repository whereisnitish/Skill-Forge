from __future__ import annotations

from apps.catalog.constants import ChallengeKind

from .base import Evaluator
from .choice import MultipleChoiceEvaluator
from .code import PythonCodeEvaluator
from .debugging import DebuggingEvaluator
from .rubric import RubricEvaluator
from .runner import runner_available
from .short_answer import ShortAnswerEvaluator

_rubric = RubricEvaluator()

EVALUATORS: dict[str, Evaluator] = {
    ChallengeKind.MULTIPLE_CHOICE: MultipleChoiceEvaluator(),
    ChallengeKind.SHORT_ANSWER: ShortAnswerEvaluator(),
    ChallengeKind.CONCEPT_EXPLANATION: _rubric,
    ChallengeKind.CODE_REVIEW: _rubric,
    ChallengeKind.DEBUGGING: DebuggingEvaluator(),
    ChallengeKind.PYTHON_CODE: PythonCodeEvaluator(),
}


def get_evaluator(kind: str) -> Evaluator:
    try:
        return EVALUATORS[kind]
    except KeyError as exc:
        raise ValueError(f"No evaluator for challenge kind {kind!r}") from exc


def evaluator_version(kind: str) -> str:
    return get_evaluator(kind).version


def unavailable_kinds() -> frozenset[str]:
    """Challenge kinds that cannot be evaluated in the current deployment."""
    return frozenset() if runner_available() else frozenset({ChallengeKind.PYTHON_CODE.value})


def is_async_kind(kind: str) -> bool:
    return bool(getattr(get_evaluator(kind), "requires_runner", False))
