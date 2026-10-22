from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone


def absolute_url(path: str) -> str:
    """Turn a site path into an absolute URL for use in emails."""
    if path.startswith(("http://", "https://")):
        return path
    return settings.SITE_URL + path


def email_base_context() -> dict:
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL,
        "SUPPORT_EMAIL": settings.SUPPORT_EMAIL,
        "settings_url": absolute_url(reverse("accounts_settings:index")),
        "notification_settings_url": absolute_url(reverse("accounts_settings:index") + "#notifications"),
        "help_url": absolute_url(reverse("marketing:contact")),
        "app_url": absolute_url(reverse("learning:today")),
        "year": timezone.now().year,
    }


def render_templated_email(template_prefix: str, context: dict) -> tuple[str, str, str]:
    """Render (subject, text, html) for `emails/<prefix>_subject.txt`, `.txt` and `.html`."""
    full = {**email_base_context(), **context}
    subject = " ".join(render_to_string(f"emails/{template_prefix}_subject.txt", full).split())
    full["subject"] = subject
    text_body = render_to_string(f"emails/{template_prefix}.txt", full).strip() + "\n"
    html_body = render_to_string(f"emails/{template_prefix}.html", full)
    return subject, text_body, html_body


def send_templated_email(
    to: str,
    template_prefix: str,
    context: dict,
    *,
    headers: dict[str, str] | None = None,
    reply_to: list[str] | None = None,
    subject_prefix: str = "",
) -> None:
    """Render and send a multipart (text + HTML) email. Raises on transport errors so tasks can retry."""
    subject, text_body, html_body = render_templated_email(template_prefix, context)
    message = EmailMultiAlternatives(
        subject=subject_prefix + subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        headers=headers or {},
        reply_to=reply_to,
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
