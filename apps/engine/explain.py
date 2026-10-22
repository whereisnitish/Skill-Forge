"""Deterministic, human-readable explanations for recommendations.

Every recommendation stores a reason code, the rendered sentence and the
structured data behind it, so the product can always answer "why this?".
"""

from __future__ import annotations

from dataclasses import dataclass, field

REASON_LABELS = {
    "review_due": "Due for review",
    "recent_struggle": "Targets a recent struggle",
    "prerequisite": "Unlocks the next skill",
    "goal_priority": "Goal priority",
    "next_in_path": "Next on your path",
    "explore_unmeasured": "Calibration check",
    "build_mastery": "Builds mastery",
    "diagnostic": "Placement check",
}


@dataclass(frozen=True)
class ExplanationContext:
    skill_name: str
    urgency: float
    weakness: float
    goal_relevance: float
    dependency_importance: float
    contributions: dict[str, float]
    mean: float
    evidence_count: int
    days_since_practice: int | None = None
    recent_failures: int = 0
    top_misconception: str | None = None
    blocking_for: tuple[str, ...] = field(default_factory=tuple)
    is_focus_skill: bool = False
    milestone_title: str | None = None
    in_current_milestone: bool = False
    path_name: str | None = None
    explored: bool = False


@dataclass(frozen=True)
class Explanation:
    code: str
    text: str
    data: dict

    @property
    def label(self) -> str:
        return REASON_LABELS.get(self.code, "Recommended")


def _days(n: int | None) -> str:
    if n is None:
        return "a while ago"
    if n <= 0:
        return "earlier today"
    if n == 1:
        return "yesterday"
    return f"{n} days ago"


def explain(ctx: ExplanationContext) -> Explanation:
    data = {
        "skill": ctx.skill_name,
        "components": {k: round(v, 4) for k, v in ctx.contributions.items()},
        "mean": round(ctx.mean, 3),
        "evidence_count": ctx.evidence_count,
        "urgency": round(ctx.urgency, 3),
        "recent_failures": ctx.recent_failures,
    }
    skill = ctx.skill_name

    if ctx.explored:
        return Explanation(
            "explore_unmeasured",
            f"We haven't measured {skill} yet — this quick check helps calibrate your plan.",
            data,
        )

    dominant = max(ctx.contributions, key=ctx.contributions.get) if ctx.contributions else ""

    if ctx.urgency >= 0.6 or (ctx.urgency > 0 and dominant == "review_urgency"):
        data["days_since_practice"] = ctx.days_since_practice
        return Explanation(
            "review_due",
            f"Scheduled because {skill} is due for review — you last practised it {_days(ctx.days_since_practice)}.",
            data,
        )

    if ctx.recent_failures >= 2 or (ctx.recent_failures >= 1 and ctx.top_misconception):
        count = ctx.recent_failures
        noun = "exercise" if count == 1 else "exercises"
        text = f"Selected because you struggled with {skill} in {count} recent {noun}"
        if ctx.top_misconception:
            data["misconception"] = ctx.top_misconception
            text += f" (recurring issue: {ctx.top_misconception.rstrip('.')})"
        return Explanation("recent_struggle", text + ".", data)

    if ctx.is_focus_skill:
        return Explanation("goal_priority", f"Selected because your goal prioritises {skill}.", data)

    if ctx.in_current_milestone and ctx.milestone_title and ctx.path_name:
        data["milestone"] = ctx.milestone_title
        return Explanation(
            "next_in_path",
            f"Next step in “{ctx.milestone_title}” on your {ctx.path_name} path.",
            data,
        )

    if ctx.blocking_for:
        data["blocking_for"] = list(ctx.blocking_for)
        target = ctx.blocking_for[0]
        return Explanation(
            "prerequisite",
            f"Selected to practise {skill}, a prerequisite for {target}.",
            data,
        )

    if ctx.milestone_title and ctx.path_name:
        data["milestone"] = ctx.milestone_title
        return Explanation(
            "next_in_path",
            f"Part of “{ctx.milestone_title}” on your {ctx.path_name} path.",
            data,
        )

    if ctx.evidence_count == 0:
        return Explanation(
            "build_mastery",
            f"A first look at {skill} — a good next step for your goal.",
            data,
        )
    return Explanation(
        "build_mastery",
        f"Builds toward proficiency in {skill} — your current estimate is {round(ctx.mean * 100)}%.",
        data,
    )
