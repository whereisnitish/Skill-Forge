"""Prerequisite readiness: may a skill be recommended yet?"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PrerequisiteEdge:
    prerequisite_id: int
    required: bool
    min_mastery: float


@dataclass(frozen=True)
class Readiness:
    ready: bool
    missing_required: tuple[int, ...] = field(default_factory=tuple)
    missing_recommended: tuple[int, ...] = field(default_factory=tuple)


def readiness(edges: Iterable[PrerequisiteEdge], mastery_mean: Callable[[int], float]) -> Readiness:
    """A skill is ready when every *required* prerequisite meets its mastery threshold.

    Recommended prerequisites never block; they are reported so selection can
    slightly prefer skills whose recommended foundations are in place.
    """
    missing_required: list[int] = []
    missing_recommended: list[int] = []
    for edge in edges:
        if mastery_mean(edge.prerequisite_id) >= edge.min_mastery:
            continue
        (missing_required if edge.required else missing_recommended).append(edge.prerequisite_id)
    return Readiness(
        ready=not missing_required,
        missing_required=tuple(sorted(missing_required)),
        missing_recommended=tuple(sorted(missing_recommended)),
    )
