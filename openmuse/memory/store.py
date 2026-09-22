"""Long-term memory: small facts about the user that persist across sessions.

Stored in SQLite. Retrieval is a lightweight keyword/bigram overlap score weighted
by how rare each word is in the store (works for English and CJK without external
embeddings); when an embedding endpoint is available (``embeddings.py``) a second
ranking by meaning is fused in. Memories can always be listed and *forgotten* by the
user. Every change a tidy-up makes (see ``consolidate.py``) is logged with the text
it replaced, so it can be undone.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from array import array
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openmuse.memory.embeddings import MemoryIndex

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class MemoryItem:
    id: str
    content: str
    category: str
    created_at: str
    source: str
    updated_at: str = ""

    def render(self) -> str:
        return f"[{self.id}] ({self.category}) {self.content}"


@dataclass
class MemoryChange:
    """One entry of the tidy-up log: what was there before, what is there now."""

    id: str
    at: str
    action: str  # merge | rewrite | drop
    before: list[MemoryItem] = field(default_factory=list)
    after: MemoryItem | None = None
    reason: str = ""
    restored: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at,
            "action": self.action,
            "before": [asdict(m) for m in self.before],
            "after": asdict(self.after) if self.after else None,
            "reason": self.reason,
            "restored": self.restored,
        }


def tokenize(text: str) -> set[str]:
    """Words for latin text + character bigrams for CJK."""
    tokens = {w.lower() for w in _WORD_RE.findall(text) if len(w) > 1}
    cjk = "".join(_CJK_RE.findall(text))
    tokens.update(cjk[i : i + 2] for i in range(len(cjk) - 1))
    if len(cjk) == 1:
        tokens.add(cjk)
    return tokens


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of the two texts' tokens: 1.0 is the same words, 0.0 none shared."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
    return len(ta & tb) / len(ta | tb)


def content_hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


class MemoryStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        # recall by meaning, when an embedding endpoint is set up (see embeddings.py)
        self.index: MemoryIndex | None = None
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
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(memories)")}
        if "updated_at" not in columns:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
            )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_log (
                id TEXT PRIMARY KEY,
                at TEXT NOT NULL,
                action TEXT NOT NULL,
                before TEXT NOT NULL,
                after TEXT,
                reason TEXT NOT NULL DEFAULT '',
                restored INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        # one vector per memory and embedding model; the hash says which text it is of
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id TEXT NOT NULL,
                model TEXT NOT NULL,
                hash TEXT NOT NULL,
                vector BLOB NOT NULL,
                PRIMARY KEY (memory_id, model)
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
            created_at=_now(),
            source=source,
        )
        self._insert(item)
        self._conn.commit()
        return item

    def update(
        self, memory_id: str, content: str, category: str | None = None
    ) -> MemoryItem | None:
        """Change what a memory says (the fact moved on); keeps its id and age."""
        content = content.strip()
        if not content:
            raise ValueError("memory content is empty")
        item = self.get(memory_id)
        if item is None:
            return None
        item.content = content
        item.category = category or item.category
        item.updated_at = _now()
        self._conn.execute(
            "UPDATE memories SET content = ?, category = ?, updated_at = ? WHERE id = ?",
            (item.content, item.category, item.updated_at, item.id),
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
        """Memories that share words with ``query``, rarest shared words counting most.

        A word that is in half the memories ("likes", "the", "我") says little about
        which one is meant; a word in one memory says everything. Scores are the sum of
        ``log(N / df)`` over the shared tokens, plus a bonus when the whole query appears
        verbatim.
        """
        q_tokens = tokenize(query)
        items = self.all()
        if not q_tokens:
            return items[:limit]
        tokens = {item.id: tokenize(item.content) for item in items}
        df: dict[str, int] = {}
        for toks in tokens.values():
            for tok in toks:
                df[tok] = df.get(tok, 0) + 1
        n = max(1, len(items))
        needle = query.strip().lower()
        scored: list[tuple[float, MemoryItem]] = []
        for item in items:
            shared = q_tokens & tokens[item.id]
            score = sum(math.log((n + 1) / df[tok]) for tok in shared)
            if needle and needle in item.content.lower():
                score += math.log(n + 1) + 1.0
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda p: (-p[0], p[1].created_at))
        return [item for _, item in scored[:limit]]

    def relevant(self, context: str, limit: int = 20) -> list[MemoryItem]:
        """Memories to inject into the system prompt: matches first, then most recent."""
        items = self.all()
        if len(items) <= limit:
            return items
        return self._fill(self.search(context, limit=limit), items, limit)

    @staticmethod
    def _fill(matched: list[MemoryItem], items: list[MemoryItem], limit: int) -> list[MemoryItem]:
        seen = {m.id for m in matched}
        for item in items:
            if len(matched) >= limit:
                break
            if item.id not in seen:
                matched.append(item)
                seen.add(item.id)
        return matched

    async def search_async(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """``search`` with the meaning-based ranking fused in when an index is set up."""
        if self.index is not None:
            return await self.index.search(query, limit=limit)
        return self.search(query, limit=limit)

    async def relevant_async(self, context: str, limit: int = 20) -> list[MemoryItem]:
        """``relevant`` with the meaning-based ranking fused in when an index is set up."""
        items = self.all()
        if len(items) <= limit:
            return items
        if self.index is not None:
            return self._fill(await self.index.search(context, limit=limit), items, limit)
        return self._fill(self.search(context, limit=limit), items, limit)

    def similar(
        self, content: str, threshold: float = 0.5, limit: int = 3
    ) -> list[tuple[float, MemoryItem]]:
        """Memories that say roughly the same thing as ``content``, most alike first."""
        pairs = [(similarity(content, item.content), item) for item in self.all()]
        pairs = [(s, item) for s, item in pairs if s >= threshold]
        pairs.sort(key=lambda p: -p[0])
        return pairs[:limit]

    # ------------------------------------------------------------------ tidy-up log
    def replace(
        self,
        ids: list[str],
        content: str,
        category: str = "",
        action: str = "merge",
        reason: str = "",
    ) -> MemoryChange | None:
        """Put one memory in the place of ``ids`` and log the change.

        The new memory is added by the user if any of the old ones was; its age is the
        oldest of them, so a merged fact does not look freshly learned.
        """
        before = [m for m in (self.get(i) for i in ids) if m is not None]
        if not before or not content.strip():
            return None
        after = MemoryItem(
            id="m_" + uuid.uuid4().hex[:8],
            content=content.strip(),
            category=category or before[0].category,
            created_at=min(m.created_at for m in before),
            source="user" if any(m.source == "user" for m in before) else "agent",
            updated_at=_now(),
        )
        for m in before:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (m.id,))
        self._insert(after)
        change = self._log(action, before, after, reason)
        self._conn.commit()
        return change

    def drop(self, memory_id: str, reason: str = "") -> MemoryChange | None:
        """Forget one memory in a way that can be undone."""
        item = self.get(memory_id)
        if item is None:
            return None
        self._conn.execute("DELETE FROM memories WHERE id = ?", (item.id,))
        change = self._log("drop", [item], None, reason)
        self._conn.commit()
        return change

    def history(self, limit: int = 50) -> list[MemoryChange]:
        rows = self._conn.execute(
            "SELECT * FROM memory_log ORDER BY at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._change(r) for r in rows]

    def restore(self, change_id: str) -> MemoryChange | None:
        """Undo one logged change: the old memories come back, the new one goes."""
        row = self._conn.execute("SELECT * FROM memory_log WHERE id = ?", (change_id,)).fetchone()
        if row is None:
            return None
        change = self._change(row)
        if change.restored:
            return change
        if change.after is not None:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (change.after.id,))
        for m in change.before:
            exists = self._conn.execute(
                "SELECT 1 FROM memories WHERE id = ? OR content = ?", (m.id, m.content)
            ).fetchone()
            if exists is None:
                self._insert(m)
        self._conn.execute("UPDATE memory_log SET restored = 1 WHERE id = ?", (change.id,))
        self._conn.commit()
        change.restored = True
        return change

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM memory_meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO memory_meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ vectors
    def vectors(self, model: str) -> dict[str, tuple[str, list[float]]]:
        """Stored vectors for ``model``: memory id → (hash of the text, vector)."""
        out: dict[str, tuple[str, list[float]]] = {}
        for row in self._conn.execute(
            "SELECT memory_id, hash, vector FROM memory_vectors WHERE model = ?", (model,)
        ):
            vec = array("f")
            vec.frombytes(row["vector"])
            out[row["memory_id"]] = (row["hash"], vec.tolist())
        return out

    def put_vectors(self, model: str, entries: dict[str, tuple[str, list[float]]]) -> None:
        self._conn.executemany(
            "INSERT INTO memory_vectors (memory_id, model, hash, vector) VALUES (?,?,?,?) "
            "ON CONFLICT(memory_id, model) DO UPDATE SET hash = excluded.hash, vector = excluded.vector",
            [(mid, model, h, array("f", vec).tobytes()) for mid, (h, vec) in entries.items()],
        )
        self._conn.commit()

    def drop_vectors(self, ids: list[str], model: str | None = None) -> None:
        if not ids:
            return
        if model is None:
            self._conn.executemany(
                "DELETE FROM memory_vectors WHERE memory_id = ?", [(i,) for i in ids]
            )
        else:
            self._conn.executemany(
                "DELETE FROM memory_vectors WHERE memory_id = ? AND model = ?",
                [(i, model) for i in ids],
            )
        self._conn.commit()

    # ------------------------------------------------------------------ helpers
    def _insert(self, item: MemoryItem) -> None:
        self._conn.execute(
            "INSERT INTO memories (id, content, category, created_at, source, updated_at) VALUES (?,?,?,?,?,?)",
            (item.id, item.content, item.category, item.created_at, item.source, item.updated_at),
        )

    def _log(
        self, action: str, before: list[MemoryItem], after: MemoryItem | None, reason: str
    ) -> MemoryChange:
        change = MemoryChange(
            id="c_" + uuid.uuid4().hex[:8],
            at=_now(),
            action=action,
            before=before,
            after=after,
            reason=reason,
        )
        self._conn.execute(
            "INSERT INTO memory_log (id, at, action, before, after, reason, restored) VALUES (?,?,?,?,?,?,0)",
            (
                change.id,
                change.at,
                action,
                json.dumps([asdict(m) for m in before], ensure_ascii=False),
                json.dumps(asdict(after), ensure_ascii=False) if after else None,
                reason,
            ),
        )
        return change

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            created_at=row["created_at"],
            source=row["source"],
            updated_at=row["updated_at"] or "",
        )

    @staticmethod
    def _change(row: sqlite3.Row) -> MemoryChange:
        return MemoryChange(
            id=row["id"],
            at=row["at"],
            action=row["action"],
            before=[MemoryItem(**m) for m in json.loads(row["before"])],
            after=MemoryItem(**json.loads(row["after"])) if row["after"] else None,
            reason=row["reason"],
            restored=bool(row["restored"]),
        )


__all__ = ["MemoryChange", "MemoryItem", "MemoryStore", "content_hash", "similarity", "tokenize"]
