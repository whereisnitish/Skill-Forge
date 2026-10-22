"""In-sandbox harness executed by a fresh, resource-limited interpreter for each run.

It loads the learner's code, runs every test in a copy of the resulting
namespace with a per-test wall-clock alarm, and prints one result line tagged
with a per-run nonce. Learner output is captured so it can't corrupt the
protocol. An audit hook refuses networking, subprocesses and writes outside the
working directory — defence in depth on top of the container and rlimits, not
a security boundary on its own.
"""

import io
import json
import os
import signal
import sys
import traceback

NONCE = os.environ.pop("SF_RUN_NONCE", "")
TIME_LIMIT = float(os.environ.pop("SF_TEST_TIME_LIMIT", "3"))
CPU_LIMIT = int(os.environ.pop("SF_CPU_LIMIT", "10"))
MEMORY_LIMIT = int(os.environ.pop("SF_MEMORY_LIMIT", str(256 * 1024 * 1024)))
WORKDIR = os.getcwd()
REAL_STDOUT = sys.stdout


def apply_limits():
    """Applied by this trusted harness to itself before any learner code is loaded."""
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT, CPU_LIMIT))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))  # no new processes or threads
    os.umask(0o077)


BLOCKED_PREFIXES = (
    "socket.",
    "subprocess.",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "pty.",
    "ctypes.",
)


def audit(event, args):
    if event.startswith(BLOCKED_PREFIXES):
        raise PermissionError(f"{event} is not allowed in the sandbox")
    if event == "open" and args and len(args) > 1:
        path, mode = args[0], args[1]
        writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
        if writing and isinstance(path, str) and not os.path.abspath(path).startswith(WORKDIR):
            raise PermissionError("writing outside the working directory is not allowed")


class TestTimeout(Exception):
    pass


def on_alarm(signum, frame):
    raise TestTimeout()


def short(exc):
    text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return text[:500]


def emit(payload):
    REAL_STDOUT.write(f"{NONCE}{json.dumps(payload)}\n")
    REAL_STDOUT.flush()


def main():
    with open("solution.py", encoding="utf-8") as fh:
        source = fh.read()
    with open("tests.json", encoding="utf-8") as fh:
        tests = json.load(fh)
    apply_limits()
    captured = io.StringIO()
    sys.addaudithook(audit)
    signal.signal(signal.SIGALRM, on_alarm)
    sys.stdout = captured
    sys.stderr = captured

    namespace = {"__name__": "solution"}
    try:
        signal.setitimer(signal.ITIMER_REAL, TIME_LIMIT)
        exec(compile(source, "solution.py", "exec"), namespace)  # noqa: S102 - this IS the sandbox
        signal.setitimer(signal.ITIMER_REAL, 0)
    except TestTimeout:
        emit(
            {
                "status": "timeout",
                "tests": [{"id": t["id"], "status": "not_run"} for t in tests],
                "stdout": captured.getvalue()[-4000:],
            }
        )
        return
    except BaseException as exc:  # noqa: BLE001
        signal.setitimer(signal.ITIMER_REAL, 0)
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()[-1000:]
        emit(
            {
                "status": "compile_error",
                "error": detail,
                "tests": [{"id": t["id"], "status": "not_run"} for t in tests],
                "stdout": captured.getvalue()[-4000:],
            }
        )
        return

    results = []
    any_timeout = False
    for test in tests:
        try:
            signal.setitimer(signal.ITIMER_REAL, TIME_LIMIT)
            exec(compile(test["code"], f"test_{test['id']}.py", "exec"), dict(namespace))  # noqa: S102
            signal.setitimer(signal.ITIMER_REAL, 0)
            results.append({"id": test["id"], "status": "passed"})
        except TestTimeout:
            any_timeout = True
            results.append({"id": test["id"], "status": "timeout", "message": "Time limit exceeded"})
        except AssertionError as exc:
            signal.setitimer(signal.ITIMER_REAL, 0)
            results.append(
                {"id": test["id"], "status": "failed", "message": short(exc) if str(exc) else "AssertionError"}
            )
        except BaseException as exc:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            results.append({"id": test["id"], "status": "error", "message": short(exc)})
    emit({"status": "timeout" if any_timeout else "completed", "tests": results, "stdout": captured.getvalue()[-4000:]})


if __name__ == "__main__":
    main()
