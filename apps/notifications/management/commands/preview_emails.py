from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.emails import render_templated_email
from apps.notifications.samples import EMAILS, sample_email


class Command(BaseCommand):
    help = "Render every email template with sample data to HTML and text files for review. Sends nothing."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--out", type=Path, default=Path("email-previews"))

    def handle(self, *args, **options) -> None:
        out: Path = options["out"]
        out.mkdir(parents=True, exist_ok=True)
        index = [
            "<!doctype html><meta charset='utf-8'><title>SkillForge emails</title>",
            "<body style='font-family:system-ui;padding:24px'><h1>SkillForge emails</h1><ul>",
        ]
        for name in EMAILS:
            template, context, _ = sample_email(name)
            subject, text_body, html_body = render_templated_email(template, context)
            (out / f"{name}.html").write_text(html_body, encoding="utf-8")
            (out / f"{name}.txt").write_text(f"Subject: {subject}\n\n{text_body}", encoding="utf-8")
            index.append(f"<li><a href='{name}.html'>{name}</a> — {subject} (<a href='{name}.txt'>text</a>)</li>")
            self.stdout.write(f"{name:20} {subject}")
        (out / "index.html").write_text("".join(index) + "</ul></body>", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(EMAILS)} previews to {out.resolve()}"))
