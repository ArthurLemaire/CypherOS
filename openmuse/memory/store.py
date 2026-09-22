"""Long-term memory: small facts about the user that persist across sessions.

Stored in SQLite. Retrieval is a lightweight keyword/bigram overlap score (works
for English and CJK without external embeddings); memories can always be
listed and *forgotten* by the user.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass
class MemoryItem:
    id: str
    content: str
    category: str
    created_at: str
    source: str

    def render(self) -> str:
        return f"[{self.id}] ({self.category}) {self.content}"


def tokenize(text: str) -> set[str]:
    """Words for latin text + character bigrams for CJK."""
    tokens = {w.lower() for w in _WORD_RE.findall(text) if len(w) > 1}
    cjk = "".join(_CJK_RE.findall(text))
    tokens.update(cjk[i : i + 2] for i in range(len(cjk) - 1))
    if len(cjk) == 1:
        tokens.add(cjk)
    return tokens


class MemoryStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'agent'
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ CRUD
    def add(self, content: str, category: str = "general", source: str = "agent") -> MemoryItem:
        content = content.strip()
        if not content:
            raise ValueError("memory content is empty")
        # De-duplicate exact matches.
        row = self._conn.execute("SELECT * FROM memories WHERE content = ?", (content,)).fetchone()
        if row:
            return self._row(row)
        item = MemoryItem(
            id="m_" + uuid.uuid4().hex[:8],
            content=content,
            category=category or "general",
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            source=source,
        )
        self._conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?)",
            (item.id, item.content, item.category, item.created_at, item.source),
        )
        self._conn.commit()
        return item

    def get(self, memory_id: str) -> MemoryItem | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row(row) if row else None

    def all(self, limit: int = 1000) -> list[MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def forget(self, memory_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def forget_matching(self, query: str) -> int:
        cur = self._conn.execute("DELETE FROM memories WHERE content LIKE ?", (f"%{query}%",))
        self._conn.commit()
        return cur.rowcount

    def clear(self) -> int:
        cur = self._conn.execute("DELETE FROM memories")
        self._conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    # ------------------------------------------------------------------ retrieval
    def search(self, query: str, limit: int = 10) -> list[MemoryItem]:
        q_tokens = tokenize(query)
        items = self.all()
        if not q_tokens:
            return items[:limit]
        scored: list[tuple[float, MemoryItem]] = []
        for item in items:
            overlap = len(q_tokens & tokenize(item.content))
            if overlap or query.strip().lower() in item.content.lower():
                scored.append(
                    (overlap + (1.0 if query.strip().lower() in item.content.lower() else 0), item)
                )
        scored.sort(key=lambda p: (-p[0], p[1].created_at), reverse=False)
        return [item for _, item in scored[:limit]]

    def relevant(self, context: str, limit: int = 20) -> list[MemoryItem]:
        """Memories to inject into the system prompt: matches first, then most recent."""
        items = self.all()
        if len(items) <= limit:
            return items
        matched = self.search(context, limit=limit)
        seen = {m.id for m in matched}
        for item in items:
            if len(matched) >= limit:
                break
            if item.id not in seen:
                matched.append(item)
                seen.add(item.id)
        return matched

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            created_at=row["created_at"],
            source=row["source"],
        )


__all__ = ["MemoryItem", "MemoryStore", "tokenize"]
