"""The user's address book: people from ``.vcf`` exports and links, plus the ones the
agent was told about.

Sources are files or URLs (a ``{{vault:NAME}}`` placeholder for a link that is a secret)
named in ``[connectors.contacts]`` or added from the app. They are read on start and on
request; a URL's text is cached in the data directory (mode 600) so a restart does not
need the network. The agent's own book — "Alice's new address is …" — is a 4.0 ``.vcf``
of its own in the data directory, the only source that is written to.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from openmuse.contacts.vcard import Contact, parse_vcards, render_vcard
from openmuse.logger import logger

if TYPE_CHECKING:
    from openmuse.config import ContactsSettings
    from openmuse.vault import CredentialVault

OWN = "My contacts"  # the agent's own book, as a source name
MAX_SOURCE_BYTES = 16 * 1024 * 1024
_WORD = re.compile(r"[\w@.+-]+", re.UNICODE)


@dataclass
class SourceState:
    name: str
    contacts: list[Contact] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "contacts": len(self.contacts),
            "fetched_at": datetime.fromtimestamp(self.fetched_at)
            .astimezone()
            .isoformat(timespec="seconds")
            if self.fetched_at
            else None,
            "error": self.error,
        }


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


class ContactBook:
    def __init__(
        self,
        settings: ContactsSettings,
        vault: CredentialVault | None = None,
        own_file: Path | None = None,
        cache_file: Path | None = None,
    ):
        self.settings = settings
        self.vault = vault
        self.own_file = own_file
        self.cache_file = cache_file
        self.states: dict[str, SourceState] = {}
        self._lock = asyncio.Lock()
        self._load_own()
        self._load_cache()
        self.read_files()

    # ------------------------------------------------------------------ what is where
    @property
    def configured(self) -> bool:
        """Anything to look people up in: a source, or people the agent was told about."""
        return self.settings.enabled and (bool(self.settings.sources) or bool(self.own))

    @property
    def own(self) -> list[Contact]:
        return self.states[OWN].contacts if OWN in self.states else []

    @property
    def contacts(self) -> list[Contact]:
        """Everyone, the agent's own book first, one entry per person: the same name with
        the same address in two sources is one person."""
        seen: set[str] = set()
        out: list[Contact] = []
        names = [OWN] + [s.name for s in self.settings.sources if s.name != OWN]
        for name in names:
            state = self.states.get(name)
            if state is None:
                continue
            for c in state.contacts:
                key = c.name.lower() + "|" + "|".join(sorted(c.emails_plain))
                if key in seen:
                    continue
                seen.add(key)
                out.append(c)
        return out

    def __len__(self) -> int:
        return len(self.contacts)

    def status(self) -> dict[str, Any]:
        names = [OWN] + [s.name for s in self.settings.sources if s.name != OWN]
        return {
            "configured": self.configured,
            "count": len(self),
            "sources": [
                self.states.get(n, SourceState(n)).to_dict() for n in names if n in self.states
            ],
        }

    # ------------------------------------------------------------------ reading
    def _load_own(self) -> None:
        if self.own_file is None:
            return
        state = SourceState(OWN)
        if self.own_file.exists():
            try:
                state.contacts = parse_vcards(self.own_file.read_text(encoding="utf-8"), source=OWN)
                state.fetched_at = self.own_file.stat().st_mtime
            except (OSError, ValueError) as exc:
                state.error = f"cannot read: {exc}"
        self.states[OWN] = state

    def _load_cache(self) -> None:
        if self.cache_file is None or not self.cache_file.exists():
            return
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for name, entry in raw.items():
                if name == OWN:
                    continue
                self.states[name] = SourceState(
                    name,
                    parse_vcards(entry.get("vcf", ""), source=name),
                    float(entry.get("fetched_at", 0)),
                    entry.get("error", ""),
                )
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning("contacts cache unreadable: {}", exc)

    def _save_cache(self, texts: dict[str, str]) -> None:
        if self.cache_file is None:
            return
        try:
            existing: dict[str, Any] = {}
            if self.cache_file.exists():
                existing = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for name, state in self.states.items():
                if name == OWN or self._is_file(name):
                    continue  # files are read from where they are
                entry = existing.get(name, {})
                if name in texts:
                    entry["vcf"] = texts[name]
                entry["fetched_at"] = state.fetched_at
                entry["error"] = state.error
                existing[name] = entry
            for name in list(existing):
                if name not in self.states:
                    del existing[name]
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(existing), encoding="utf-8")
            self.cache_file.chmod(0o600)  # someone's whole address book
        except OSError as exc:
            logger.warning("contacts cache not written: {}", exc)

    def _url(self, raw: str) -> str:
        url = raw
        if self.vault is not None:
            url = self.vault.resolve(raw, strict=False)
        if "{{" in url:
            raise ValueError("the link is a vault placeholder that is not set")
        return url.strip()

    def _is_file(self, name: str) -> bool:
        src = next((s for s in self.settings.sources if s.name == name), None)
        if src is None:
            return False
        try:
            return not self._url(src.url).startswith(("http://", "https://"))
        except ValueError:
            return False

    def read_files(self) -> None:
        """Read the sources that are files (cheap, no network); URLs wait for ``refresh``."""
        for src in self.settings.sources:
            if src.name == OWN:
                continue
            try:
                url = self._url(src.url)
            except ValueError as exc:
                self.states[src.name] = SourceState(src.name, error=str(exc))
                continue
            if url.startswith(("http://", "https://")):
                self.states.setdefault(src.name, SourceState(src.name))
                continue
            self.states[src.name] = self._read_file(src.name, url)
        for name in list(self.states):
            if name != OWN and not any(s.name == name for s in self.settings.sources):
                del self.states[name]

    def _read_file(self, name: str, url: str) -> SourceState:
        path = Path(url[len("file://") :] if url.startswith("file://") else url).expanduser()
        state = SourceState(name)
        try:
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError("the file is larger than 16 MB")
            state.contacts = parse_vcards(path.read_text(encoding="utf-8"), source=name)
            state.fetched_at = time.time()
        except OSError as exc:
            state.error = f"cannot read {path}: {exc.strerror or exc}"
        except ValueError as exc:
            state.error = str(exc)
        return state

    async def _fetch(self, url: str) -> str:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            async with client.stream(
                "GET", url, headers={"User-Agent": "OpenMuse contacts"}
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise ValueError("the file is larger than 16 MB")
                    chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    async def refresh(self, only: str | None = None) -> dict[str, Any]:
        """Read every source again (files and links); ``only`` for a single one."""
        async with self._lock:
            self._load_own()
            self.read_files()
            texts: dict[str, str] = {}
            for src in self.settings.sources:
                if src.name == OWN or (only and src.name != only):
                    continue
                try:
                    url = self._url(src.url)
                except ValueError as exc:
                    self.states[src.name] = SourceState(src.name, error=str(exc))
                    continue
                if not url.startswith(("http://", "https://")):
                    continue
                state = self.states.setdefault(src.name, SourceState(src.name))
                try:
                    text = await self._fetch(url)
                    contacts = parse_vcards(text, source=src.name)
                    if not contacts and "BEGIN:VCARD" not in text.upper():
                        raise ValueError("not a vCard file")
                    state.contacts = contacts
                    state.fetched_at = time.time()
                    state.error = ""
                    texts[src.name] = text
                except httpx.HTTPStatusError as exc:
                    state.error = f"HTTP {exc.response.status_code}"
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    state.error = str(exc)[:200] or type(exc).__name__
                if state.error:
                    logger.warning("contacts source {}: {}", src.name, state.error)
            self._save_cache(texts)
        return self.status()

    # ------------------------------------------------------------------ looking up
    def get(self, contact_id: str) -> Contact | None:
        return next((c for c in self.contacts if c.id == contact_id), None)

    def by_email(self, address: str) -> Contact | None:
        addr = address.strip().lower()
        if not addr:
            return None
        return next((c for c in self.contacts if addr in c.emails_plain), None)

    def search(self, query: str, limit: int = 8) -> list[Contact]:
        """People matching every word of the query — by name, nickname, company, email or
        phone; whole words first, then prefixes ('ali' finds Alice). An address or a number
        matches on its own."""
        words = _tokens(query)
        digits = _digits(query) if len(_digits(query)) >= 4 else ""
        if not words and not digits:
            return []
        scored: list[tuple[float, Contact]] = []
        for c in self.contacts:
            score = 0.0
            name_words = _tokens(c.name) + _tokens(c.nickname)
            name_words += [w for w in _tokens(c.first) + _tokens(c.last) if w not in name_words]
            org_words = _tokens(c.org) + _tokens(c.title)
            emails = c.emails_plain
            ok = True
            for w in words:
                if w in name_words:
                    score += 10
                elif any(nw.startswith(w) for nw in name_words):
                    score += 6
                elif any(w == e or w == e.split("@")[0] for e in emails):
                    score += 12
                elif any(w in e for e in emails):
                    score += 4
                elif w in org_words or any(ow.startswith(w) for ow in org_words):
                    score += 3
                elif any(w in nw for nw in name_words if len(w) >= 2):
                    score += 2  # CJK names have no spaces: '张' inside '张伟'
                elif w in _tokens(c.note):
                    score += 1
                elif digits and w.isdigit():
                    continue
                else:
                    ok = False
                    break
            if digits and any(digits in _digits(p) for p in c.phones_plain):
                score += 12
                ok = True
            if ok and score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: (-x[0], x[1].name.lower()))
        return [c for _, c in scored[:limit]]

    def render(self, contacts: list[Contact]) -> str:
        return "\n".join(c.render() for c in contacts)

    # ------------------------------------------------------------------ the agent's own book
    def add(
        self,
        name: str,
        email: str = "",
        phone: str = "",
        org: str = "",
        note: str = "",
        birthday: str = "",
    ) -> Contact:
        """Write a person to the agent's own book (or update the one with that name)."""
        if self.own_file is None:
            raise RuntimeError("the address book has no file to write to")
        name = name.strip()
        if not name:
            raise ValueError("a contact needs a name")
        if not (email.strip() or phone.strip() or org.strip() or note.strip()):
            raise ValueError("give at least an email, a phone number, a company or a note")
        own = list(self.own)
        existing = next((c for c in own if c.name.lower() == name.lower()), None)
        parts = name.split()
        contact = existing or Contact(
            id="own-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40],
            name=name,
            first=parts[0] if len(parts) > 1 else "",
            last=" ".join(parts[1:]) if len(parts) > 1 else "",
            source=OWN,
        )
        for value in (v.strip() for v in email.replace(";", ",").split(",")):
            if value and value.lower() not in contact.emails_plain:
                contact.emails.append(value)
        for value in (v.strip() for v in phone.replace(";", ",").split(",")):
            if value and _digits(value) not in [_digits(p) for p in contact.phones_plain]:
                contact.phones.append(value)
        if org.strip():
            contact.org = org.strip()
        if birthday.strip():
            contact.birthday = birthday.strip()
        if note.strip():
            contact.note = (
                (contact.note + "\n" + note.strip()).strip()
                if contact.note and note.strip() not in contact.note
                else (contact.note or note.strip())
            )
        if existing is None:
            own.append(contact)
        self._write_own(own)
        return contact

    def remove(self, contact_id: str) -> Contact | None:
        """Take a person out of the agent's own book; people from sources stay."""
        own = list(self.own)
        hit = next((c for c in own if c.id == contact_id), None)
        if hit is None:
            return None
        self._write_own([c for c in own if c.id != contact_id])
        return hit

    def _write_own(self, contacts: list[Contact]) -> None:
        assert self.own_file is not None
        self.own_file.parent.mkdir(parents=True, exist_ok=True)
        self.own_file.write_text("".join(render_vcard(c) for c in contacts), encoding="utf-8")
        self.own_file.chmod(0o600)
        self._load_own()


__all__ = ["OWN", "ContactBook", "SourceState"]
