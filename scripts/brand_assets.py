"""Render the social sharing image and touch icon from HTML (development tool).

python scripts/brand_assets.py
"""

from __future__ import annotations

import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def font_data_url(name: str) -> str:
    # Inline the font: pages rendered from set_content() cannot load file:// URLs.
    data = base64.b64encode((ROOT / "static/fonts" / name).read_bytes()).decode()
    return f"data:font/woff2;base64,{data}"


SERIF = font_data_url("dm-serif-display-latin-400-normal.woff2")
SERIF_ITALIC = font_data_url("dm-serif-display-latin-400-italic.woff2")
INTER = font_data_url("inter-latin-wght-normal.woff2")
# Same mark as templates/components/logo.html: a forest-green seal with a gold
# keyline and a stepped path that ends in a gold jewel.
LOGO = """<svg viewBox="0 0 32 32" width="{s}" height="{s}">
<rect x="1" y="1" width="30" height="30" rx="8" fill="#173d32"/>
<rect x="3.25" y="3.25" width="25.5" height="25.5" rx="6" fill="none" stroke="#c4a15a" stroke-opacity=".55" stroke-width=".8"/>
<path d="M8.5 23.5h4.25v-4.25H17V15h4.25" fill="none" stroke="#d9bd7e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M22.75 7.25 25.5 10l-2.75 2.75L20 10Z" fill="#d9bd7e"/></svg>"""

OG = f"""<!doctype html><html><head><style>
@font-face {{ font-family: DMSerif; src: url({SERIF}); }}
@font-face {{ font-family: DMSerif; font-style: italic; src: url({SERIF_ITALIC}); }}
@font-face {{ font-family: IN; src: url({INTER}); }}
body {{ margin: 0; width: 1200px; height: 630px; background: #f5efe3; color: #382b24; font-family: IN, sans-serif;
  display: flex; flex-direction: column; justify-content: center; padding: 0 96px; box-sizing: border-box; position: relative; }}
body::before {{ content: ""; position: absolute; inset: 28px; border: 1px solid rgba(196,161,90,.55); border-radius: 18px; }}
.brand {{ display: flex; align-items: center; gap: 18px; font-family: DMSerif; font-size: 40px; }}
.eyebrow {{ margin: 54px 0 0; font-size: 18px; font-weight: 600; letter-spacing: .16em; text-transform: uppercase; color: #7a5b22; }}
h1 {{ font-family: DMSerif; font-weight: 400; font-size: 92px; line-height: 1.02; letter-spacing: -0.015em; margin: 18px 0 26px; }}
h1 em {{ color: #173d32; }}
p {{ font-size: 28px; color: #6a5d4f; margin: 0; max-width: 880px; }}
</style></head><body><div class="brand">{LOGO.format(s=60)}SkillForge</div>
<p class="eyebrow">Personalized learning, built around you</p>
<h1>Build skills that<br><em>actually stick.</em></h1>
<p>Adaptive daily practice for software engineers.</p></body></html>"""

ICON = f"""<!doctype html><html><body style="margin:0;width:180px;height:180px;background:#173d32;display:grid;place-items:center">
{LOGO.format(s=150)}</body></html>"""


def main() -> None:
    out = ROOT / "static/img"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(OG, wait_until="networkidle")
        page.screenshot(path=out / "og-image.png")
        page = browser.new_page(viewport={"width": 180, "height": 180})
        page.set_content(ICON)
        page.screenshot(path=out / "apple-touch-icon.png")
        browser.close()
    print("Wrote static/img/og-image.png and static/img/apple-touch-icon.png")


if __name__ == "__main__":
    main()
