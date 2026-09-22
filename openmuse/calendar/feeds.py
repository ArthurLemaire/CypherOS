"""The user's calendars, read from ``.ics`` feeds and kept in a small cache.

A feed is a URL (the private link every calendar app hands out) or a local file. Feeds
are fetched together, at most every ``refresh_minutes``; between fetches the cache
answers, so building a prompt or drawing the Feed costs nothing. The URL may be a
``{{vault:NAME}}`` placeholder — the link *is* the secret for most providers.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from openmuse.calendar.ics import Event, Occurrence, day_bounds, expand, parse_ics
from openmuse.logger import logger

if TYPE_CHECKING:
    from openmuse.config import CalendarSettings
    from openmuse.vault import CredentialVault

MAX_FEED_BYTES = 8 * 1024 * 1024


@dataclass
class FeedState:
    name: str
    events: list[Event] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "events": len(self.events),
            "fetched_at": datetime.fromtimestamp(self.fetched_at)
            .astimezone()
            .isoformat(timespec="seconds")
            if self.fetched_at
            else None,
            "error": self.error,
        }


@dataclass
class Slot:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class CalendarFeeds:
    def __init__(
        self,
        settings: CalendarSettings,
        vault: CredentialVault | None = None,
        cache_file: Path | None = None,
        tz: tzinfo | None = None,
    ):
        self.settings = settings
        self.vault = vault
        self.cache_file = cache_file
        self.tz: tzinfo = tz or datetime.now().astimezone().tzinfo or UTC
        self.states: dict[str, FeedState] = {}
        self._lock = asyncio.Lock()
        self._load_cache()

    # ------------------------------------------------------------------ cache
    def _load_cache(self) -> None:
        if self.cache_file is None or not self.cache_file.exists():
            return
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for name, entry in raw.items():
                events = parse_ics(entry.get("ics", ""), self.tz, calendar=name)
                self.states[name] = FeedState(
                    name, events, float(entry.get("fetched_at", 0)), entry.get("error", "")
                )
        except (OSError, ValueError, AttributeError) as exc:  # a broken cache is just refetched
            logger.warning("calendar cache unreadable: {}", exc)

    def _save_cache(self, texts: dict[str, str]) -> None:
        if self.cache_file is None:
            return
        try:
            existing: dict[str, Any] = {}
            if self.cache_file.exists():
                existing = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for name, state in self.states.items():
                entry = existing.get(name, {})
                if name in texts:
                    entry["ics"] = texts[name]
                entry["fetched_at"] = state.fetched_at
                entry["error"] = state.error
                existing[name] = entry
            for name in list(existing):
                if name not in self.states:
                    del existing[name]
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(existing), encoding="utf-8")
        except OSError as exc:
            logger.warning("calendar cache not written: {}", exc)

    # ------------------------------------------------------------------ fetching
    @property
    def configured(self) -> bool:
        return self.settings.enabled and bool(self.settings.feeds)

    @property
    def fetched_at(self) -> float:
        return max((s.fetched_at for s in self.states.values()), default=0.0)

    def stale(self) -> bool:
        return time.time() - self.fetched_at > self.settings.refresh_minutes * 60

    def _url(self, raw: str) -> str:
        url = raw
        if self.vault is not None:
            url = self.vault.resolve(raw, strict=False)
        if "{{" in url:
            raise ValueError("the link is a vault placeholder that is not set")
        return url.strip()

    async def _read(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                async with client.stream(
                    "GET", url, headers={"User-Agent": "OpenMuse calendar"}
                ) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_FEED_BYTES:
                            raise ValueError("the feed is larger than 8 MB")
                        chunks.append(chunk)
                    return b"".join(chunks).decode("utf-8", errors="replace")
        if url.startswith("file://"):
            url = url[len("file://") :]
        return await asyncio.to_thread(Path(url).expanduser().read_text, "utf-8")

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        """Fetch every feed (if stale or ``force``); each feed fails on its own."""
        if not self.settings.enabled:
            return self.status()
        async with self._lock:
            if not force and not self.stale():
                return self.status()
            wanted = {f.name for f in self.settings.feeds}
            for name in list(self.states):
                if name not in wanted:
                    del self.states[name]
            texts: dict[str, str] = {}
            for feed in self.settings.feeds:
                state = self.states.setdefault(feed.name, FeedState(feed.name))
                try:
                    text = await self._read(self._url(feed.url))
                    if "BEGIN:VCALENDAR" not in text[:2000]:
                        raise ValueError("not an iCalendar file (no BEGIN:VCALENDAR)")
                    state.events = parse_ics(text, self.tz, calendar=feed.name)
                    state.error = ""
                    texts[feed.name] = text
                except (httpx.HTTPError, OSError, ValueError) as exc:
                    state.error = f"{type(exc).__name__}: {exc}"[:200]
                    logger.warning("calendar feed '{}' failed: {}", feed.name, state.error)
                state.fetched_at = time.time()
            self._save_cache(texts)
            return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.enabled,
            "feeds": [
                self.states.get(f.name, FeedState(f.name)).to_dict() for f in self.settings.feeds
            ],
            "fetched_at": datetime.fromtimestamp(self.fetched_at)
            .astimezone()
            .isoformat(timespec="seconds")
            if self.fetched_at
            else None,
            "stale": self.stale(),
        }

    # ------------------------------------------------------------------ reading
    def events(self, start: datetime, end: datetime) -> list[Occurrence]:
        """Occurrences overlapping [start, end) across every feed, sorted."""
        all_events: list[Event] = []
        for state in self.states.values():
            all_events.extend(state.events)
        return expand(all_events, start, end)

    def agenda(self, day: date, days: int = 1) -> list[Occurrence]:
        start, _ = day_bounds(day, self.tz)
        _, end = day_bounds(day + timedelta(days=days - 1), self.tz)
        return self.events(start, end)

    def search(
        self, query: str, around: date, days_back: int = 90, days_ahead: int = 180
    ) -> list[Occurrence]:
        start, _ = day_bounds(around - timedelta(days=days_back), self.tz)
        _, end = day_bounds(around + timedelta(days=days_ahead), self.tz)
        needle = query.strip().lower()
        return [
            o
            for o in self.events(start, end)
            if needle in o.summary.lower()
            or needle in o.location.lower()
            or needle in o.description.lower()
        ]

    def free_slots(
        self, day: date, min_minutes: int = 30, day_start: str = "09:00", day_end: str = "18:00"
    ) -> list[Slot]:
        """Gaps of at least ``min_minutes`` between timed events within the working hours."""
        h0, m0 = (int(p) for p in day_start.split(":"))
        h1, m1 = (int(p) for p in day_end.split(":"))
        base, _ = day_bounds(day, self.tz)
        cursor = base.replace(hour=h0, minute=m0)
        close = base.replace(hour=h1, minute=m1)
        busy = sorted(
            (o.start, o.end)
            for o in self.agenda(day)
            if not o.all_day and o.end > cursor and o.start < close
        )
        slots: list[Slot] = []
        for b_start, b_end in busy:
            if b_start - cursor >= timedelta(minutes=min_minutes):
                slots.append(Slot(cursor, min(b_start, close)))
            cursor = max(cursor, b_end)
        if close - cursor >= timedelta(minutes=min_minutes):
            slots.append(Slot(cursor, close))
        return slots

    def render(self, items: list[Occurrence], today: date | None = None) -> str:
        """The agenda as the model (and the CLI) read it: grouped by day, local times."""
        if not items:
            return "(no events)"
        today = today or datetime.now(self.tz).date()
        out: list[str] = []
        current: date | None = None
        for o in items:
            local = o.start.astimezone(self.tz)
            d = local.date()
            if d != current:
                current = d
                tag = (
                    " (today)"
                    if d == today
                    else " (tomorrow)"
                    if d == today + timedelta(days=1)
                    else ""
                )
                out.append(f"{d:%a %Y-%m-%d}{tag}")
            if o.all_day:
                span = (
                    "all day"
                    if (o.end - o.start) <= timedelta(days=1)
                    else f"all day → {(o.end - timedelta(days=1)).astimezone(self.tz):%m-%d}"
                )
            else:
                end_local = o.end.astimezone(self.tz)
                end_txt = (
                    f"{end_local:%H:%M}" if end_local.date() == d else f"{end_local:%m-%d %H:%M}"
                )
                span = f"{local:%H:%M}–{end_txt}"
            bits = [f"  {span:<14} {o.summary}"]
            if o.location:
                bits.append(f"@ {o.location}")
            if o.calendar and len(self.settings.feeds) > 1:
                bits.append(f"[{o.calendar}]")
            out.append(" ".join(bits))
        return "\n".join(out)


__all__ = ["CalendarFeeds", "FeedState", "Slot"]
