"""Presentation helpers shared by every template: icons, markdown, formatting."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from django import template
from django.conf import settings
from django.utils.html import escape, format_html
from django.utils.safestring import SafeString, mark_safe

from apps.core.markdown import render_code, render_markdown

register = template.Library()

ICON_DIR = Path(__file__).resolve().parent.parent / "icons"
_SVG_OPEN = re.compile(r"<svg\b[^>]*>", re.S)
_ICON_NAME = re.compile(r"^[a-z0-9\-]+$")


@lru_cache(maxsize=512)
def _icon_body(name: str) -> str:
    if not _ICON_NAME.match(name):
        raise ValueError(f"Invalid icon name {name!r}")
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        if settings.DEBUG:
            raise FileNotFoundError(f"Icon {name!r} is not vendored; run `npm run vendor`.")
        return ""
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    match = _SVG_OPEN.search(raw)
    if not match:
        return ""
    end = raw.rfind("</svg>")
    return raw[match.end() : end].strip()


@register.simple_tag
def icon(name: str, css: str = "size-5", label: str = "", stroke: str = "1.75") -> SafeString:
    """Inline a Lucide icon. Decorative unless a `label` is given."""
    body = _icon_body(name)
    a11y = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="{}" stroke-linecap="round" stroke-linejoin="round" '
        'class="icon {}" {} focusable="false">{}</svg>',
        stroke,
        css,
        a11y,
        mark_safe(body),  # noqa: S308 - vendored, trusted SVG markup
    )


@register.filter(name="markdown")
def markdown_filter(value: str) -> SafeString:
    return mark_safe(render_markdown(value or ""))  # noqa: S308 - sanitised by nh3


@register.filter
def markdown_inline(value: str) -> SafeString:
    """Markdown for short, phrasing-level text (option labels): drops a single wrapping <p>."""
    html = render_markdown(value or "").strip()
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]
    return mark_safe(html)  # noqa: S308 - sanitised by nh3


@register.filter
def codeblock(value: str, language: str = "python") -> SafeString:
    return mark_safe(render_code(value or "", language))  # noqa: S308 - sanitised by nh3


@register.filter
def percent(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.{int(digits)}f}%"


@register.filter
def pct_width(value: float | None) -> str:
    """Clamp a 0..1 value to a CSS percentage for progress bars."""
    if value is None:
        return "0%"
    return f"{max(0.0, min(1.0, float(value))) * 100:.1f}%"


@register.filter
def minutes(value: int | None) -> str:
    if not value:
        return "0 min"
    value = int(value)
    if value < 60:
        return f"{value} min"
    hours, mins = divmod(value, 60)
    return f"{hours} h {mins} min" if mins else f"{hours} h"


@register.filter
def seconds_to_minutes(value: int | None) -> int:
    return round((value or 0) / 60)


@register.filter
def humanize_code(value: str) -> str:
    """'first_success' -> 'First success'."""
    return str(value or "").replace("_", " ").capitalize()


@register.filter
def get_item(mapping: dict, key):
    if mapping is None:
        return None
    return mapping.get(key)


@register.simple_tag(takes_context=True)
def query_with(context, **kwargs) -> str:
    """Return the current query string with some parameters replaced (for pagination)."""
    request = context.get("request")
    params = request.GET.copy() if request is not None else {}
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = urlencode(list(params.lists()), doseq=True) if hasattr(params, "lists") else ""
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def nav_state(context, *names: str) -> str:
    """Return 'is-active' when the current view namespace:url_name matches any name."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    current = f"{match.namespace}:{match.url_name}"
    for name in names:
        if name.endswith(":*") and match.namespace == name[:-2]:
            return "is-active"
        if current == name:
            return "is-active"
    return ""


@register.simple_tag(takes_context=True)
def aria_current(context, *names: str) -> SafeString:
    return mark_safe('aria-current="page"') if nav_state(context, *names) else mark_safe("")


@register.inclusion_tag("components/field.html")
def form_field(field, css: str = "", show_label: bool = True, variant: str = ""):
    """Render a bound field with label, help, errors and accessible wiring."""
    from django import forms

    widget = field.field.widget
    described = []
    if field.help_text:
        described.append(f"{field.auto_id}_help")
    if field.errors:
        described.append(f"{field.auto_id}_error")
    if isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
        kind = "choices"
    elif isinstance(widget, forms.CheckboxInput):
        kind = "checkbox"
    elif isinstance(widget, forms.HiddenInput):
        kind = "hidden"
    else:
        kind = "input"
    if kind == "checkbox":
        base = "checkbox"
    elif isinstance(widget, forms.Textarea):
        base = "textarea"
    elif isinstance(widget, forms.Select):
        base = "select"
    else:
        base = "input"
    attrs = {"class": f"{base} {css}".strip()}
    if described:
        attrs["aria-describedby"] = " ".join(described)
    if field.errors:
        attrs["aria-invalid"] = "true"
    widget_html = field.as_widget(attrs=attrs) if kind != "choices" else ""
    return {
        "field": field,
        "kind": kind,
        "widget_html": widget_html,
        "show_label": show_label,
        "variant": variant,
        "describedby": " ".join(described),
    }


@register.inclusion_tag("components/difficulty.html")
def difficulty(level: int, show_label: bool = True):
    from apps.catalog.constants import DIFFICULTY_LABELS

    level = int(level or 0)
    return {
        "pips": [i <= level for i in range(1, 6)],
        "label": DIFFICULTY_LABELS.get(level, ""),
        "show_label": show_label,
    }


@register.inclusion_tag("components/mastery_ring.html")
def mastery_ring(value: float | None, size: int = 56, stroke: int = 6, label: str = ""):
    import math

    value = max(0.0, min(1.0, float(value or 0)))
    radius = (size - stroke) / 2
    circumference = 2 * math.pi * radius
    return {
        "size": size,
        "stroke": stroke,
        "radius": radius,
        "center": size / 2,
        "circumference": round(circumference, 2),
        "offset": round(circumference * (1 - value), 2),
        "percent": round(value * 100),
        "label": label,
    }


@register.filter
def initials(value: str) -> str:
    parts = [p for p in re.split(r"[\s._@-]+", value or "") if p]
    if not parts:
        return "?"
    letters = (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()
    return escape(letters)
