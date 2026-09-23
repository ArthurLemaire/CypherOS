"""Trial credentials: a first million tokens for every new phone, on us.

The nanoMuse app on a phone has no model of its own to start with. It asks this gateway for a
*trial*: ``POST /api/trial`` with the device's id gives back a key and a model address —
``https://<site>/llm/trial/<id>/main`` — that the app puts straight into its ``[llm]`` and
``[gui]`` settings. Calls made with it pass through the same proxy the demo sessions use, the
same upstream key goes on, and every token is counted against the trial's lifetime budget.
When that is spent the proxy answers 429 ``trial_exhausted`` and the app tells the user to bring
their own key.

One device, one trial: asking again with the same device id rotates the key and keeps the count
(a reinstalled app recovers without a second million). New trials are capped per address and
per day; the whole thing has a switch. Everything lives in one SQLite file so a restart of the
gateway forgets nothing.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from .config import Lane, Settings
from .sessions import CST, Refused, _day_key  # noqa: PLC2701 — one module's helpers, shared

log = logging.getLogger("showcase.trials")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id          TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL,
    device      TEXT NOT NULL UNIQUE,
    ip          TEXT NOT NULL,
    created_at  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    requests    INTEGER NOT NULL DEFAULT 0,
    tokens      INTEGER NOT NULL DEFAULT 0,
    token_limit INTEGER NOT NULL,
    disabled    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS trials_ip_created ON trials (ip, created_at);
CREATE INDEX IF NOT EXISTS trials_created ON trials (created_at);
CREATE TABLE IF NOT EXISTS trial_days (
    day      TEXT PRIMARY KEY,
    requests INTEGER NOT NULL DEFAULT 0,
    tokens   INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class Trial:
    id: str
    device: str
    ip: str
    created_at: float
    last_seen: float
    requests: int
    tokens: int
    token_limit: int
    disabled: bool

    @property
    def remaining(self) -> int:
        return max(0, self.token_limit - self.tokens)

    def public(self, settings: Settings, key: str | None = None) -> dict:
        out: dict = {
            "id": self.id,
            "model": settings.main.model,
            "base_url": settings.trial_base_url(self.id),
            "gui_base_url": settings.trial_base_url(self.id, "gui"),
            "tokens_limit": self.token_limit,
            "tokens_used": self.tokens,
            "tokens_remaining": self.remaining,
            "requests": self.requests,
            "created_at": int(self.created_at),
            "exhausted": self.remaining == 0,
            "disabled": self.disabled,
        }
        if key is not None:
            out["key"] = key
        return out


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _new_key() -> str:
    return "nmt_" + secrets.token_urlsafe(30)


def _new_id() -> str:
    return secrets.token_hex(8)


class TrialStore:
    """The SQLite file. Small, synchronous calls; one connection behind a lock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> Trial:
        return Trial(
            id=row["id"],
            device=row["device"],
            ip=row["ip"],
            created_at=row["created_at"],
            last_seen=row["last_seen"],
            requests=row["requests"],
            tokens=row["tokens"],
            token_limit=row["token_limit"],
            disabled=bool(row["disabled"]),
        )

    def get(self, trial_id: str) -> tuple[Trial, str] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
        return (self._row(row), row["key_hash"]) if row else None

    def by_device(self, device: str) -> Trial | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM trials WHERE device = ?", (device,)).fetchone()
        return self._row(row) if row else None

    def insert(self, trial: Trial, key: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO trials (id, key_hash, device, ip, created_at, last_seen, requests,"
                " tokens, token_limit, disabled) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    trial.id,
                    _hash(key),
                    trial.device,
                    trial.ip,
                    trial.created_at,
                    trial.last_seen,
                    trial.requests,
                    trial.tokens,
                    trial.token_limit,
                    int(trial.disabled),
                ),
            )

    def rotate_key(self, trial_id: str, key: str, now: float) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE trials SET key_hash = ?, last_seen = ? WHERE id = ?",
                (_hash(key), now, trial_id),
            )

    def record(self, trial_id: str, tokens: int, now: float) -> None:
        day = _day_key(now)
        with self._lock:
            self._db.execute(
                "UPDATE trials SET requests = requests + 1, tokens = tokens + ?, last_seen = ?"
                " WHERE id = ?",
                (tokens, now, trial_id),
            )
            self._db.execute(
                "INSERT INTO trial_days (day, requests, tokens) VALUES (?, 1, ?)"
                " ON CONFLICT(day) DO UPDATE SET requests = requests + 1, tokens = tokens + ?",
                (day, tokens, tokens),
            )

    def issued_since(self, since: float, ip: str | None = None) -> int:
        """Trials created at or after ``since`` — from one address, or from everyone."""
        with self._lock:
            if ip is None:
                row = self._db.execute(
                    "SELECT COUNT(*) FROM trials WHERE created_at >= ?", (since,)
                ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT COUNT(*) FROM trials WHERE created_at > ? AND ip = ?", (since, ip)
                ).fetchone()
        return int(row[0])

    def total(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM trials").fetchone()[0])

    def day(self, day: str) -> tuple[int, int]:
        with self._lock:
            row = self._db.execute(
                "SELECT requests, tokens FROM trial_days WHERE day = ?", (day,)
            ).fetchone()
        return (int(row["requests"]), int(row["tokens"])) if row else (0, 0)


class TrialManager:
    def __init__(self, settings: Settings, store: TrialStore, clock=time.time) -> None:
        self.s = settings
        self.store = store
        self.clock = clock
        self._recent: dict[str, deque[float]] = defaultdict(
            deque
        )  # requests per trial, last minute

    # ------------------------------------------------------------------ issuing
    def _day_start(self, now: float) -> float:
        from datetime import datetime

        today = datetime.fromtimestamp(now, CST).replace(hour=0, minute=0, second=0, microsecond=0)
        return today.timestamp()

    def issue(self, device: str, ip: str) -> tuple[Trial, str]:
        """A trial for this device: new, or the existing one with a fresh key."""
        if not self.s.trial_enabled:
            raise Refused(404, "trial_off", "Free trial credentials are not offered here.")
        if not self.s.main.configured:
            raise Refused(503, "no_model", "This gateway has no model configured for trials.")
        now = self.clock()
        existing = self.store.by_device(device)
        if existing is not None:
            if existing.disabled:
                raise Refused(403, "trial_disabled", "This trial has been switched off.")
            key = _new_key()
            self.store.rotate_key(existing.id, key, now)
            existing.last_seen = now
            log.info("trial %s: key rotated for device %s…", existing.id, device[:8])
            return existing, key
        if self.store.issued_since(now - 86400, ip) >= self.s.trial_per_ip_daily:
            raise Refused(
                429, "trial_ip_limit", "That is all the trial credentials for today from here."
            )
        if self.store.issued_since(self._day_start(now)) >= self.s.trial_daily_new:
            raise Refused(
                429,
                "trial_daily_limit",
                "Today's trial credentials are all given out. Come back tomorrow, or bring your own key.",
            )
        key = _new_key()
        trial = Trial(
            id=_new_id(),
            device=device,
            ip=ip,
            created_at=now,
            last_seen=now,
            requests=0,
            tokens=0,
            token_limit=self.s.trial_tokens,
            disabled=False,
        )
        self.store.insert(trial, key)
        log.info("trial %s issued to %s (device %s…)", trial.id, ip, device[:8])
        return trial, key

    # ------------------------------------------------------------------ using
    def authenticate(self, trial_id: str, key: str | None) -> Trial:
        found = self.store.get(trial_id)
        if found is None or not key or not secrets.compare_digest(_hash(key), found[1]):
            raise Refused(401, "bad_key", "invalid api key")
        return found[0]

    def lane(self, trial: Trial, name: str) -> Lane:
        """The upstream a trial's model call goes to — after the budget check."""
        if trial.disabled:
            raise Refused(403, "trial_disabled", "This trial has been switched off.")
        upstream = self.s.lane(name)
        if upstream is None or not upstream.configured:
            raise Refused(404, "no_lane", f"no model lane '{name}'")
        if trial.tokens >= trial.token_limit:
            raise Refused(
                429,
                "trial_exhausted",
                f"The free trial's {trial.token_limit:,} tokens are used up. Put your own model key"
                " into Settings to keep going.",
            )
        now = self.clock()
        recent = self._recent[trial.id]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= self.s.trial_rpm:
            raise Refused(429, "trial_rate", "Too many requests in a minute; wait a little.")
        _, day_tokens = self.store.day(_day_key(now))
        if day_tokens >= self.s.trial_daily_tokens:
            raise Refused(
                429,
                "trial_daily_budget",
                "The trial pool has spent today's model budget. Come back tomorrow, or bring your own key.",
            )
        recent.append(now)
        return upstream

    def record(self, trial: Trial, tokens: int) -> None:
        self.store.record(trial.id, tokens, self.clock())

    def stats(self) -> dict:
        now = self.clock()
        requests, tokens = self.store.day(_day_key(now))
        return {
            "enabled": self.s.trial_enabled,
            "tokens": self.s.trial_tokens,
            "issued_total": self.store.total(),
            "issued_today": self.store.issued_since(self._day_start(now)),
            "daily_new": self.s.trial_daily_new,
            "day_requests": requests,
            "day_tokens": tokens,
        }
