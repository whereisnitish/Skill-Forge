from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Skill, SkillPrerequisite
from apps.engine.graph import CycleError, SkillGraph


class Command(BaseCommand):
    help = "Verify the stored prerequisite graph is acyclic and print its depth profile."

    def handle(self, *args, **options) -> None:
        nodes = list(Skill.objects.values_list("slug", flat=True))
        edges = SkillPrerequisite.objects.values_list("skill__slug", "prerequisite__slug")
        graph = SkillGraph.from_edges(nodes, edges)
        try:
            depth = graph.depth()
        except CycleError as exc:
            raise CommandError(str(exc)) from exc
        layers: dict[int, list[str]] = {}
        for slug, level in depth.items():
            layers.setdefault(level, []).append(slug)
        for level in sorted(layers):
            self.stdout.write(f"depth {level}: {', '.join(sorted(layers[level]))}")
        self.stdout.write(self.style.SUCCESS(f"Skill graph OK: {len(nodes)} skills, {len(list(edges))} edges."))
