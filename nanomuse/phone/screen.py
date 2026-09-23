"""What the agent sees of the phone: one screen, as a list of elements and a picture.

The device sends::

    {"app": "alipay", "app_name": "支付宝", "route": "/transfer/confirm",
     "width": 390, "height": 844, "keyboard": false,
     "elements": [{"id": 1, "role": "button", "text": "确认付款", "desc": "",
                   "bounds": [40, 760, 350, 808], "clickable": true, "editable": false,
                   "scrollable": false, "focused": false, "checked": null, "value": ""}],
     "screenshot": "<base64 JPEG or PNG>" | null}

Element ids are per screen (the device numbers what it reports, top to bottom); the agent
taps by id when it can, by coordinates when it must. The rendering below is what the model
reads — compact, one line per element — and the screenshot, when there is one, is saved to
the workspace and shown to models that take images.
"""

from __future__ import annotations

import base64
import binascii
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.phone.link import Device

MAX_ELEMENTS = 150
MAX_TEXT = 80
KEEP_SHOTS = 40


@dataclass
class Element:
    id: int
    role: str = "view"
    text: str = ""
    desc: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    clickable: bool = False
    editable: bool = False
    scrollable: bool = False
    focused: bool = False
    checked: bool | None = None
    value: str = ""

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def label(self) -> str:
        """The words a person would use for it: its text, else its description."""
        return (self.text or self.desc or "").strip()

    def render(self) -> str:
        flags = [
            f
            for f, on in (
                ("clickable", self.clickable),
                ("editable", self.editable),
                ("scrollable", self.scrollable),
                ("focused", self.focused),
            )
            if on
        ]
        if self.checked is not None:
            flags.append("checked" if self.checked else "unchecked")
        parts = [f"[{self.id}] {self.role}"]
        if self.text:
            parts.append(f'"{_clip(self.text)}"')
        if self.desc and self.desc != self.text:
            parts.append(f"({_clip(self.desc)})")
        if self.value:
            parts.append(f'value="{_clip(self.value)}"')
        if flags:
            parts.append("{" + ", ".join(flags) + "}")
        x, y = self.center
        parts.append(f"@({x},{y})")
        return " ".join(parts)

    @classmethod
    def from_raw(cls, raw: dict[str, Any], idx: int) -> Element:
        b = raw.get("bounds") or [0, 0, 0, 0]
        try:
            bounds = tuple(int(float(v)) for v in b[:4])
            if len(bounds) != 4:
                bounds = (0, 0, 0, 0)
        except (TypeError, ValueError):
            bounds = (0, 0, 0, 0)
        checked = raw.get("checked")
        return cls(
            id=int(raw.get("id", idx)),
            role=str(raw.get("role") or "view")[:24],
            text=str(raw.get("text") or "")[:400],
            desc=str(raw.get("desc") or "")[:200],
            bounds=bounds,  # type: ignore[arg-type]
            clickable=bool(raw.get("clickable")),
            editable=bool(raw.get("editable")),
            scrollable=bool(raw.get("scrollable")),
            focused=bool(raw.get("focused")),
            checked=None if checked is None else bool(checked),
            value=str(raw.get("value") or "")[:200],
        )


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class Screen:
    app: str = ""
    app_name: str = ""
    route: str = ""
    width: int = 0
    height: int = 0
    keyboard: bool = False
    elements: list[Element] = field(default_factory=list)
    image_path: str | None = None
    taken_at: float = field(default_factory=time.time)
    note: str = ""  # anything the device wants to add ("permission dialog open", ...)

    # ------------------------------------------------------------------ building
    @classmethod
    def from_device(
        cls, raw: dict[str, Any], device: Device | None = None, shots_dir: Path | None = None
    ) -> Screen:
        elements = []
        for i, item in enumerate((raw.get("elements") or [])[:MAX_ELEMENTS], start=1):
            if isinstance(item, dict):
                elements.append(Element.from_raw(item, i))
        screen = cls(
            app=str(raw.get("app") or "")[:80],
            app_name=str(raw.get("app_name") or "")[:80],
            route=str(raw.get("route") or raw.get("activity") or "")[:160],
            width=int(raw.get("width") or (device.width if device else 0) or 0),
            height=int(raw.get("height") or (device.height if device else 0) or 0),
            keyboard=bool(raw.get("keyboard")),
            elements=elements,
            note=str(raw.get("note") or "")[:300],
        )
        shot = raw.get("screenshot")
        if shot and shots_dir is not None:
            screen.image_path = _save_screenshot(str(shot), shots_dir)
        return screen

    # ------------------------------------------------------------------ reading
    def element(self, element_id: int) -> Element | None:
        for el in self.elements:
            if el.id == element_id:
                return el
        return None

    def texts(self) -> list[str]:
        return [t for el in self.elements for t in (el.text, el.desc, el.value) if t]

    def find_words(self, words: list[str]) -> list[str]:
        """Which of ``words`` appear on this screen (case-insensitive, substring)."""
        haystack = "\n".join(self.texts()).lower()
        return [w for w in words if w and w.lower() in haystack]

    @property
    def title(self) -> str:
        name = self.app_name or self.app or "phone"
        return (
            f"{name} ({self.app})"
            if self.app and self.app_name and self.app != self.app_name
            else name
        )

    def render(self, max_elements: int = MAX_ELEMENTS) -> str:
        head = [self.title]
        if self.route:
            head.append(self.route)
        if self.width and self.height:
            head.append(f"{self.width}×{self.height}")
        head.append("keyboard shown" if self.keyboard else "keyboard hidden")
        lines = [" · ".join(head)]
        if self.note:
            lines.append(f"note: {self.note}")
        if not self.elements:
            lines.append(
                "(no elements reported — the screen may be empty, still loading, or the device cannot read it)"
            )
        for el in self.elements[:max_elements]:
            lines.append(el.render())
        if len(self.elements) > max_elements:
            lines.append(
                f"… {len(self.elements) - max_elements} more elements (scroll to see them)"
            )
        return "\n".join(lines)

    def to_dict(self, brief: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "app": self.app,
            "app_name": self.app_name,
            "route": self.route,
            "width": self.width,
            "height": self.height,
            "keyboard": self.keyboard,
            "elements": len(self.elements),
            "image": self.image_path,
            "taken_at": self.taken_at,
        }
        if not brief:
            data["items"] = [el.render() for el in self.elements]
        return data


def _save_screenshot(encoded: str, shots_dir: Path) -> str | None:
    """Decode the device's picture into ``shots_dir`` and keep only the newest few."""
    if "," in encoded[:64] and encoded.lstrip().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        data = base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError) as exc:
        logger.debug("phone screenshot not decodable: {}", exc)
        return None
    if len(data) < 64:
        return None
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
        return None
    return str(path)


__all__ = ["Element", "Screen"]
