#!/usr/bin/env python3
"""Render cards.html to one PNG per card.

    python3 docs/promo/cards/render.py                 # -> docs/promo/cards/out/NN-slug.png
    python3 docs/promo/cards/render.py --only 1,3,9    # some of them
    python3 docs/promo/cards/render.py --scale 2       # 2484 x 3312, if a platform wants more pixels
    python3 docs/promo/cards/render.py --html docs/promo/cards/cards-en.html --out docs/promo/cards/out-en

Every card is a <section class="card" data-slug="..."> — 1242 x 1656 CSS pixels (3:4, what
小红书 shows uncropped) in cards.html, 1600 x 1000 (16:10, Product Hunt gallery / X / Reddit)
in cards-en.html; the screenshot is of that element, so the grey page around the cards
never appears. Needs Playwright with Chromium: `pip install playwright && playwright install
chromium`. Cards whose phone shot is still missing are rendered with a placeholder and listed
at the end, so the page can be checked before the shots arrive (see ../shots.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=HERE / "out", help="output directory (default: out/ next to this file)")
    ap.add_argument("--only", default="", help="comma-separated 1-based card numbers")
    ap.add_argument("--scale", type=float, default=1.0, help="device scale factor (default 1 → 1242 x 1656)")
    ap.add_argument("--html", type=Path, default=HERE / "cards.html", help="deck to render (default: cards.html; cards-en.html is the 16:10 English set)")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright && playwright install chromium", file=sys.stderr)
        return 2

    wanted = {int(n) for n in args.only.split(",") if n.strip()} if args.only else None
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1800, "height": 1800}, device_scale_factor=args.scale)
        page.goto(args.html.resolve().as_uri(), wait_until="load")
        # Give the font loader and the <img> error handlers a moment; both are synchronous after load
        # in practice, but a beat costs nothing and keeps the output identical run to run.
        page.wait_for_timeout(300)
        page.evaluate("document.fonts.ready")

        cards = page.query_selector_all("section.card")
        placeholders: list[str] = []
        for i, card in enumerate(cards, start=1):
            if wanted and i not in wanted:
                continue
            slug = card.get_attribute("data-slug") or f"card-{i}"
            missing = card.query_selector_all(".missing")
            if missing:
                placeholders.append(f"{i:02d}-{slug}: " + ", ".join(m.inner_text().replace("待截图 · ", "") for m in missing))
            path = args.out / f"{i:02d}-{slug}.png"
            card.screenshot(path=str(path), type="png")
            print(path)
        browser.close()

    if placeholders:
        print("\nrendered with placeholders (shots still missing):")
        for line in placeholders:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
