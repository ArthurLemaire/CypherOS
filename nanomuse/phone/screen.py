"""What the agent sees of the phone: one screen, as a picture.

The device sends::

    {"app": "com.eg.android.AlipayGphone", "app_name": "支付宝",
     "width": 1080, "height": 2400, "keyboard": false,
     "screenshot": "<base64 JPEG or PNG>",
     "note": "permission dialog open"}

That is the observation: a screenshot and the little a device can always say about it
(which app, how big, is the keyboard up). The model that operates the phone looks, and taps
by coordinates, the way a person does. A device that has an accessibility tree (the Android
app) may add ``nodes`` — the elements that say or do something, each with its text, its
centre and its flags, in the same pixel space as the picture — as a **second** input: it
helps the model read small text and know a field is a password field, but it is never
required, because a real phone cannot be relied on to have one (WebViews, Flutter, games,
FLAG_SECURE) and the simulated phone has none. The screenshot is saved to the workspace,
shown to the model, and kept for the trace.
"""

from __future__ import annotations

import base64
import binascii
import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.phone.link import Device

KEEP_SHOTS = 400  # a 30-step task is 30 pictures; traces point at these files
MAX_NODES = 120  # what a device may send; more is decoration
NODE_LINES = 60  # what the model gets to read next to the picture


@dataclass
class Screen:
    app: str = ""
    app_name: str = ""
    route: str = ""  # what the device knows about where it is (a URL path, an activity)
    width: int = 0
    height: int = 0
    keyboard: bool = False
    image_path: str | None = None
    image_size: tuple[int, int] | None = None  # the picture's own pixels, if known
    taken_at: float = field(default_factory=time.time)
    note: str = ""  # anything the device wants to add ("permission dialog open", ...)
    # the accessibility tree, flattened by the device (optional): id, text/desc/hint, class,
    # cx/cy (the centre, in the picture's pixels), flags such as clickable/editable/password
    nodes: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ building
    @classmethod
    def from_device(
        cls, raw: dict[str, Any], device: Device | None = None, shots_dir: Path | None = None
    ) -> Screen:
        screen = cls(
            app=str(raw.get("app") or "")[:80],
            app_name=str(raw.get("app_name") or "")[:80],
            route=str(raw.get("route") or raw.get("activity") or "")[:160],
            width=int(raw.get("width") or (device.width if device else 0) or 0),
            height=int(raw.get("height") or (device.height if device else 0) or 0),
            keyboard=bool(raw.get("keyboard")),
            note=str(raw.get("note") or "")[:300],
        )
        shot = raw.get("screenshot") or raw.get("image")
        if shot and shots_dir is not None:
            screen.image_path, screen.image_size = _save_screenshot(str(shot), shots_dir)
        if screen.image_size and all(screen.image_size) and not (screen.width and screen.height):
            screen.width, screen.height = screen.image_size
        nodes = raw.get("nodes")
        if isinstance(nodes, list):
            screen.nodes = [_clean_node(n) for n in nodes[:MAX_NODES] if isinstance(n, dict)]
        return screen

    # ------------------------------------------------------------------ reading
    @property
    def title(self) -> str:
        name = self.app_name or self.app or "phone"
        return (
            f"{name} ({self.app})"
            if self.app and self.app_name and self.app != self.app_name
            else name
        )

    @property
    def has_image(self) -> bool:
        return bool(self.image_path)

    def render(self) -> str:
        """The words that go with the picture (and all a text-only model gets)."""
        head = [self.title]
        if self.route:
            head.append(self.route)
        if self.width and self.height:
            head.append(f"{self.width}×{self.height}")
        head.append("keyboard shown" if self.keyboard else "keyboard hidden")
        lines = [" · ".join(head)]
        if self.note:
            lines.append(f"note: {self.note}")
        if not self.image_path:
            lines.append("(the device sent no screenshot)")
        if self.nodes:
            lines.append(
                "Elements the phone reports (text · kind · centre x,y in the picture's pixels):"
            )
            lines.extend(self.node_lines())
        return "\n".join(lines)

    def node_lines(
        self, scale: tuple[float, float] | None = None, limit: int = NODE_LINES
    ) -> list[str]:
        """One line per element, the ones that say or do something first; ``scale`` maps
        the centres from the picture's pixels to another space (the operator's 999 grid)."""
        sx, sy = scale or (1.0, 1.0)
        ranked = sorted(self.nodes, key=_node_rank)
        out = []
        for n in ranked[:limit]:
            words = (
                " / ".join(str(n[k])[:60] for k in ("text", "desc", "hint") if n.get(k))
                or n.get("res")
                or ""
            )
            flags = [
                k
                for k in (
                    "clickable",
                    "editable",
                    "password",
                    "scrollable",
                    "focused",
                    "selected",
                    "disabled",
                )
                if n.get(k)
            ]
            if "checked" in n:
                flags.append("checked" if n["checked"] else "unchecked")
            kind = str(n.get("class") or "")
            where = ""
            if n.get("cx") is not None and n.get("cy") is not None:
                where = f" @ {round(float(n['cx']) * sx)},{round(float(n['cy']) * sy)}"
            out.append(
                f"- {json.dumps(words, ensure_ascii=False) if words else '(no text)'}"
                + (f" · {kind}" if kind else "")
                + (f" [{', '.join(flags)}]" if flags else "")
                + where
            )
        if len(ranked) > limit:
            out.append(f"- … and {len(ranked) - limit} more")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "app_name": self.app_name,
            "route": self.route,
            "width": self.width,
            "height": self.height,
            "keyboard": self.keyboard,
            "image": self.image_path,
            "taken_at": self.taken_at,
            "note": self.note,
            "nodes": len(self.nodes),
        }


