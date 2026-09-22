"""Watching the inbox for ``mail`` triggers: new messages since the last look, by IMAP UID.

The first look only records where the inbox ends, so connecting a mailbox never replays
a thousand old messages through the triggers. Each later look fetches what arrived since,
newest last, capped so a burst cannot start dozens of runs.
"""

from __future__ import annotations

import asyncio
import email
import email.message
import imaplib
from dataclasses import dataclass

from openmuse.config import EmailSettings
from openmuse.tools.email_tool import _body_of, _decode, scrub_email_secrets
from openmuse.vault import CredentialVault

MAX_PER_LOOK = 20
BODY_CHARS = 2000


@dataclass
class NewMail:
    uid: int
    sender: str
    subject: str
    date: str
    body: str

    @property
    def key(self) -> str:
        return f"uid:{self.uid}"

    def render(self) -> str:
        return (
            f"From: {self.sender}\nDate: {self.date}\nSubject: {self.subject}\n\n{self.body}"
        ).strip()


class MailWatcher:
    def __init__(self, settings: EmailSettings, vault: CredentialVault | None = None):
        self.settings = settings
        self.vault = vault

    @property
    def configured(self) -> bool:
        return bool(self.settings.enabled and self.settings.imap_host)

    def _creds(self) -> tuple[str, str]:
        address, password = self.settings.address, self.settings.password
        if self.vault is not None:
            address = self.vault.resolve(address, strict=False)
            password = self.vault.resolve(password, strict=False)
        if "{{" in address or "{{" in password or not address or not password:
            raise RuntimeError("email credentials are not set")
        return address, password

    async def look(self, last_uid: int) -> tuple[list[NewMail], int]:
        """Messages with UID above ``last_uid`` and the new high-water mark.

        ``last_uid == 0`` means "first look": nothing is returned, the mark is set to the
        newest UID in the inbox. Raises ``RuntimeError`` / ``OSError`` when IMAP fails.
        """
        address, password = self._creds()
        settings = self.settings

        def _look() -> tuple[list[NewMail], int]:
            with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as imap:
                imap.login(address, password)
                status, _ = imap.select("INBOX", readonly=True)
                if status != "OK":
                    raise RuntimeError("cannot open INBOX")
                status, data = imap.uid("search", "ALL")
                if status != "OK":
                    raise RuntimeError("IMAP search failed")
                uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
                newest = max(uids, default=0)
                if last_uid <= 0:
                    return [], newest
                fresh = sorted(u for u in uids if u > last_uid)[-MAX_PER_LOOK:]
                out: list[NewMail] = []
                for uid in fresh:
                    status, parts = imap.uid("fetch", str(uid), "(RFC822)")
                    if status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    msg = email.message_from_bytes(parts[0][1])
                    body = _body_of(msg)
                    if settings.scrub_secrets:
                        body = scrub_email_secrets(body)
                    if len(body) > BODY_CHARS:
                        body = body[:BODY_CHARS] + "... [truncated]"
                    out.append(
                        NewMail(
                            uid=uid,
                            sender=_decode(msg.get("From")),
                            subject=_decode(msg.get("Subject")),
                            date=str(msg.get("Date", "")),
                            body=body,
                        )
                    )
                return out, max(newest, last_uid)

        try:
            return await asyncio.to_thread(_look)
        except imaplib.IMAP4.error as exc:
            raise RuntimeError(f"IMAP error: {exc}") from exc


__all__ = ["MailWatcher", "NewMail"]
