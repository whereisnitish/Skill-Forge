"""Capture screenshots of key screens for visual review (development tool).

Usage (dev server running, demo learner created):
    python scripts/screenshots.py http://127.0.0.1:8000 ./screenshots
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PUBLIC = [
    ("home", "/"),
    ("features", "/features/"),
    ("pricing", "/pricing/"),
    ("tracks", "/tracks/"),
    ("how", "/how-it-works/"),
    ("login", "/accounts/login/"),
    ("register", "/accounts/register/"),
]
APP = [
    ("today", "/app/"),
    ("skills-map", "/app/skills/?view=map"),
    ("skills", "/app/skills/"),
    ("mastery", "/app/mastery/"),
    ("analytics", "/app/progress/"),
    ("history", "/app/history/"),
    ("goals", "/app/goals/"),
    ("reviews", "/app/reviews/"),
    ("settings", "/settings/"),
    ("mentor", "/app/mentor/"),
    ("billing", "/billing/"),
]


def main(base: str, out: Path, only: set[str] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("dark", "light"):
            for label, viewport in (
                ("desktop", {"width": 1440, "height": 900}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                context = browser.new_context(viewport=viewport, color_scheme=theme)
                context.add_cookies([{"name": "sf_theme", "value": theme, "url": base}])
                page = context.new_page()
                page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
                for name, path in PUBLIC:
                    if only and name not in only:
                        continue
                    page.goto(base + path, wait_until="networkidle")
                    page.screenshot(path=out / f"{theme}-{label}-{name}.png", full_page=True)
                page.goto(base + "/accounts/login/")
                page.fill("input[name=username]", "demo@skillforge.local")
                page.fill("input[name=password]", "skillforge-demo-2026")
                page.click("button[type=submit]")
                page.wait_for_url("**/app/")
                page.request.post(
                    base + "/settings/theme/",
                    form={"theme": theme},
                    headers={"X-CSRFToken": page.eval_on_selector("meta[name=csrf-token]", "e => e.content")},
                )
                for name, path in APP:
                    if only and name not in only:
                        continue
                    page.goto(base + path, wait_until="networkidle")
                    page.wait_for_timeout(900)  # let entrance animations and charts settle
                    page.screenshot(path=out / f"{theme}-{label}-{name}.png", full_page=True)
                context.close()
        browser.close()
    print(f"Saved screenshots to {out}")
    for error in errors:
        print("console", error)


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]), set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None)
