"""Run one submission in a fresh, resource-limited child interpreter (POSIX only).

The child is a new session (process group) running the trusted harness, which
applies kernel resource limits to itself before loading learner code. On a
wall-clock overrun the whole process group is killed. The working directory
is private and removed afterwards; the environment carries no secrets.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .protocol import RunRequest

HARNESS = Path(__file__).with_name("harness.py")
MEMORY_LIMIT_BYTES = int(os.environ.get("RUNNER_MEMORY_LIMIT_MB", "256")) * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
WORK_ROOT = os.environ.get("RUNNER_WORK_ROOT", tempfile.gettempdir())


class SandboxUnsupported(RuntimeError):
    """Raised on platforms where the required kernel resource limits are unavailable."""


def execute(request: RunRequest) -> dict:
    if os.name != "posix":
        raise SandboxUnsupported("The sandbox requires POSIX resource limits; refusing to execute code.")
    nonce = secrets.token_hex(16)
    total_budget = request.time_limit * (len(request.tests) + 1) + 2
    workdir = tempfile.mkdtemp(prefix="run-", dir=WORK_ROOT)
    started = time.monotonic()
    try:
        Path(workdir, "solution.py").write_text(request.code, encoding="utf-8")
        Path(workdir, "tests.json").write_text(
            json.dumps([{"id": t.id, "code": t.code} for t in request.tests]), encoding="utf-8"
        )
        shutil.copyfile(HARNESS, Path(workdir, "harness.py"))
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": workdir,
            "LANG": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SF_RUN_NONCE": nonce,
            "SF_TEST_TIME_LIMIT": str(request.time_limit),
            "SF_CPU_LIMIT": str(int(total_budget) + 1),
            "SF_MEMORY_LIMIT": str(MEMORY_LIMIT_BYTES),
        }
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", "harness.py"],
            cwd=workdir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(timeout=total_budget)
        except subprocess.TimeoutExpired:
            _kill_group(process.pid)
            process.communicate()
            return _not_run(request, "timeout", started)
        finally:
            _kill_group(process.pid)  # reap anything left in the group
        for line in reversed(stdout[-MAX_OUTPUT_BYTES:].decode("utf-8", "replace").splitlines()):
            if line.startswith(nonce):
                result = json.loads(line[len(nonce) :])
                result["duration_ms"] = int((time.monotonic() - started) * 1000)
                return result
        crashed = _not_run(request, "crashed", started)
        crashed["error"] = "The program ended unexpectedly (resource limit or crash)."
        if process.returncode and process.returncode < 0:
            crashed["error"] += f" Signal {-process.returncode}."
        return crashed
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def _not_run(request: RunRequest, status: str, started: float) -> dict:
    return {
        "status": status,
        "tests": [{"id": t.id, "status": "not_run"} for t in request.tests],
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
