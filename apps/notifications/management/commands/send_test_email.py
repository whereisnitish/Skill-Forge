from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.emails import send_templated_email
from apps.notifications.samples import EMAILS, recipient_note, sample_email


class Command(BaseCommand):
    help = "Send sample emails through the configured email backend to verify delivery and design."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--to", required=True, help="Recipient address (required — nothing is sent by default).")
        parser.add_argument(
            "--template",
            action="append",
            choices=[*EMAILS, "all"],
            help="Email to send; repeat for several, or 'all'. Defaults to verify_email.",
        )

    def handle(self, *args, **options) -> None:
        names = options["template"] or ["verify_email"]
        if "all" in names:
            names = EMAILS
        for name in names:
            template, context, headers = sample_email(name, email=options["to"])
            try:
                send_templated_email(options["to"], template, context, headers=headers, subject_prefix="[Test] ")
            except Exception as exc:
                raise CommandError(f"Sending {name} failed: {type(exc).__name__}: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(f"Sent {name} to {options['to']} ({recipient_note()})"))
