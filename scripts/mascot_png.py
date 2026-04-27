"""Rasterise the red panda: the PWA icons from web/public/icon.svg and the README cover from the
live component's idle pose. Needs the site copies first (`npm run mascot:assets` and
`npm run site:mascot` in web/) and Playwright's Chromium (`playwright install chromium`).

    python scripts/mascot_png.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _page_html(body: str, css: str = "") -> str:
    return f"<!doctype html><meta charset=utf-8><style>html,body{{margin:0;background:transparent}}{css}</style>{body}"


def main() -> None:
    icon_svg = (WEB / "public/icon.svg").read_text()
    mascot_js = (ROOT / "site/assets/mascot.js").read_text()
    moods = json.loads(re.search(r"window\.NANOMUSE_MASCOT = (\{.*\});", mascot_js, re.S).group(1))
    css = (WEB / "src/components/RedPanda.css").read_text()
    idle = moods["idle"].replace('<g class="rp-all"', '<circle cx="100" cy="100" r="100" fill="#dcebdc"></circle><g class="rp-all"', 1)
    idle = re.sub(r'width="\d+" height="\d+"', 'width="480" height="480"', idle, count=1)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in (192, 512):
            page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
            page.set_content(_page_html(re.sub(r"<svg ", f'<svg width="{size}" height="{size}" ', icon_svg, count=1)))
            page.screenshot(path=str(WEB / f"public/icon-{size}.png"), omit_background=True)
            page.close()
        page = browser.new_page(viewport={"width": 480, "height": 480}, device_scale_factor=1)
        page.set_content(_page_html(idle, css + ".rp *{animation:none!important}"))
        page.wait_for_timeout(100)
        page.screenshot(path=str(ROOT / "docs/cover.png"), omit_background=True)
        page.close()
        browser.close()
    print("wrote web/public/icon-192.png, web/public/icon-512.png, docs/cover.png")


if __name__ == "__main__":
    main()
