"""Progress analytics computed from attempts, evaluations and review records.

Each function returns plain data plus a chart spec consumed by static/js/app.js.
Small samples are reported as such; nothing is extrapolated or invented.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.core.timeutils import local_now

from ..models import AttemptEvaluation, LearningAttempt, Recommendation, ReviewRecord

CATEGORY_LABELS = {
    "conceptual": "Conceptual",
    "syntax": "Syntax",
    "edge_case": "Edge cases",
    "logic": "Logic",
    "incomplete": "Incomplete answers",
    "misread": "Misread question",
    "security": "Security",
    "performance": "Performance",
}
MIN_SAMPLE = 5


@dataclass(frozen=True)
class Totals:
    attempts: int
    evaluated: int
    passed: int
    minutes: int
    skills: int
    hints: int

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.evaluated if self.evaluated else None


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def totals(user) -> Totals:
    agg = LearningAttempt.objects.filter(user=user).aggregate(
        attempts=Count("id"),
        evaluated=Count("id", filter=Q(status=LearningAttempt.Status.EVALUATED)),
        passed=Count("id", filter=Q(evaluation__passed=True)),
        seconds=Sum("time_spent_seconds"),
        skills=Count("challenge__skill", distinct=True),
        hints=Sum("hints_used"),
    )
    return Totals(
        attempts=agg["attempts"] or 0,
        evaluated=agg["evaluated"] or 0,
        passed=agg["passed"] or 0,
        minutes=round((agg["seconds"] or 0) / 60),
        skills=agg["skills"] or 0,
        hints=agg["hints"] or 0,
    )


def activity(user, *, days: int = 28, now: datetime | None = None) -> dict:
    today = local_now(user, now or timezone.now()).date()
    start = today - timedelta(days=days - 1)
    rows = (
        LearningAttempt.objects.filter(user=user, local_date__gte=start)
        .values("local_date")
        .annotate(n=Count("id"), seconds=Sum("time_spent_seconds"))
    )
    by_day = {r["local_date"]: r for r in rows}
    labels, counts, minutes, heat = [], [], [], []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = by_day.get(day, {})
        n = row.get("n", 0)
        labels.append(day.strftime("%d %b"))
        counts.append(n)
        minutes.append(round((row.get("seconds") or 0) / 60))
        heat.append({"day": day, "count": n, "level": 0 if n == 0 else 1 if n < 2 else 2 if n < 4 else 3})
    return {
        "heat": heat,
        "active_days": sum(1 for c in counts if c),
        "chart": {
            "type": "bar",
            "labels": labels,
            "datasets": [
                {"label": "Challenges", "data": counts, "color": "accent"},
                {"label": "Minutes", "data": minutes, "color": "info", "type": "line", "axis": "y2"},
            ],
            "secondaryAxis": {"suggestedMax": 30},
        },
        "table": [{"label": lbl, "count": c, "minutes": m} for lbl, c, m in zip(labels, counts, minutes, strict=True)],
    }


def weekly_trends(user, *, weeks: int = 12, now: datetime | None = None) -> dict:
    today = local_now(user, now or timezone.now()).date()
    first = week_start(today) - timedelta(weeks=weeks - 1)
    rows = AttemptEvaluation.objects.filter(attempt__user=user, attempt__local_date__gte=first).values_list(
        "attempt__local_date", "score", "attempt__challenge__difficulty", "attempt__time_spent_seconds"
    )
    buckets: dict[date, list[tuple[float, int, int]]] = defaultdict(list)
    for day, score, difficulty, seconds in rows:
        buckets[week_start(day)].append((score, difficulty, seconds or 0))
    labels, accuracy, difficulty_avg, minutes, counts = [], [], [], [], []
    for index in range(weeks):
        start = first + timedelta(weeks=index)
        items = buckets.get(start, [])
        labels.append(start.strftime("%d %b"))
        counts.append(len(items))
        if items:
            accuracy.append(round(100 * sum(i[0] for i in items) / len(items)))
            difficulty_avg.append(round(sum(i[1] for i in items) / len(items), 2))
            minutes.append(round(sum(i[2] for i in items) / 60))
        else:
            accuracy.append(None)
            difficulty_avg.append(None)
            minutes.append(0)
    sample = sum(counts)
    return {
        "sample": sample,
        "enough": sample >= MIN_SAMPLE,
        "accuracy_chart": {
            "type": "line",
            "labels": labels,
            "percent": True,
            "suggestedMax": 100,
            "datasets": [{"label": "Average score", "data": accuracy, "color": "success", "fill": True}],
        },
        "difficulty_chart": {
            "type": "line",
            "labels": labels,
            "suggestedMax": 5,
            "datasets": [{"label": "Average difficulty", "data": difficulty_avg, "color": "warning"}],
        },
        "time_chart": {
            "type": "bar",
            "labels": labels,
            "datasets": [{"label": "Minutes practised", "data": minutes, "color": "info"}],
        },
        "table": [
            {"week": lbl, "count": c, "accuracy": a, "difficulty": d, "minutes": m}
            for lbl, c, a, d, m in zip(labels, counts, accuracy, difficulty_avg, minutes, strict=True)
        ],
    }


def skill_performance(user, *, limit: int = 10) -> list[dict]:
    rows = (
        AttemptEvaluation.objects.filter(attempt__user=user)
        .values("attempt__challenge__skill__name", "attempt__challenge__skill__slug")
        .annotate(n=Count("id"), avg=Avg("score"), passed=Count("id", filter=Q(passed=True)))
        .order_by("-n")[:limit]
    )
    return [
        {
            "name": r["attempt__challenge__skill__name"],
            "slug": r["attempt__challenge__skill__slug"],
            "attempts": r["n"],
            "avg": r["avg"] or 0,
            "passed": r["passed"],
        }
        for r in rows
    ]


def skill_chart(rows: list[dict]) -> dict:
    return {
        "type": "bar",
        "labels": [r["name"] for r in rows],
        "percent": True,
        "suggestedMax": 100,
        "datasets": [{"label": "Average score", "data": [round(r["avg"] * 100) for r in rows], "color": "accent"}],
    }


def retention(user) -> dict:
    review_attempts = AttemptEvaluation.objects.filter(attempt__user=user, attempt__is_review=True)
    total = review_attempts.count()
    passed = review_attempts.filter(passed=True).count()
    outcomes = Counter(ReviewRecord.objects.filter(attempt__user=user).values_list("outcome", flat=True))
    spaced = ReviewRecord.objects.filter(attempt__user=user, previous_interval_days__gte=3)
    spaced_total = spaced.count()
    spaced_passed = spaced.filter(outcome="success").count()
    return {
        "reviews": total,
        "passed": passed,
        "rate": passed / total if total else None,
        "spaced_total": spaced_total,
        "spaced_rate": spaced_passed / spaced_total if spaced_total else None,
        "outcomes": dict(outcomes),
        "enough": total >= MIN_SAMPLE,
    }


def error_categories(user, *, days: int = 90, now: datetime | None = None) -> dict:
    cutoff = (now or timezone.now()) - timedelta(days=days)
    counts: Counter = Counter()
    labels: dict[str, str] = {}
    codes: Counter = Counter()
    for items in (
        AttemptEvaluation.objects.filter(attempt__user=user, created_at__gte=cutoff)
        .exclude(misconceptions=[])
        .values_list("misconceptions", flat=True)
    ):
        for item in items:
            counts[item.get("category", "conceptual")] += 1
            codes[item["code"]] += 1
            labels[item["code"]] = item["label"]
    ordered = counts.most_common()
    return {
        "total": sum(counts.values()),
        "categories": [{"key": k, "label": CATEGORY_LABELS.get(k, k.title()), "count": v} for k, v in ordered],
        "top": [{"label": labels[c], "count": n} for c, n in codes.most_common(6)],
        "chart": {
            "type": "bar",
            "labels": [CATEGORY_LABELS.get(k, k.title()) for k, _ in ordered],
            "datasets": [{"label": "Mistakes", "data": [v for _, v in ordered], "color": "danger"}],
        },
    }


def completion(user) -> dict:
    counts = dict(
        Recommendation.objects.filter(user=user).values("status").annotate(n=Count("id")).values_list("status", "n")
    )
    total = sum(counts.values())
    done = counts.get(Recommendation.Status.COMPLETED, 0)
    return {
        "total": total,
        "completed": done,
        "skipped": counts.get(Recommendation.Status.SKIPPED, 0),
        "expired": counts.get(Recommendation.Status.EXPIRED, 0),
        "rate": done / total if total else None,
    }