_NODE_KEYS = (
    "id",
    "class",
    "text",
    "desc",
    "hint",
    "res",
    "cx",
    "cy",
    "box",
    "clickable",
    "long_clickable",
    "editable",
    "password",
    "checked",
    "scrollable",
    "focused",
    "selected",
    "disabled",
)


def _clean_node(raw: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {}
    for key in _NODE_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if key in ("text", "desc", "hint", "res", "class", "id"):
            node[key] = str(value)[:80]
        elif key in ("cx", "cy"):
            try:
                node[key] = int(float(value))
            except (TypeError, ValueError):
                continue
        elif key == "box":
            if isinstance(value, list) and len(value) == 4:
                try:
                    node[key] = [int(float(v)) for v in value]
                except (TypeError, ValueError):
                    continue
        else:
            node[key] = bool(value)
    return node


def _node_rank(n: dict[str, Any]) -> tuple[int, int]:
    """Fields and password fields first (the rules hinge on them), then what has words, then
    the merely clickable; top to bottom within a group."""
    if n.get("password") or n.get("editable"):
        group = 0
    elif n.get("text") or n.get("desc") or n.get("hint"):
        group = 1
    else:
        group = 2
    return group, int(n.get("cy") or 0)


def _save_screenshot(encoded: str, shots_dir: Path) -> tuple[str | None, tuple[int, int] | None]:
    """Decode the device's picture into ``shots_dir`` and keep only the newest few."""
    if "," in encoded[:64] and encoded.lstrip().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError) as exc:
        logger.debug("phone screenshot not decodable: {}", exc)
        return None, None
    if len(data) < 64:
        return None, None
    suffix = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    try:
        shots_dir.mkdir(parents=True, exist_ok=True)
        path = (
            shots_dir
            / f"phone-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}{suffix}"
        )
        path.write_bytes(data)
        old = sorted(shots_dir.glob("phone-*"), key=lambda p: p.stat().st_mtime)
        for stale in old[:-KEEP_SHOTS]:
            stale.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("could not save phone screenshot: {}", exc)
        return None, None
    return str(path), image_size(data)


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG or JPEG from its header; None when it is neither."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(w), int(h)
            i += 2 + length
    return None


__all__ = ["Screen", "image_size"]
