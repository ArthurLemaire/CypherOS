"""What the agent sees of the phone: one screen, as a picture.

The device sends::

    {"app": "com.eg.android.AlipayGphone", "app_name": "支付宝",
     "width": 1080, "height": 2400, "keyboard": false,
     "screenshot": "<base64 JPEG or PNG>",
     "note": "permission dialog open"}

That is the whole observation: a screenshot and the little a device can always say about
it (which app, how big, is the keyboard up). Nothing is read from an accessibility tree —
a real phone does not reliably offer one (WebViews, Flutter, games, FLAG_SECURE), and the
simulated phone has none — so the model that operates the phone looks, and taps by
coordinates, the way a person does. The screenshot is saved to the workspace, shown to the
model, and kept for the trace.
"""

from __future__ import annotations

import base64
import binascii
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.phone.link import Device

KEEP_SHOTS = 400  # a 30-step task is 30 pictures; traces point at these files


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
        return "\n".join(lines)

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
        }


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
