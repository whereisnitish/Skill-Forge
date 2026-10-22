"""Load and validate curated catalogue content from YAML files.

This module has no database dependency, so content can be validated in CI or
while authoring:

    python -m apps.catalog.content_loader apps/catalog/content
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apps.engine.graph import CycleError, SkillGraph

from .constants import ChallengeKind, GoalType

CONTENT_DIR = Path(__file__).resolve().parent / "content"

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KINDS = {k.value for k in ChallengeKind}
GOALS = {g.value for g in GoalType}
MISCONCEPTION_CATEGORIES = {
    "conceptual", "syntax", "edge_case", "logic", "incomplete", "misread", "security", "performance",
}  # fmt: skip
RUBRIC_KINDS = {ChallengeKind.CONCEPT_EXPLANATION.value, ChallengeKind.CODE_REVIEW.value}


@dataclass
class ContentBundle:
    categories: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    challenges: list[dict] = field(default_factory=list)
    paths: list[dict] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)  # slug -> file name


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_content(directory: Path = CONTENT_DIR) -> ContentBundle:
    bundle = ContentBundle()
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path.name}: top level must be a mapping")
        unknown = set(data) - {"categories", "skills", "challenges", "paths"}
        if unknown:
            raise ValueError(f"{path.name}: unknown top-level keys {sorted(unknown)}")
        for key in ("categories", "skills", "challenges", "paths"):
            items = data.get(key) or []
            if not isinstance(items, list):
                raise ValueError(f"{path.name}: '{key}' must be a list")
            for item in items:
                if isinstance(item, dict) and "slug" in item:
                    bundle.sources[f"{key}:{item['slug']}"] = path.name
            getattr(bundle, key).extend(items)
    return bundle


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def challenge_version_payload(challenge: dict) -> dict:
    """Fields that define a challenge version; any change produces a new version."""
    return {
        "title": challenge.get("title", ""),
        "objective": challenge.get("objective", ""),
        "prompt": challenge.get("prompt", ""),
        "content": challenge.get("content", {}),
        "hints": challenge.get("hints", []),
        "solution": challenge.get("solution", ""),
        "explanation": challenge.get("explanation", ""),
        "tests": challenge.get("tests", []),
    }


def path_version_payload(path: dict) -> list:
    return [
        {
            "title": m.get("title", ""),
            "description": m.get("description", ""),
            "steps": [normalise_step(s) for s in m.get("steps", [])],
        }
        for m in path.get("milestones", [])
    ]


def normalise_step(step: Any) -> dict:
    if isinstance(step, str):
        return {"skill": step, "target": 0.7}
    return {"skill": step.get("skill"), "target": float(step.get("target", 0.7))}


def normalise_prerequisite(prereq: Any) -> dict:
    if isinstance(prereq, str):
        return {"skill": prereq, "strength": "required", "min_mastery": 0.55}
    return {
        "skill": prereq.get("skill"),
        "strength": prereq.get("strength", "required"),
        "min_mastery": float(prereq.get("min_mastery", 0.55)),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(bundle: ContentBundle) -> ValidationReport:
    report = ValidationReport()
    err = report.errors.append
    warn = report.warnings.append

    def where(kind: str, slug: Any) -> str:
        return f"{bundle.sources.get(f'{kind}:{slug}', '?')}: {kind[:-1]} '{slug}'"

    category_slugs = _unique_slugs(bundle.categories, "categories", report, where)
    skill_slugs = _unique_slugs(bundle.skills, "skills", report, where)
    challenge_slugs = _unique_slugs(bundle.challenges, "challenges", report, where)
    _unique_slugs(bundle.paths, "paths", report, where)
    del challenge_slugs

    for category in bundle.categories:
        if not category.get("name"):
            err(f"{where('categories', category.get('slug'))}: missing name")

    edges: list[tuple[str, str]] = []
    for skill in bundle.skills:
        loc = where("skills", skill.get("slug"))
        _require(skill, ["name", "category", "summary", "difficulty"], loc, err)
        if skill.get("category") not in category_slugs:
            err(f"{loc}: unknown category {skill.get('category')!r}")
        _check_int(skill.get("difficulty"), 1, 5, f"{loc}: difficulty", err)
        if len(str(skill.get("summary", ""))) > 240:
            err(f"{loc}: summary longer than 240 characters")
        objectives = skill.get("objectives", [])
        if not isinstance(objectives, list) or not objectives or not all(isinstance(o, str) for o in objectives):
            err(f"{loc}: objectives must be a non-empty list of strings")
        _check_int(skill.get("review_interval_days", 2), 1, 30, f"{loc}: review_interval_days", err)
        for raw in skill.get("prerequisites", []) or []:
            prereq = normalise_prerequisite(raw)
            if prereq["skill"] not in skill_slugs:
                err(f"{loc}: unknown prerequisite {prereq['skill']!r}")
                continue
            if prereq["strength"] not in {"required", "recommended"}:
                err(f"{loc}: prerequisite strength must be 'required' or 'recommended'")
            if not 0.0 <= prereq["min_mastery"] <= 1.0:
                err(f"{loc}: min_mastery must be between 0 and 1")
            edges.append((skill["slug"], prereq["skill"]))
        for related in skill.get("related", []) or []:
            if related not in skill_slugs:
                err(f"{loc}: unknown related skill {related!r}")
            if related == skill.get("slug"):
                err(f"{loc}: a skill cannot be related to itself")

    try:
        SkillGraph.from_edges(skill_slugs, edges).validate()
    except CycleError as exc:
        err(str(exc))

    per_skill: dict[str, list[dict]] = {slug: [] for slug in skill_slugs}
    for challenge in bundle.challenges:
        _validate_challenge(challenge, skill_slugs, where("challenges", challenge.get("slug")), err, warn)
        if challenge.get("skill") in per_skill:
            per_skill[challenge["skill"]].append(challenge)

    for slug, items in per_skill.items():
        if len(items) < 2:
            warn(f"skill '{slug}' has {len(items)} challenge(s); at least 2 recommended")
        if not any(c.get("diagnostic") for c in items):
            warn(f"skill '{slug}' has no diagnostic challenge")

    defaults: dict[str, list[str]] = {}
    for path in bundle.paths:
        loc = where("paths", path.get("slug"))
        _require(path, ["name", "tagline", "goal_type", "milestones"], loc, err)
        if path.get("goal_type") not in GOALS:
            err(f"{loc}: unknown goal_type {path.get('goal_type')!r}")
        if path.get("default"):
            defaults.setdefault(path.get("goal_type"), []).append(path.get("slug"))
        seen: set[str] = set()
        for m_index, milestone in enumerate(path.get("milestones") or [], start=1):
            if not milestone.get("title"):
                err(f"{loc}: milestone {m_index} missing title")
            steps = milestone.get("steps") or []
            if not steps:
                err(f"{loc}: milestone {m_index} has no steps")
            for raw in steps:
                step = normalise_step(raw)
                if step["skill"] not in skill_slugs:
                    err(f"{loc}: unknown step skill {step['skill']!r}")
                if step["skill"] in seen:
                    err(f"{loc}: skill {step['skill']!r} appears more than once")
                seen.add(step["skill"])
                if not 0.1 <= step["target"] <= 1.0:
                    err(f"{loc}: step target must be between 0.1 and 1.0")
    for goal, slugs in defaults.items():
        if len(slugs) > 1:
            err(f"goal_type {goal!r} has several default paths: {slugs}")
    for goal in GOALS:
        if bundle.paths and goal not in defaults:
            warn(f"goal_type {goal!r} has no default path")
    return report


def _unique_slugs(items: list[dict], kind: str, report: ValidationReport, where) -> set[str]:
    slugs: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            report.errors.append(f"{kind}: every entry must be a mapping")
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not SLUG.match(slug):
            report.errors.append(f"{kind}: invalid slug {slug!r}")
            continue
        if slug in slugs:
            report.errors.append(f"{where(kind, slug)}: duplicate slug")
        slugs.add(slug)
    return slugs


def _require(item: dict, keys: list[str], loc: str, err) -> None:
    for key in keys:
        if item.get(key) in (None, "", []):
            err(f"{loc}: missing '{key}'")


def _check_int(value: Any, low: int, high: int, label: str, err) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        err(f"{label} must be an integer between {low} and {high}")


def _check_misconception(value: Any, loc: str, err) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        err(f"{loc}: misconception must be a mapping")
        return
    if not SLUG.match(str(value.get("code", ""))):
        err(f"{loc}: misconception code must be a slug")
    if not value.get("label"):
        err(f"{loc}: misconception needs a label")
    if value.get("category") not in MISCONCEPTION_CATEGORIES:
        err(f"{loc}: misconception category must be one of {sorted(MISCONCEPTION_CATEGORIES)}")


def _check_patterns(entries: list, loc: str, err) -> None:
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            err(f"{loc}: keyword entries must be non-empty strings")
            continue
        if entry.startswith("re:"):
            try:
                re.compile(entry[3:], re.IGNORECASE)
            except re.error as exc:
                err(f"{loc}: invalid regex {entry!r}: {exc}")


def _check_criteria(content: dict, loc: str, err, minimum: int) -> None:
    criteria = content.get("criteria") or []
    if len(criteria) < minimum:
        err(f"{loc}: needs at least {minimum} rubric criteria")
    ids: set[str] = set()
    for criterion in criteria:
        cid = criterion.get("id")
        if not isinstance(cid, str) or not SLUG.match(cid):
            err(f"{loc}: criterion id {cid!r} must be a slug")
        elif cid in ids:
            err(f"{loc}: duplicate criterion id {cid!r}")
        ids.add(str(cid))
        if not criterion.get("label"):
            err(f"{loc}: criterion {cid!r} missing label")
        weight = criterion.get("weight", 1)
        if not isinstance(weight, (int, float)) or weight <= 0:
            err(f"{loc}: criterion {cid!r} weight must be positive")
        if not criterion.get("any"):
            err(f"{loc}: criterion {cid!r} needs an 'any' keyword list")
        else:
            _check_patterns(criterion["any"], f"{loc} criterion {cid!r}", err)
        if not criterion.get("missing_feedback"):
            err(f"{loc}: criterion {cid!r} needs missing_feedback")
        _check_misconception(criterion.get("misconception"), f"{loc} criterion {cid!r}", err)
    min_words = content.get("min_words", 0)
    max_words = content.get("max_words", 600)
    if not isinstance(min_words, int) or not isinstance(max_words, int) or min_words >= max_words:
        err(f"{loc}: min_words must be an integer smaller than max_words")


def _compiles(source: str, loc: str, label: str, err) -> None:
    try:
        compile(source, f"<{label}>", "exec")
    except SyntaxError as exc:
        err(f"{loc}: {label} does not compile: {exc}")


def _validate_challenge(challenge: dict, skill_slugs: set[str], loc: str, err, warn) -> None:
    _require(challenge, ["skill", "kind", "difficulty", "minutes", "title", "objective", "prompt"], loc, err)
    if challenge.get("skill") not in skill_slugs:
        err(f"{loc}: unknown skill {challenge.get('skill')!r}")
    for secondary in challenge.get("secondary_skills", []) or []:
        if secondary not in skill_slugs:
            err(f"{loc}: unknown secondary skill {secondary!r}")
        if secondary == challenge.get("skill"):
            err(f"{loc}: secondary skill duplicates the primary skill")
    kind = challenge.get("kind")
    if kind not in KINDS:
        err(f"{loc}: unknown kind {kind!r}")
        return
    _check_int(challenge.get("difficulty"), 1, 5, f"{loc}: difficulty", err)
    _check_int(challenge.get("minutes"), 1, 60, f"{loc}: minutes", err)
    if len(str(challenge.get("title", ""))) > 200:
        err(f"{loc}: title longer than 200 characters")
    if len(str(challenge.get("objective", ""))) > 300:
        err(f"{loc}: objective longer than 300 characters")
    hints = challenge.get("hints", [])
    if not isinstance(hints, list) or not all(isinstance(h, str) for h in hints):
        err(f"{loc}: hints must be a list of strings")
    elif not hints:
        warn(f"{loc}: no hints provided")
    if not challenge.get("explanation"):
        err(f"{loc}: missing explanation")
    tags = challenge.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) and SLUG.match(t) for t in tags):
        err(f"{loc}: tags must be a list of slugs")

    content = challenge.get("content") or {}
    if not isinstance(content, dict):
        err(f"{loc}: content must be a mapping")
        return

    if kind == ChallengeKind.MULTIPLE_CHOICE:
        options = content.get("options") or []
        if len(options) < 2:
            err(f"{loc}: needs at least two options")
        ids = [str(o.get("id")) for o in options]
        if len(set(ids)) != len(ids):
            err(f"{loc}: option ids must be unique")
        correct = [o for o in options if o.get("correct")]
        if not correct:
            err(f"{loc}: needs a correct option")
        if not content.get("multiple") and len(correct) != 1:
            err(f"{loc}: single-answer questions need exactly one correct option")
        for option in options:
            if not option.get("text"):
                err(f"{loc}: option {option.get('id')!r} missing text")
            if not option.get("feedback"):
                err(f"{loc}: option {option.get('id')!r} missing feedback")
            _check_misconception(option.get("misconception"), f"{loc} option {option.get('id')!r}", err)

    elif kind == ChallengeKind.SHORT_ANSWER:
        accepted = content.get("accepted") or []
        if not accepted or not all(isinstance(a, str) for a in accepted):
            err(f"{loc}: needs a non-empty 'accepted' list of strings")
        for pattern in content.get("patterns", []) or []:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                err(f"{loc}: invalid pattern {pattern!r}: {exc}")
        for entry in content.get("partial", []) or []:
            if not entry.get("answers") or not 0 < float(entry.get("score", 0)) < 1:
                err(f"{loc}: partial entries need answers and a score between 0 and 1")
        for entry in content.get("wrong", []) or []:
            if not entry.get("answers") or not entry.get("feedback"):
                err(f"{loc}: wrong-answer entries need answers and feedback")
            _check_misconception(entry.get("misconception"), f"{loc} wrong answer", err)

    elif kind in RUBRIC_KINDS:
        _check_criteria(content, loc, err, minimum=2)
        if kind == ChallengeKind.CODE_REVIEW and not content.get("code"):
            err(f"{loc}: code review challenges need 'code' to review")

    elif kind == ChallengeKind.DEBUGGING:
        code = content.get("code") or ""
        if not code:
            err(f"{loc}: debugging challenges need 'code'")
        lines = code.rstrip("\n").count("\n") + 1 if code else 0
        bug_lines = content.get("bug_lines") or []
        if not bug_lines or not all(isinstance(n, int) and 1 <= n <= lines for n in bug_lines):
            err(f"{loc}: bug_lines must list line numbers within the code (1..{lines})")
        _check_criteria(content, loc, err, minimum=1)

    elif kind == ChallengeKind.PYTHON_CODE:
        starter = content.get("starter_code") or ""
        reference = content.get("reference_solution") or ""
        if not starter:
            err(f"{loc}: python_code challenges need starter_code")
        else:
            _compiles(starter, loc, "starter_code", err)
        if not reference:
            err(f"{loc}: python_code challenges need reference_solution")
        else:
            _compiles(reference, loc, "reference_solution", err)
        tests = challenge.get("tests") or []
        if len(tests) < 2:
            err(f"{loc}: python_code challenges need at least two tests")
        if tests and all(t.get("hidden") for t in tests):
            err(f"{loc}: at least one test must be visible")
        for index, test in enumerate(tests, start=1):
            if not test.get("name") or not test.get("code"):
                err(f"{loc}: test {index} needs a name and code")
            else:
                _compiles(test["code"], loc, f"test {index}", err)

    if kind != ChallengeKind.PYTHON_CODE and challenge.get("tests"):
        err(f"{loc}: only python_code challenges can define tests")


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else CONTENT_DIR
    bundle = load_content(directory)
    report = validate(bundle)
    for warning in report.warnings:
        print(f"warning: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")
    print(
        f"{len(bundle.categories)} categories, {len(bundle.skills)} skills, "
        f"{len(bundle.challenges)} challenges, {len(bundle.paths)} paths; "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)."
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
