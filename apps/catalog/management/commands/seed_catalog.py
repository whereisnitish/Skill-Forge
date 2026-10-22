from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.content_loader import CONTENT_DIR, load_content, validate
from apps.catalog.seeding import SeedError, sync_catalog


class Command(BaseCommand):
    help = "Load the curated skill catalogue, challenges and learning paths. Safe to run repeatedly."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dir", type=Path, default=CONTENT_DIR, help="Content directory.")
        parser.add_argument("--check", action="store_true", help="Validate only; do not touch the database.")

    def handle(self, *args, **options) -> None:
        bundle = load_content(options["dir"])
        report = validate(bundle)
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING(f"warning: {warning}"))
        if not report.ok:
            for error in report.errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError(f"Content has {len(report.errors)} error(s); nothing was changed.")
        summary = f"{len(bundle.skills)} skills, {len(bundle.challenges)} challenges, {len(bundle.paths)} paths"
        if options["check"]:
            self.stdout.write(self.style.SUCCESS(f"Content is valid: {summary}."))
            return
        try:
            stats = sync_catalog(bundle)
        except SeedError as exc:
            raise CommandError(str(exc)) from exc
        details = ", ".join(f"{key}={value}" for key, value in sorted(stats.items()))
        self.stdout.write(self.style.SUCCESS(f"Catalogue synchronised ({summary}). {details}"))
