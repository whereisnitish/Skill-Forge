"""Markdown rendering for curated and generated learning content.

Content is converted with Python-Markdown (code highlighted server-side by
Pygments) and then sanitised with nh3, so even AI-generated or admin-entered
content cannot inject scripts or event handlers.
"""

from __future__ import annotations

from functools import lru_cache

import markdown as md
import nh3

_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "div", "em", "h2", "h3", "h4",
    "hr", "i", "kbd", "li", "ol", "p", "pre", "span", "strong", "sub", "sup", "table",
    "tbody", "td", "th", "thead", "tr", "ul",
}  # fmt: skip
_ALLOWED_ATTRIBUTES = {
    "*": {"class"},
    "a": {"href", "title"},
    "abbr": {"title"},
    "td": {"align"},
    "th": {"align"},
}


@lru_cache(maxsize=2048)
def render_markdown(text: str) -> str:
    if not text:
        return ""
    html = md.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False, "css_class": "codehilite"}},
        output_format="html",
    )
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )


def render_code(code: str, language: str = "python") -> str:
    """Highlight a standalone code block (used for buggy/starter code displays)."""
    fence = "```"
    return render_markdown(f"{fence}{language}\n{code.rstrip()}\n{fence}")
