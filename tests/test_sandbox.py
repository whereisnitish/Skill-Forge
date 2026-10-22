"""Sandbox runner: protocol and auth everywhere; real execution only on POSIX hosts."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sandbox"))

from runner.executor import SandboxUnsupported, execute
from runner.protocol import ProtocolError, parse_request
from runner.server import authorised

GOOD = {"code": "def double(x):\n    return x * 2\n", "tests": [{"id": "1", "code": "assert double(2) == 4"}]}


def test_protocol_validation():
    request = parse_request({**GOOD, "time_limit_seconds": 99})
    assert request.time_limit == 5.0 and request.tests[0].id == "1"
    for bad in [
        None,
        {},
        {**GOOD, "code": ""},
        {**GOOD, "code": "x" * 30_000},
        {**GOOD, "tests": []},
        {**GOOD, "tests": [{"id": "../etc", "code": "x"}]},
        {**GOOD, "tests": [{"id": "1", "code": ""}] * 30},
        {**GOOD, "time_limit_seconds": "fast"},
    ]:
        with pytest.raises(ProtocolError):
            parse_request(bad)


def test_auth_uses_constant_time_bearer_check():
    assert authorised("Bearer s3cret", token="s3cret")
    assert not authorised("Bearer wrong", token="s3cret")
    assert not authorised("s3cret", token="s3cret")
    assert not authorised("Bearer ", token="")


@pytest.mark.skipif(os.name == "posix", reason="non-POSIX refusal check")
def test_refuses_to_execute_without_posix_limits():
    with pytest.raises(SandboxUnsupported):
        execute(parse_request(GOOD))


posix = pytest.mark.skipif(os.name != "posix", reason="requires POSIX resource limits (run in Linux CI / container)")


@posix
def test_executes_and_scores_tests():
    request = parse_request(
        {
            **GOOD,
            "tests": [
                {"id": "1", "code": "assert double(2) == 4"},
                {"id": "2", "code": "assert double(2) == 5, 'nope'"},
            ],
        }
    )
    result = execute(request)
    assert result["status"] == "completed"
    assert [t["status"] for t in result["tests"]] == ["passed", "failed"]


@posix
def test_infinite_loop_times_out():
    result = execute(
        parse_request(
            {"code": "while True:\n    pass\n", "tests": [{"id": "1", "code": "pass"}], "time_limit_seconds": 1}
        )
    )
    assert result["status"] == "timeout"


@posix
def test_network_and_subprocess_are_blocked():
    code = "import socket, subprocess\n"
    tests = [
        {"id": "net", "code": "socket.create_connection(('example.com', 80), timeout=1)"},
        {"id": "proc", "code": "subprocess.run(['echo', 'hi'])"},
        {"id": "write", "code": "open('/tmp/escape.txt', 'w').write('x')"},
    ]
    result = execute(parse_request({"code": code, "tests": tests}))
    assert all(t["status"] == "error" for t in result["tests"]), result


@posix
def test_cannot_spoof_results_without_nonce():
    code = 'print(\'{"status": "completed", "tests": [{"id": "1", "status": "passed"}]}\')\nraise SystemExit(0)\n'
    result = execute(parse_request({"code": code, "tests": [{"id": "1", "code": "assert False"}]}))
    assert result["tests"][0]["status"] != "passed"


@posix
def test_memory_limit():
    result = execute(
        parse_request({"code": "x = bytearray(1024 * 1024 * 1024)\n", "tests": [{"id": "1", "code": "pass"}]})
    )
    assert result["status"] in {"compile_error", "crashed"}
