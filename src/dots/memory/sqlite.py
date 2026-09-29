"""A persistent SQLite backend using FTS5 when available, LIKE otherwise."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dots.memory.base import Memory, MemoryRecord


class SqliteMemory(Memory):
    """Durable memory backed by a single SQLite file.

    Recall uses full-text search (FTS5) if the local SQLite build supports it,
    and transparently falls back to a ``LIKE`` scan otherwise.
    """

    def __init__(self, path: str | Path = ".dots/memory.db") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._fts = self._detect_fts()
        self._init_schema()

    def _detect_fts(self) -> bool:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE _fts_probe USING fts5(x)")
            self._conn.execute("DROP TABLE _fts_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
            """
        )
        if self._fts:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS records_fts "
                "USING fts5(text, content='records', content_rowid='rowid')"
            )
        self._conn.commit()

    async def remember(self, text: str, *, tags: list[str] | None = None) -> MemoryRecord:
        record = MemoryRecord(text=text, tags=tags or [])
        self._conn.execute(
            "INSERT INTO records (id, text, tags, created_at) VALUES (?, ?, ?, ?)",
            (record.id, record.text, json.dumps(record.tags), record.created_at.isoformat()),
        )
        if self._fts:
            self._conn.execute("INSERT INTO records_fts (text) VALUES (?)", (record.text,))
        self._conn.commit()
        return record

    async def recall(self, query: str, *, k: int = 5) -> list[MemoryRecord]:
        if self._fts and query.strip():
            rows = self._conn.execute(
                """
                SELECT r.* FROM records_fts f
                JOIN records r ON r.rowid = f.rowid
                WHERE records_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (query, k),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", k),
            ).fetchall()
        return [self._row(r) for r in rows]

    async def all(self) -> list[MemoryRecord]:
        rows = self._conn.execute("SELECT * FROM records ORDER BY created_at DESC").fetchall()
        return [self._row(r) for r in rows]

    async def clear(self) -> None:
        self._conn.execute("DELETE FROM records")
        if self._fts:
            self._conn.execute("DELETE FROM records_fts")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            text=row["text"],
            tags=json.loads(row["tags"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
