"""Server-side layout for the interactive skill map (layered by prerequisite depth)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from apps.engine.graph import SkillGraph

NODE_W = 184
NODE_H = 52
COL_GAP = 72
ROW_GAP = 16
PAD = 16


@dataclass(frozen=True)
class MapNode:
    id: int
    slug: str
    name: str
    category: str
    x: float
    y: float
    percent: int
    level: str
    ready: bool
    measured: bool

    @property
    def bar_width(self) -> float:
        return max(0.0, (NODE_W - 24) * self.percent / 100)


@dataclass(frozen=True)
class MapEdge:
    source: int
    target: int
    d: str
    required: bool


def layout(skills, edges: list[tuple[int, int, bool]], views: dict, readiness: dict) -> dict:
    """skills: iterable of Skill; edges: (skill_id, prerequisite_id, required)."""
    by_id = {s.pk: s for s in skills}
    graph = SkillGraph.from_edges(by_id.keys(), [(a, b) for a, b, _ in edges if a in by_id and b in by_id])
    depth = graph.depth()
    columns: dict[int, list[int]] = defaultdict(list)
    for node, level in depth.items():
        columns[level].append(node)

    order: dict[int, float] = {}
    for level in sorted(columns):
        nodes = columns[level]
        if level == 0:
            nodes.sort(key=lambda n: (by_id[n].category.order, by_id[n].order, by_id[n].name))
        else:

            def barycentre(n: int) -> tuple[float, int, str]:
                parents = [order[p] for p in graph.prerequisites.get(n, ()) if p in order]
                return (sum(parents) / len(parents) if parents else 1e9, by_id[n].category.order, by_id[n].name)

            nodes.sort(key=barycentre)
        for index, node in enumerate(nodes):
            order[node] = index

    positions: dict[int, tuple[float, float]] = {}
    tallest = max((len(c) for c in columns.values()), default=0)
    total_h = tallest * (NODE_H + ROW_GAP) - ROW_GAP
    for level, nodes in columns.items():
        col_h = len(nodes) * (NODE_H + ROW_GAP) - ROW_GAP
        offset = (total_h - col_h) / 2
        for index, node in enumerate(nodes):
            positions[node] = (
                round(PAD + level * (NODE_W + COL_GAP)),
                round(PAD + offset + index * (NODE_H + ROW_GAP)),
            )

    nodes_out = []
    for node, (x, y) in positions.items():
        skill = by_id[node]
        view = views[node]
        nodes_out.append(
            MapNode(
                id=node,
                slug=skill.slug,
                name=skill.name,
                category=skill.category.name,
                x=x,
                y=y,
                percent=view.percent if view.measured else 0,
                level=str(view.level),
                ready=readiness[node],
                measured=view.measured,
            )
        )
    edges_out = []
    for skill_id, prereq_id, required in edges:
        if skill_id not in positions or prereq_id not in positions:
            continue
        sx, sy = positions[prereq_id]
        tx, ty = positions[skill_id]
        x1, y1 = sx + NODE_W, sy + NODE_H / 2
        x2, y2 = tx, ty + NODE_H / 2
        mid = (x1 + x2) / 2
        edges_out.append(
            MapEdge(
                prereq_id,
                skill_id,
                f"M{x1:.0f} {y1:.0f} C {mid:.0f} {y1:.0f}, {mid:.0f} {y2:.0f}, {x2:.0f} {y2:.0f}",
                required,
            )
        )
    width = PAD * 2 + (max(columns, default=0) + 1) * (NODE_W + COL_GAP) - COL_GAP
    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "width": int(width),
        "height": int(total_h + PAD * 2),
        "node_w": NODE_W,
        "node_h": NODE_H,
    }
