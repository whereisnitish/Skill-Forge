"""Request validation for the runner API (pure; importable and testable anywhere)."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CODE_CHARS = 20_000
MAX_TEST_CHARS = 4_000
MAX_TESTS = 20
MAX_TIME_LIMIT = 5.0
TEST_ID = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class TestSpec:
    id: str
    code: str


@dataclass(frozen=True)
class RunRequest:
    code: str
    tests: tuple[TestSpec, ...]
    time_limit: float


def parse_request(payload: object) -> RunRequest:
    if not isinstance(payload, dict):
        raise ProtocolError("Body must be a JSON object.")
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ProtocolError("'code' must be a non-empty string.")
    if len(code) > MAX_CODE_CHARS:
        raise ProtocolError("'code' is too long.")
    raw_tests = payload.get("tests")
    if not isinstance(raw_tests, list) or not raw_tests or len(raw_tests) > MAX_TESTS:
        raise ProtocolError(f"'tests' must be a list of 1-{MAX_TESTS} items.")
    tests = []
    for item in raw_tests:
        if not isinstance(item, dict):
            raise ProtocolError("Each test must be an object.")
        test_id, test_code = item.get("id"), item.get("code")
        if not isinstance(test_id, str) or not TEST_ID.match(test_id):
            raise ProtocolError("Invalid test id.")
        if not isinstance(test_code, str) or not test_code or len(test_code) > MAX_TEST_CHARS:
            raise ProtocolError("Invalid test code.")
        tests.append(TestSpec(test_id, test_code))
    try:
        time_limit = float(payload.get("time_limit_seconds", 3))
    except (TypeError, ValueError) as exc:
        raise ProtocolError("'time_limit_seconds' must be a number.") from exc
    return RunRequest(code=code, tests=tuple(tests), time_limit=max(0.5, min(MAX_TIME_LIMIT, time_limit)))
