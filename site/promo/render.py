#!/usr/bin/env python3
"""Render the promo storyboard to a video.

Every frame is a screenshot of storyboard.html at a fixed time, so the result is the same on
every machine, does not depend on the renderer keeping up, and can be re-cut by editing HTML.

    cd web && npm run site:mascot          # the mascot, icons and screenshots the page uses
    python site/promo/render.py            # -> site/media/nanomuse-promo.mp4 + poster

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`) and
ffmpeg on the PATH. Options: --fps 30 --scale 1.5 (1280×720 × 1.5 = 1080p) --out DIR.
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


async def render_frames(port: int, frames: Path, fps: int, scale: float) -> tuple[int, int]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=scale)
        page.on("pageerror", lambda e: print("page error:", e, file=sys.stderr))
        await page.goto(f"http://127.0.0.1:{port}/promo/storyboard.html", wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        duration = int(await page.evaluate("window.__duration"))
        total = duration * fps // 1000
        step = 1000 / fps
        for i in range(total):
            await page.evaluate("t => window.__render(t)", i * step)
            await page.screenshot(path=frames / f"f{i:05d}.png")
            if i % (fps * 5) == 0:
                print(f"  {i}/{total} frames ({i / fps:.0f}s)", flush=True)
        # The poster is the "it asks" moment: the approval card up, the panda waiting.
        await page.evaluate("t => window.__render(t)", 5200 + 10500)
        await page.screenshot(path=frames / "poster.png")
        await browser.close()
        return total, duration


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--scale", type=float, default=1.5, help="device scale factor; 1.5 gives 1920×1080")
    ap.add_argument("--out", type=Path, default=SITE / "media")
    ap.add_argument("--crf", type=int, default=24, help="x264 quality, lower is bigger")
    args = ap.parse_args()

    if not (SITE / "assets" / "mascot.js").exists():
        print("site/assets is missing — run `npm run site:mascot` in web/ first", file=sys.stderr)
        return 2
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    httpd, port = serve(SITE)
    try:
        with tempfile.TemporaryDirectory(prefix="nanomuse-promo-") as tmp:
            frames = Path(tmp)
            print(f"rendering at {args.fps} fps, scale {args.scale} …")
            total, duration = asyncio.run(render_frames(port, frames, args.fps, args.scale))
            mp4 = args.out / "nanomuse-promo.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-framerate", str(args.fps), "-i", str(frames / "f%05d.png"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(mp4),
                ],
                check=True,
            )
            poster = args.out / "nanomuse-promo-poster.jpg"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(frames / "poster.png"), "-q:v", "3", str(poster)],
                check=True,
            )
            print(f"{mp4}  {mp4.stat().st_size / 1e6:.1f} MB, {duration / 1000:.0f}s, {total} frames")
            print(f"{poster}  {poster.stat().st_size / 1e3:.0f} KB")
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
