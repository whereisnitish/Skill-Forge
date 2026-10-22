"""Skill prerequisite graph: validation, ordering and dependency analysis."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field


class CycleError(ValueError):
    def __init__(self, cycle: list[Hashable]):
        self.cycle = cycle
        super().__init__("Prerequisite cycle: " + " -> ".join(str(node) for node in cycle))


@dataclass
class SkillGraph:
    """Directed graph where an edge prerequisite -> skill means 'learn prerequisite first'."""

    nodes: set[Hashable] = field(default_factory=set)
    prerequisites: dict[Hashable, set[Hashable]] = field(default_factory=lambda: defaultdict(set))
    dependents: dict[Hashable, set[Hashable]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def from_edges(cls, nodes: Iterable[Hashable], edges: Iterable[tuple[Hashable, Hashable]]) -> SkillGraph:
        """Build from (skill, prerequisite) pairs."""
        graph = cls()
        graph.nodes.update(nodes)
        for skill, prerequisite in edges:
            graph.add_edge(skill, prerequisite)
        return graph

    def add_edge(self, skill: Hashable, prerequisite: Hashable) -> None:
        if skill == prerequisite:
            raise CycleError([skill, skill])
        self.nodes.update((skill, prerequisite))
        self.prerequisites[skill].add(prerequisite)
        self.dependents[prerequisite].add(skill)

    def find_cycle(self) -> list[Hashable] | None:
        """Return one cycle as a list of nodes (first == last), or None."""
        white, grey, black = 0, 1, 2
        colour = dict.fromkeys(self.nodes, white)
        parent: dict[Hashable, Hashable] = {}

        for root in sorted(self.nodes, key=str):
            if colour[root] != white:
                continue
            stack = [(root, iter(sorted(self.prerequisites.get(root, ()), key=str)))]
            colour[root] = grey
            while stack:
                node, children = stack[-1]
                advanced = False
                for child in children:
                    if colour[child] == white:
                        parent[child] = node
                        colour[child] = grey
                        stack.append((child, iter(sorted(self.prerequisites.get(child, ()), key=str))))
                        advanced = True
                        break
                    if colour[child] == grey:
                        cycle = [child, node]
                        cursor = node
                        while cursor != child:
                            cursor = parent[cursor]
                            cycle.append(cursor)
                        cycle.reverse()
                        return cycle
                if not advanced:
                    colour[node] = black
                    stack.pop()
        return None

    def validate(self) -> None:
        cycle = self.find_cycle()
        if cycle:
            raise CycleError(cycle)

    def would_create_cycle(self, skill: Hashable, prerequisite: Hashable) -> bool:
        """True if adding prerequisite -> skill would introduce a cycle."""
        # A cycle appears iff `prerequisite` already (transitively) requires `skill`.
        return skill == prerequisite or skill in self.ancestors(prerequisite)

    def ancestors(self, node: Hashable) -> set[Hashable]:
        """All transitive prerequisites of `node`."""
        return self._walk(node, self.prerequisites)

    def descendants(self, node: Hashable) -> set[Hashable]:
        """All skills that transitively depend on `node`."""
        return self._walk(node, self.dependents)

    @staticmethod
    def _walk(start: Hashable, adjacency: dict[Hashable, set[Hashable]]) -> set[Hashable]:
        seen: set[Hashable] = set()
        queue = deque(adjacency.get(start, ()))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(adjacency.get(current, ()))
        return seen

    def topological_order(self) -> list[Hashable]:
        """Prerequisites before dependents; ties broken by name for determinism."""
        self.validate()
        indegree = {node: len(self.prerequisites.get(node, ())) for node in self.nodes}
        ready = sorted((n for n, d in indegree.items() if d == 0), key=str)
        order: list[Hashable] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for dependent in sorted(self.dependents.get(node, ()), key=str):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
            ready.sort(key=str)
        return order

    def depth(self) -> dict[Hashable, int]:
        """Longest prerequisite chain length to each node (roots have depth 0)."""
        depths: dict[Hashable, int] = {}
        for node in self.topological_order():
            prereqs = self.prerequisites.get(node, ())
            depths[node] = 1 + max((depths[p] for p in prereqs), default=-1)
        return depths

    def dependency_importance(self, scope: Iterable[Hashable] | None = None) -> dict[Hashable, float]:
        """Normalised count of (in-scope) skills that depend on each node, in [0, 1].

        Foundational skills that unlock many goal skills score close to 1.
        """
        scope_set = set(scope) if scope is not None else set(self.nodes)
        counts = {node: len(self.descendants(node) & scope_set) for node in self.nodes}
        peak = max(counts.values(), default=0)
        if peak == 0:
            return dict.fromkeys(self.nodes, 0.0)
        return {node: count / peak for node, count in counts.items()}
