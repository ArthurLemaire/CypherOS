"""Append-only event log — the source of truth for replay and audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventLog:
    """A tiny append-only JSONL log.

    Each entry is ``{"ts", "type", "data"}``. Because every step's inputs and
    outputs are recorded here, a run can be replayed deterministically from the
    log alone (see :meth:`Runtime.replay`).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._entries: list[dict[str, Any]] = []
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                self._entries.append(json.loads(line))

    def append(self, type_: str, data: dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": type_,
            "data": data,
        }
        self._entries.append(entry)
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    def entries(self, *, type_: str | None = None) -> list[dict[str, Any]]:
        if type_ is None:
            return list(self._entries)
        return [e for e in self._entries if e["type"] == type_]

    def __len__(self) -> int:
        return len(self._entries)
