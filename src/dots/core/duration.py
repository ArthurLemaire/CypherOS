"""Parse human durations like ``15m`` / ``2h`` / ``1h30m`` into seconds."""

from __future__ import annotations

import re

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_TOKEN = re.compile(r"(\d+(?:\.\d+)?)([smhd])")


def parse_duration(value: str | int | float) -> float:
    """Return seconds for a duration string.

    >>> parse_duration("15m")
    900.0
    >>> parse_duration("1h30m")
    5400.0
    >>> parse_duration(45)
    45.0
    """
    if isinstance(value, (int, float)):
        return float(value)

    text = value.strip().lower()
    if not text:
        raise ValueError("empty duration")

    if text.isdigit():
        return float(text)

    total = 0.0
    matched = 0
    for amount, unit in _TOKEN.findall(text):
        total += float(amount) * _UNIT_SECONDS[unit]
        matched += len(amount) + len(unit)

    if matched != len(text):
        raise ValueError(f"invalid duration: {value!r}")
    return total


def format_duration(seconds: float) -> str:
    """Inverse of :func:`parse_duration`, best-effort and compact."""
    remaining = int(seconds)
    parts: list[str] = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if remaining >= size:
            parts.append(f"{remaining // size}{unit}")
            remaining %= size
    return "".join(parts) or "0s"
