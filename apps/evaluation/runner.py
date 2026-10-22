"""HTTP client for the isolated code-runner service (see `sandbox/`).

User code is NEVER executed inside the web or worker processes. When the
runner is not configured, coding challenges are reported as unavailable — they
are never marked as passed.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class RunnerUnavailable(RuntimeError):
    pass


class RunnerBusy(RunnerUnavailable):
    pass


@dataclass(frozen=True)
class CaseOutcome:
    id: str
    status: str  # passed | failed | error | timeout | not_run
    message: str = ""


@dataclass(frozen=True)
class RunResult:
    status: str  # completed | compile_error | timeout | crashed
    tests: list[CaseOutcome]
    stdout: str = ""
    duration_ms: int = 0
    error: str = ""


def runner_available() -> bool:
    return bool(settings.CODE_RUNNER_URL and settings.CODE_RUNNER_TOKEN)


class _UserSlot:
    """Per-user concurrency guard using an expiring cache key."""

    def __init__(self, user_id: int | None):
        self.key = f"runner-slot:{user_id}" if user_id else None

    def __enter__(self) -> _UserSlot:
        if self.key and not cache.add(self.key, 1, timeout=int(settings.CODE_RUNNER_TIMEOUT_SECONDS) + 10):
            raise RunnerBusy("Another submission is still running.")
        return self

    def __exit__(self, *exc: object) -> None:
        if self.key:
            cache.delete(self.key)


def run_tests(code: str, tests: list[dict[str, Any]], *, user_id: int | None = None) -> RunResult:
    if not runner_available():
        raise RunnerUnavailable("The code runner is not configured.")
    payload = json.dumps(
        {
            "code": code,
            "tests": [{"id": str(t["id"]), "code": t["code"]} for t in tests],
            "time_limit_seconds": 3,
        }
    ).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - URL comes from trusted settings
        f"{settings.CODE_RUNNER_URL}/run",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.CODE_RUNNER_TOKEN}",
        },
    )
    with _UserSlot(user_id):
        try:
            with urllib.request.urlopen(request, timeout=settings.CODE_RUNNER_TIMEOUT_SECONDS) as resp:  # noqa: S310
                body = json.loads(resp.read(1_000_000).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                raise RunnerBusy("The code runner is at capacity.") from exc
            logger.warning("runner.http_error", extra={"status": exc.code})
            raise RunnerUnavailable(f"Runner responded with HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("runner.unreachable", extra={"error": type(exc).__name__})
            raise RunnerUnavailable("The code runner could not be reached.") from exc

    try:
        return RunResult(
            status=str(body["status"]),
            tests=[
                CaseOutcome(id=str(t["id"]), status=str(t["status"]), message=str(t.get("message", ""))[:500])
                for t in body.get("tests", [])
            ],
            stdout=str(body.get("stdout", ""))[:4000],
            duration_ms=int(body.get("duration_ms", 0)),
            error=str(body.get("error", ""))[:1000],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunnerUnavailable("The code runner returned an unexpected response.") from exc
