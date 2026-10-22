"""Authoring check: run curated reference solutions against their own tests.

This executes ONLY trusted, repository-authored content (reference solutions
and test assertions written by curriculum authors). It never runs learner
code — learner submissions are executed exclusively by the sandbox service.

    python -m apps.catalog.verify_solutions
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from .content_loader import CONTENT_DIR, load_content

HARNESS = textwrap.dedent(
    """
    import json, sys
    namespace = {"__name__": "solution"}
    source = open(sys.argv[1], encoding="utf-8").read()
    tests = json.load(open(sys.argv[2], encoding="utf-8"))
    results = []
    try:
        exec(compile(source, "solution.py", "exec"), namespace)
    except BaseException as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(0)
    for test in tests:
        try:
            exec(compile(test["code"], "test.py", "exec"), dict(namespace))
            results.append({"name": test["name"], "passed": True})
        except BaseException as exc:
            results.append({"name": test["name"], "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps({"results": results}))
    """
)


def run(source: str, tests: list[dict], timeout: float = 10.0) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "harness.py").write_text(HARNESS, encoding="utf-8")
        (tmp_path / "solution.py").write_text(source, encoding="utf-8")
        (tmp_path / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
        completed = subprocess.run(  # noqa: S603 - trusted authoring content only
            [
                sys.executable,
                "-I",
                str(tmp_path / "harness.py"),
                str(tmp_path / "solution.py"),
                str(tmp_path / "tests.json"),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmp,
            check=False,
        )
        output = completed.stdout.strip().splitlines()
        if not output:
            return {"error": completed.stderr.strip()[-500:] or "no output"}
        return json.loads(output[-1])


def main() -> int:
    bundle = load_content(CONTENT_DIR)
    failures = 0
    checked = 0
    for challenge in bundle.challenges:
        if challenge.get("kind") != "python_code":
            continue
        checked += 1
        content = challenge.get("content", {})
        tests = challenge.get("tests", [])
        reference = run(content.get("reference_solution", ""), tests)
        if "error" in reference:
            failures += 1
            print(f"FAIL {challenge['slug']}: reference solution crashed: {reference['error']}")
            continue
        failed = [r for r in reference["results"] if not r["passed"]]
        if failed:
            failures += 1
            for result in failed:
                print(f"FAIL {challenge['slug']}: reference fails '{result['name']}': {result.get('error')}")
        starter = run(content.get("starter_code", ""), tests)
        if "results" in starter and all(r["passed"] for r in starter["results"]):
            failures += 1
            print(f"FAIL {challenge['slug']}: starter code already passes every test")
    print(f"Checked {checked} python_code challenge(s); {failures} problem(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
