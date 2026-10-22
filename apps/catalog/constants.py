"""Shared catalogue vocabulary used across apps."""

from __future__ import annotations

from django.db import models


class ChallengeKind(models.TextChoices):
    MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
    SHORT_ANSWER = "short_answer", "Short answer"
    PYTHON_CODE = "python_code", "Python coding"
    DEBUGGING = "debugging", "Debugging"
    CONCEPT_EXPLANATION = "concept_explanation", "Concept explanation"
    CODE_REVIEW = "code_review", "Code review"


KIND_ICONS = {
    ChallengeKind.MULTIPLE_CHOICE: "list-checks",
    ChallengeKind.SHORT_ANSWER: "text-cursor-input",
    ChallengeKind.PYTHON_CODE: "code-xml",
    ChallengeKind.DEBUGGING: "bug",
    ChallengeKind.CONCEPT_EXPLANATION: "message-square-text",
    ChallengeKind.CODE_REVIEW: "git-pull-request",
}

# Learner-facing practice preferences map onto challenge kinds and tags.
FORMAT_FAMILIES: dict[str, dict] = {
    "coding": {
        "label": "Coding exercises",
        "description": "Write working Python against real test cases.",
        "icon": "code-xml",
        "kinds": {ChallengeKind.PYTHON_CODE},
        "tags": set(),
    },
    "debugging": {
        "label": "Debugging",
        "description": "Find the defect in realistic code and explain the fix.",
        "icon": "bug",
        "kinds": {ChallengeKind.DEBUGGING},
        "tags": set(),
    },
    "conceptual": {
        "label": "Conceptual questions",
        "description": "Quick checks and explanations that test understanding.",
        "icon": "lightbulb",
        "kinds": {
            ChallengeKind.MULTIPLE_CHOICE,
            ChallengeKind.SHORT_ANSWER,
            ChallengeKind.CONCEPT_EXPLANATION,
        },
        "tags": set(),
    },
    "practical": {
        "label": "Practical scenarios & code review",
        "description": "Review pull requests and reason about production situations.",
        "icon": "git-pull-request",
        "kinds": {ChallengeKind.CODE_REVIEW},
        "tags": {"scenario"},
    },
    "interview": {
        "label": "Interview-style questions",
        "description": "The kind of questions asked in technical interviews.",
        "icon": "messages-square",
        "kinds": set(),
        "tags": {"interview"},
    },
}

FORMAT_CHOICES = [(code, data["label"]) for code, data in FORMAT_FAMILIES.items()]


class GoalType(models.TextChoices):
    PYTHON = "python", "Become a better Python developer"
    INTERVIEWS = "interviews", "Prepare for technical interviews"
    DJANGO = "django", "Master Django and backend development"
    AI = "ai", "Learn AI and LLM engineering"
    SYSTEM_DESIGN = "system_design", "Improve system design"
    COMMUNICATION = "communication", "Build professional communication skills"


GOAL_ICONS = {
    GoalType.PYTHON: "file-code-2",
    GoalType.INTERVIEWS: "briefcase",
    GoalType.DJANGO: "server",
    GoalType.AI: "brain-circuit",
    GoalType.SYSTEM_DESIGN: "network",
    GoalType.COMMUNICATION: "message-circle-more",
}

DIFFICULTY_LABELS = {1: "Introductory", 2: "Foundational", 3: "Intermediate", 4: "Advanced", 5: "Expert"}
