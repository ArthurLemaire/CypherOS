#!/usr/bin/env python3
"""Blur parts of a phone screenshot and save it as the WebP the cards use.

    python3 docs/promo/cards/redact.py ~/Downloads/nanomuse-shots/approval.png \
        --box 120,610,840,58 --box 40,1180,300,40 -o docs/promo/cards/shots/approval.webp

Each --box is x,y,w,h in pixels of the original. The region is pixelated (a 12-px mosaic) and
then softened, which reads as "hidden on purpose" rather than as a smudge, and cannot be
undone the way a light Gaussian blur can. The output is resized to --width (default 1080) and
written as lossy WebP at quality 88 — about 150 KB for a phone screenshot, small enough to
commit. Without -o the result goes to shots/<name>.webp next to this file.

    --show     also write <out>.boxes.png with the boxes outlined, to check the coordinates
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def box(spec: str) -> tuple[int, int, int, int]:
    parts = [int(v) for v in spec.split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError("a box is x,y,w,h with w and h > 0")
    return parts[0], parts[1], parts[2], parts[3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--box", type=box, action="append", default=[], metavar="x,y,w,h")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--mosaic", type=int, default=12, help="mosaic cell size in source pixels")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        print("Pillow is not installed: pip install pillow", file=sys.stderr)
        return 2

    im = Image.open(args.src).convert("RGB")
    out = args.out or HERE / "shots" / (args.src.stem + ".webp")
    out.parent.mkdir(parents=True, exist_ok=True)

    for x, y, w, h in args.box:
        region = im.crop((x, y, x + w, y + h))
        cells = (max(1, w // args.mosaic), max(1, h // args.mosaic))
        region = region.resize(cells, Image.BILINEAR).resize((w, h), Image.NEAREST)
        region = region.filter(ImageFilter.GaussianBlur(radius=args.mosaic / 3))
        im.paste(region, (x, y))

    if args.show:
        proof = im.copy()
        draw = ImageDraw.Draw(proof)
        for x, y, w, h in args.box:
            draw.rectangle((x, y, x + w, y + h), outline=(255, 0, 0), width=4)
        proof_path = out.with_suffix(".boxes.png")
        proof.save(proof_path)
        print(proof_path)

    if im.width > args.width:
        im = im.resize((args.width, round(im.height * args.width / im.width)), Image.LANCZOS)
    im.save(out, "WEBP", quality=88, method=6)
    print(f"{out} ({im.width}x{im.height}, {out.stat().st_size // 1024} KB, {len(args.box)} box(es))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
