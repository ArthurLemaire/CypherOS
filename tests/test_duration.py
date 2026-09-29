from __future__ import annotations

import pytest

from dots.core.duration import format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("15m", 900.0),
        ("1h", 3600.0),
        ("1h30m", 5400.0),
        ("45s", 45.0),
        ("2d", 172800.0),
        ("90", 90.0),
    ],
)
def test_parse_duration(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


def test_parse_duration_numeric_passthrough() -> None:
    assert parse_duration(30) == 30.0
    assert parse_duration(2.5) == 2.5


@pytest.mark.parametrize("bad", ["", "abc", "15x", "1h30x"])
def test_parse_duration_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_format_duration_roundtrips_compactly() -> None:
    assert format_duration(5400) == "1h30m"
    assert format_duration(0) == "0s"
    assert format_duration(90) == "1m30s"
