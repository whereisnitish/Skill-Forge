"""Plan catalogue and entitlements. Entitlements are enforced server-side, never by UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price: str
    period: str
    tagline: str
    features: tuple[str, ...]
    entitlements: dict = field(default_factory=dict)
    purchasable: bool = False
    contact_sales: bool = False
    highlighted: bool = False


PLANS: dict[str, Plan] = {
    "free": Plan(
        code="free",
        name="Free",
        price="$0",
        period="forever",
        tagline="Build a daily practice habit.",
        features=(
            "Adaptive daily plan and spaced reviews",
            "All core learning paths",
            "Up to 8 graded submissions per day",
            "5 AI mentor requests per day (when AI is enabled)",
            "Progress, mastery and history",
        ),
        entitlements={
            "daily_submissions": 8,
            "ai_mentor_daily": 5,
            "advanced_analytics": False,
            "premium_paths": False,
        },
    ),
    "pro": Plan(
        code="pro",
        name="Pro",
        price="$12",
        period="per month",
        tagline="For engineers who practise most days.",
        features=(
            "Everything in Free",
            "Unlimited graded submissions",
            "60 AI mentor requests per day",
            "Advanced analytics: retention, difficulty and error trends",
            "Premium paths, including Interview Sprint",
        ),
        entitlements={
            "daily_submissions": None,
            "ai_mentor_daily": 60,
            "advanced_analytics": True,
            "premium_paths": True,
        },
        purchasable=True,
        highlighted=True,
    ),
    "interview": Plan(
        code="interview",
        name="Interview Preparation",
        price="$29",
        period="per month",
        tagline="An intensive season of interview practice.",
        features=(
            "Everything in Pro",
            "120 AI mentor requests per day",
            "Interview Sprint path with harder targets",
            "Cancel any time from the billing portal",
        ),
        entitlements={
            "daily_submissions": None,
            "ai_mentor_daily": 120,
            "advanced_analytics": True,
            "premium_paths": True,
        },
        purchasable=True,
    ),
    "teams": Plan(
        code="teams",
        name="Teams",
        price="Custom",
        period="per seat",
        tagline="For engineering teams that learn together.",
        features=(
            "Everything in Pro for every seat",
            "Team workspaces are in development",
            "Talk to us about early access",
        ),
        entitlements={
            "daily_submissions": None,
            "ai_mentor_daily": 60,
            "advanced_analytics": True,
            "premium_paths": True,
        },
        contact_sales=True,
    ),
}

PAID_PLAN_CODES = {code for code, plan in PLANS.items() if plan.purchasable}


def get_plan(code: str) -> Plan:
    return PLANS.get(code, PLANS["free"])
