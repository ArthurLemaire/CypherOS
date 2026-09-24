#!/usr/bin/env python3
"""Generate the red panda chat avatar for android/ from web/src/components/redPandaShapes.ts.

The red panda is nanoMuse's face in the chat header and on notifications — never the
launcher icon (that is the one-stroke N, see gen-android-icons.py). One drawable per mood:

- drawable/nm_avatar_idle.xml      open eyes, the ω mouth
- drawable/nm_avatar_working.xml   narrowed eyes, a straight mouth — concentrating
- drawable/nm_avatar_waiting.xml   wide eyes, a small round mouth — it needs you
- drawable/nm_avatar_happy.xml     closed curved eyes, a smile, blush
- drawable/nm_avatar_error.xml     half-lidded eyes, a small frown

Geometry comes from redPandaShapes.ts (the 200×200 box); the drawables crop to HEAD_BOX so
the head fills a 148×148 viewport. Idempotent; re-run after every upstream pull.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHAPES = ROOT / "web" / "src" / "components" / "redPandaShapes.ts"
RES = ROOT / "android" / "src" / "android" / "app" / "src" / "main" / "res"

PALETTE = {
    "fur": "#D8632E",
    "furDeep": "#BF4F23",
    "cream": "#FFF4E6",
    "dark": "#2A1A14",
    "blush": "#F4A0A0",
    "white": "#FFFFFF",
}


def read_shapes() -> dict[str, object]:
    """Pull the few constants we need out of the TypeScript source.

    Regexes rather than a TS parser: the file is ours and the constants are literals. Failing
    loudly here is the point — if the web geometry changes shape, this script must be updated
    with it instead of silently drawing a different animal.
    """
    src = SHAPES.read_text(encoding="utf-8")

    def obj(name: str) -> dict[str, float]:
        match = re.search(rf"export const {name}\b[^=]*=\s*\{{([^}}]*)\}}", src)
        if not match:
            sys.exit(f"{SHAPES.name}: missing {name}")
        return {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?\d*\.?\d+)", match.group(1))}

    def path(name: str) -> str:
        match = re.search(rf"export const {name}\s*=\s*((?:\s*\"[^\"]*\"\s*\+?)+);", src)
        if not match:
            sys.exit(f"{SHAPES.name}: missing {name}")
        return "".join(re.findall(r"\"([^\"]*)\"", match.group(1)))

    def circles(name: str) -> list[dict[str, dict[str, float]]]:
        match = re.search(rf"export const {name}\b[^=]*=\s*\[(.*?)\];", src, re.S)
        if not match:
            sys.exit(f"{SHAPES.name}: missing {name}")
        out = []
        for entry in re.findall(
            r"\{\s*(\w+):\s*\{([^}]*)\},\s*(\w+):\s*\{([^}]*)\}\s*\}", match.group(1)
        ):
            out.append(
                {
                    entry[0]: {
                        k: float(v) for k, v in re.findall(r"(\w+):\s*(-?\d*\.?\d+)", entry[1])
                    },
                    entry[2]: {
                        k: float(v) for k, v in re.findall(r"(\w+):\s*(-?\d*\.?\d+)", entry[3])
                    },
                }
            )
        if not out:
            sys.exit(f"{SHAPES.name}: {name} has no entries")
        return out

    return {
        "head": obj("HEAD"),
        "head_box": obj("HEAD_BOX"),
        "ears": circles("EARS"),
        "eyes": circles("EYES"),
        "mask": path("MASK_PATH"),
        "nose": path("NOSE_PATH"),
        "mouth": path("MOUTH_FILLED_PATH"),
        "blush": re.findall(
            r"\{ cx: (-?[\d.]+), cy: (-?[\d.]+), rx: (-?[\d.]+), ry: (-?[\d.]+) \}",
            src[src.index("export const BLUSH") : src.index("];", src.index("export const BLUSH"))],
        ),
    }


def num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def ellipse(cx: float, cy: float, rx: float, ry: float) -> str:
    return f"M{num(cx - rx)} {num(cy)}a{num(rx)} {num(ry)} 0 1 1 {num(rx * 2)} 0a{num(rx)} {num(ry)} 0 1 1 {num(-rx * 2)} 0z"


def circle(cx: float, cy: float, r: float) -> str:
    return ellipse(cx, cy, r, r)


def rect(x: float, y: float, w: float, h: float) -> str:
    return f"M{num(x)} {num(y)}h{num(w)}v{num(h)}h{num(-w)}z"


def band(x0: float, y0: float, cx: float, cy_outer: float, cy_inner: float, x1: float) -> str:
    """A curved stroke drawn as a filled shape: outer curve there, inner curve back."""
    inset = (x1 - x0) * 0.15
    return (
        f"M{num(x0)} {num(y0)}Q{num(cx)} {num(cy_outer)} {num(x1)} {num(y0)}"
        f"L{num(x1 - inset)} {num(y0)}Q{num(cx)} {num(cy_inner)} {num(x0 + inset)} {num(y0)}Z"
    )


Shape = (
    "tuple[str, str]"  # (pathData, fill) — a string alias so Python 3.8 can import the module too
)


def base(s: dict[str, object]) -> list[Shape]:
    fur, deep, cream = PALETTE["fur"], PALETTE["furDeep"], PALETTE["cream"]
    out: list[Shape] = []
    for ear in s["ears"]:  # type: ignore[union-attr]
        o = ear["outer"]
        out.append((circle(o["cx"], o["cy"], o["r"]), deep))
    for ear in s["ears"]:  # type: ignore[union-attr]
        o = ear["outer"]
        out.append((circle(o["cx"], o["cy"], o["r"] - 4), fur))
    for ear in s["ears"]:  # type: ignore[union-attr]
        i = ear["inner"]
        out.append((circle(i["cx"], i["cy"], i["r"]), cream))
    head = s["head"]  # type: ignore[assignment]
    out.append((ellipse(head["cx"], head["cy"], head["rx"], head["ry"]), fur))  # type: ignore[index]
    out.append((str(s["mask"]), cream))
    return out


def eyes_open(
    s: dict[str, object], scale: float = 1.0, ry_scale: float = 1.0, dy: float = 0.0
) -> list[Shape]:
    out: list[Shape] = []
    for e in s["eyes"]:  # type: ignore[union-attr]
        eye, hi = e["eye"], e["highlight"]
        r = eye["r"] * scale
        out.append((ellipse(eye["cx"], eye["cy"] + dy, r, r * ry_scale), PALETTE["dark"]))
        hr = hi["r"] * scale * (0.85 if ry_scale < 1 else 1.0)
        out.append(
            (circle(hi["cx"], hi["cy"] + dy + (2.0 if ry_scale < 1 else 0.0), hr), PALETTE["white"])
        )
    return out


def eyes_closed_happy(s: dict[str, object]) -> list[Shape]:
    out: list[Shape] = []
    for e in s["eyes"]:  # type: ignore[union-attr]
        cx, cy = e["eye"]["cx"], e["eye"]["cy"]
        out.append((band(cx - 12, cy + 4, cx, cy - 11, cy - 3, cx + 12), PALETTE["dark"]))
    return out


def eyes_half(s: dict[str, object]) -> list[Shape]:
    out: list[Shape] = []
    for e in s["eyes"]:  # type: ignore[union-attr]
        eye = e["eye"]
        cx, cy, r = eye["cx"], eye["cy"], eye["r"]
        out.append((circle(cx, cy, r), PALETTE["dark"]))
        # The lid: cream over the upper half of the eye, flat edge just above centre.
        out.append((rect(cx - r - 1, cy - r - 1, 2 * r + 2, r - 1), PALETTE["cream"]))
        out.append((circle(cx + 4.5, cy + 4, 3.2), PALETTE["white"]))
    return out


def mouth_omega(s: dict[str, object]) -> list[Shape]:
    return [(str(s["mouth"]), PALETTE["dark"])]


def mouth_flat() -> list[Shape]:
    return [
        (rect(98.4, 138.5, 3.2, 3.5), PALETTE["dark"]),
        (rect(93, 142, 14, 3.2), PALETTE["dark"]),
    ]


def mouth_o() -> list[Shape]:
    return [(circle(100, 143.5, 3.8), PALETTE["dark"])]


def mouth_smile() -> list[Shape]:
    return [
        (rect(98.4, 138.5, 3.2, 3), PALETTE["dark"]),
        (band(88, 141, 100, 153, 146, 112), PALETTE["dark"]),
    ]


def mouth_frown() -> list[Shape]:
    return [
        (rect(98.4, 138.5, 3.2, 3), PALETTE["dark"]),
        (band(92, 147, 100, 141, 144.5, 108), PALETTE["dark"]),
    ]


def blush(s: dict[str, object]) -> list[Shape]:
    return [
        (ellipse(float(cx), float(cy), float(rx), float(ry)), PALETTE["blush"])
        for cx, cy, rx, ry in s["blush"]
    ]  # type: ignore[union-attr]


def moods(s: dict[str, object]) -> dict[str, list[Shape]]:
    return {
        "idle": base(s) + eyes_open(s) + [(str(s["nose"]), PALETTE["dark"])] + mouth_omega(s),
        "working": base(s)
        + eyes_open(s, ry_scale=0.72, dy=2)
        + [(str(s["nose"]), PALETTE["dark"])]
        + mouth_flat(),
        "waiting": base(s)
        + eyes_open(s, scale=1.1)
        + [(str(s["nose"]), PALETTE["dark"])]
        + mouth_o(),
        "happy": base(s)
        + blush(s)
        + eyes_closed_happy(s)
        + [(str(s["nose"]), PALETTE["dark"])]
        + mouth_smile(),
        "error": base(s) + eyes_half(s) + [(str(s["nose"]), PALETTE["dark"])] + mouth_frown(),
    }


def vector(shapes: list[Shape], box: dict[str, float], mood: str) -> str:
    size = max(box["width"], box["height"])
    tx = -(box["x"] - (size - box["width"]) / 2)
    ty = -(box["y"] - (size - box["height"]) / 2)
    paths = "\n".join(
        f'        <path android:fillColor="{fill}" android:pathData="{d}"/>' for d, fill in shapes
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- nanoMuse: the red panda, {mood}. Generated by scripts/gen-avatar.py from
     web/src/components/redPandaShapes.ts; do not edit by hand. -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="48dp" android:height="48dp"
    android:viewportWidth="{num(size)}" android:viewportHeight="{num(size)}">
    <group android:translateX="{num(tx)}" android:translateY="{num(ty)}">
{paths}
    </group>
</vector>
"""


def main() -> None:
    shapes = read_shapes()
    box = shapes["head_box"]  # type: ignore[assignment]
    drawable = RES / "drawable"
    drawable.mkdir(parents=True, exist_ok=True)
    for mood, parts in moods(shapes).items():
        target = drawable / f"nm_avatar_{mood}.xml"
        target.write_text(vector(parts, box, mood), encoding="utf-8")  # type: ignore[arg-type]
        print("wrote", target.relative_to(ROOT))


if __name__ == "__main__":
    main()
