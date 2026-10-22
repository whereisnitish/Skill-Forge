"""Every icon the UI can reference is vendored locally (no CDN, no silent blanks in production)."""

import re
from pathlib import Path

import yaml

from apps.catalog.constants import FORMAT_FAMILIES, GOAL_ICONS, KIND_ICONS
from apps.core.templatetags.ui import ICON_DIR
from apps.learning.services.achievements import ACHIEVEMENTS

ROOT = Path(__file__).resolve().parent.parent


def referenced_icons() -> set[str]:
    names = set(KIND_ICONS.values()) | set(GOAL_ICONS.values())
    names |= {f["icon"] for f in FORMAT_FAMILIES.values()}
    names |= {a.icon for a in ACHIEVEMENTS.values()}
    for path in (ROOT / "templates").rglob("*.html"):
        names |= set(re.findall(r'\{%\s*icon\s+"([a-z0-9-]+)"', path.read_text(encoding="utf-8")))
    for path in (ROOT / "apps/catalog/content").glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names |= {item["icon"] for key in ("categories", "paths") for item in data.get(key, []) if "icon" in item}
    return names


def test_all_referenced_icons_are_vendored():
    missing = sorted(name for name in referenced_icons() if not (ICON_DIR / f"{name}.svg").is_file())
    assert not missing, f"Run `npm run vendor`; missing icons: {missing}"


def test_essential_static_assets_are_local():
    for relative in [
        "static/vendor/htmx.min.js",
        "static/vendor/chart.umd.min.js",
        "static/js/app.js",
        "static/img/favicon.svg",
        "static/img/og-image.png",
        "static/img/apple-touch-icon.png",
        "static/fonts/inter-latin-wght-normal.woff2",
    ]:
        assert (ROOT / relative).is_file(), relative
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert "https://" not in base.split("<body")[0].replace("{{ SITE_URL }}", "")  # no CDN assets in <head>
