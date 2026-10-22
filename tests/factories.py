"""Small, deterministic test catalogue built through the real seeding code."""

from __future__ import annotations

from apps.catalog.content_loader import ContentBundle
from apps.catalog.seeding import sync_catalog


def mcq(slug: str, skill: str, *, difficulty: int = 2, diagnostic: bool = False, tags=None, minutes: int = 3) -> dict:
    return {
        "slug": slug,
        "skill": skill,
        "kind": "multiple_choice",
        "difficulty": difficulty,
        "minutes": minutes,
        "diagnostic": diagnostic,
        "tags": tags or [],
        "title": f"Question {slug}",
        "objective": "Recognise the right answer.",
        "prompt": "Which option is correct?",
        "hints": ["Think carefully.", "It's the first one."],
        "explanation": "Option A is correct because it is.",
        "solution": "Choose **A**.",
        "content": {
            "options": [
                {"id": "a", "text": "Correct option", "correct": True, "feedback": "Yes."},
                {
                    "id": "b",
                    "text": "Wrong option",
                    "feedback": "No.",
                    "misconception": {
                        "code": f"{skill}-confusion",
                        "label": f"Confuses {skill}",
                        "category": "conceptual",
                    },
                },
            ]
        },
    }


def short(slug: str, skill: str, *, difficulty: int = 2) -> dict:
    return {
        "slug": slug,
        "skill": skill,
        "kind": "short_answer",
        "difficulty": difficulty,
        "minutes": 3,
        "title": f"Short {slug}",
        "objective": "Recall a fact.",
        "prompt": "What is the complexity of a dict lookup on average?",
        "hints": ["Hashing."],
        "explanation": "Average O(1).",
        "content": {
            "ignore_spaces": True,
            "accepted": ["O(1)", "constant"],
            "partial": [{"answers": ["O(log n)"], "score": 0.4, "feedback": "Closer, but no."}],
            "wrong": [
                {
                    "answers": ["O(n)"],
                    "feedback": "That's a list scan.",
                    "misconception": {
                        "code": "dict-is-linear",
                        "label": "Thinks dict lookups scan",
                        "category": "performance",
                    },
                }
            ],
        },
    }


def concept(slug: str, skill: str, *, difficulty: int = 2) -> dict:
    return {
        "slug": slug,
        "skill": skill,
        "kind": "concept_explanation",
        "difficulty": difficulty,
        "minutes": 6,
        "title": f"Explain {slug}",
        "objective": "Explain laziness.",
        "prompt": "Explain why generators are memory efficient compared with building a full list in memory first.",
        "hints": ["When is each value computed?"],
        "explanation": "Generators yield lazily.",
        "content": {
            "min_words": 8,
            "max_words": 200,
            "criteria": [
                {
                    "id": "lazy",
                    "label": "Values are produced lazily",
                    "weight": 2,
                    "required": True,
                    "any": ["lazi", "on demand", "one at a time"],
                    "missing_feedback": "Say when values are produced.",
                    "misconception": {
                        "code": "gen-eager",
                        "label": "Thinks generators are eager",
                        "category": "conceptual",
                    },
                },
                {
                    "id": "memory",
                    "label": "Mentions memory",
                    "weight": 1,
                    "any": ["memory", "ram"],
                    "missing_feedback": "Mention memory.",
                },
            ],
        },
    }


def debugging(slug: str, skill: str) -> dict:
    return {
        "slug": slug,
        "skill": skill,
        "kind": "debugging",
        "difficulty": 2,
        "minutes": 5,
        "title": f"Debug {slug}",
        "objective": "Find the bug.",
        "prompt": "Find the defect.",
        "hints": ["Look at the return."],
        "explanation": "The + 1 is wrong.",
        "content": {
            "code": "def average(values):\n    total = sum(values)\n    return total / len(values) + 1\n",
            "bug_lines": [3],
            "line_weight": 0.4,
            "min_words": 3,
            "max_words": 100,
            "criteria": [
                {
                    "id": "plus-one",
                    "label": "Spots the + 1",
                    "weight": 1,
                    "any": ["+ 1", "plus one", "extra one"],
                    "missing_feedback": "Look at the arithmetic.",
                }
            ],
        },
    }


def code(slug: str, skill: str) -> dict:
    return {
        "slug": slug,
        "skill": skill,
        "kind": "python_code",
        "difficulty": 2,
        "minutes": 10,
        "title": f"Code {slug}",
        "objective": "Write a function.",
        "prompt": "Write `double(x)`.",
        "hints": ["Multiply."],
        "explanation": "Return x * 2.",
        "content": {
            "starter_code": "def double(x):\n    raise NotImplementedError\n",
            "reference_solution": "def double(x):\n    return x * 2\n",
        },
        "tests": [
            {"name": "doubles 2", "code": "assert double(2) == 4"},
            {"name": "doubles 0", "code": "assert double(0) == 0", "hidden": True},
        ],
    }


def small_bundle() -> ContentBundle:
    """Graph: basics -> intermediate -> advanced; side skill 'other' has no prerequisites."""
    return ContentBundle(
        categories=[{"slug": "core", "name": "Core", "description": "", "icon": "shapes", "order": 1}],
        skills=[
            {
                "slug": "basics",
                "name": "Basics",
                "category": "core",
                "difficulty": 1,
                "summary": "Basics.",
                "objectives": ["Know basics"],
                "review_interval_days": 2,
            },
            {
                "slug": "intermediate",
                "name": "Intermediate",
                "category": "core",
                "difficulty": 2,
                "summary": "Mid.",
                "objectives": ["Know mid"],
                "prerequisites": ["basics"],
                "review_interval_days": 2,
            },
            {
                "slug": "advanced",
                "name": "Advanced",
                "category": "core",
                "difficulty": 3,
                "summary": "Adv.",
                "objectives": ["Know adv"],
                "prerequisites": [{"skill": "intermediate", "min_mastery": 0.55}],
            },
            {
                "slug": "other",
                "name": "Other",
                "category": "core",
                "difficulty": 1,
                "summary": "Other.",
                "objectives": ["Know other"],
            },
        ],
        challenges=[
            mcq("basics-mcq", "basics", difficulty=1, diagnostic=True),
            short("basics-short", "basics", difficulty=1),
            concept("basics-concept", "basics", difficulty=1),
            mcq("intermediate-mcq", "intermediate", diagnostic=True),
            mcq("intermediate-mcq-2", "intermediate", difficulty=3),
            debugging("intermediate-debug", "intermediate"),
            mcq("advanced-mcq", "advanced", difficulty=3, diagnostic=True),
            code("advanced-code", "advanced"),
            mcq("other-mcq", "other", difficulty=1, diagnostic=True),
            short("other-short", "other", difficulty=1),
        ],
        paths=[
            {
                "slug": "test-path",
                "name": "Test Path",
                "tagline": "A path for tests.",
                "goal_type": "python",
                "default": True,
                "milestones": [
                    {"title": "First", "steps": ["basics", "intermediate"]},
                    {"title": "Second", "steps": [{"skill": "advanced", "target": 0.7}]},
                ],
            },
            {
                "slug": "premium-path",
                "name": "Premium Path",
                "tagline": "Paid.",
                "goal_type": "python",
                "premium": True,
                "milestones": [{"title": "Only", "steps": ["other"]}],
            },
        ],
    )


def load_small_catalog():
    return sync_catalog(small_bundle())
