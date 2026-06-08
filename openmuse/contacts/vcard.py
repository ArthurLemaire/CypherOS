"""vCard reading and writing — enough of RFC 6350 (4.0), RFC 2426 (3.0) and the 2.1 files
old phones export for the address books people actually have.

Google Contacts, iCloud, Outlook, Fastmail, Nextcloud and Android all export ``.vcf``.
What is read: names (``FN``, ``N``, ``NICKNAME``), emails and phones with their types,
``ORG``, ``TITLE``, ``BDAY``, ``ADR``, ``URL``, ``NOTE``, ``UID``, and Apple's ``item1.``
property groups. What is written (for the agent's own book): 4.0, minimal.
"""

from __future__ import annotations

import hashlib
import quopri
import re
from dataclasses import dataclass, field
from typing import Any

_FOLD = re.compile(r"\r?\n[ \t]")
_LINE = re.compile(
    r"^(?:(?P<group>[A-Za-z0-9-]+)\.)?(?P<name>[A-Za-z0-9-]+)(?P<params>(?:;[^:]*)?):(?P<value>.*)$"
)


@dataclass
class Contact:
    id: str
    name: str
    first: str = ""
    last: str = ""
    nickname: str = ""
    emails: list[str] = field(default_factory=list)  # "alice@example.com" or "alice@… (work)"
    phones: list[str] = field(default_factory=list)
    org: str = ""
    title: str = ""
    birthday: str = ""
    addresses: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    note: str = ""
    source: str = ""

    @property
    def addresses_plain(self) -> list[str]:
        return [_plain(a) for a in self.addresses]

    @property
    def emails_plain(self) -> list[str]:
        """Just the addresses, lower-case, without the type labels."""
        return [_plain(e).lower() for e in self.emails]

    @property
    def phones_plain(self) -> list[str]:
        return [_plain(p) for p in self.phones]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "first": self.first,
            "last": self.last,
            "nickname": self.nickname,
            "emails": self.emails,
            "phones": self.phones,
            "org": self.org,
            "title": self.title,
            "birthday": self.birthday,
            "addresses": self.addresses,
            "urls": self.urls,
            "note": self.note,
            "source": self.source,
        }

    def render(self) -> str:
        """One contact for the model: a header line and one line per field that is set."""
        head = self.name
        if self.nickname and self.nickname.lower() != self.name.lower():
            head += f" ({self.nickname})"
        if self.org:
            head += f" — {self.title + ', ' if self.title else ''}{self.org}"
        lines = [f"{head}  [{self.id}]"]
        if self.emails:
            lines.append("  email: " + ", ".join(self.emails))
        if self.phones:
            lines.append("  phone: " + ", ".join(self.phones))
        if self.birthday:
            lines.append(f"  birthday: {self.birthday}")
        for a in self.addresses:
            lines.append(f"  address: {a}")
        for u in self.urls:
            lines.append(f"  url: {u}")
        if self.note:
            lines.append("  note: " + self.note.replace("\n", " ")[:300])
        return "\n".join(lines)


def _plain(value: str) -> str:
    """'alice@example.com (work)' → 'alice@example.com'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()


def _unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split(value: str, sep: str) -> list[str]:
    """Split on an unescaped separator (``\\;`` inside a component stays)."""
    parts: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            cur.append(value[i : i + 2])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _params(raw: str) -> dict[str, list[str]]:
    """';TYPE=work,pref;X=1' (or 2.1's bare ';WORK;PREF') → {'TYPE': ['work','pref'], ...}."""
    out: dict[str, list[str]] = {}
    for part in raw.split(";"):
        if not part:
            continue
        if "=" in part:
            key, _, val = part.partition("=")
            values = [v.strip().strip('"').lower() for v in val.split(",") if v.strip()]
        else:
            key, values = "TYPE", [part.strip().lower()]  # vCard 2.1 style
        out.setdefault(key.upper(), []).extend(values)
    return out


def _label(params: dict[str, list[str]]) -> str:
    """A short type for a phone or email: 'work', 'home', 'mobile'. 'pref' and 'internet'
    say nothing about what it is."""
    kinds = [
        t
        for t in params.get("TYPE", [])
        if t not in ("pref", "internet", "voice", "x-mobile", "other")
    ]
    if "cell" in kinds:
        kinds = ["mobile" if k == "cell" else k for k in kinds]
    return kinds[0] if kinds else ""


def _with_label(value: str, params: dict[str, list[str]]) -> str:
    label = _label(params)
    return f"{value} ({label})" if label else value


def _decode(value: str, params: dict[str, list[str]]) -> str:
    if "quoted-printable" in [e.lower() for e in params.get("ENCODING", [])]:
        charset = (params.get("CHARSET") or ["utf-8"])[0]
        try:
            return quopri.decodestring(value.encode("latin-1")).decode(charset, errors="replace")
        except (LookupError, ValueError):
            return value
    return value


def _birthday(value: str) -> str:
    v = value.strip()
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?", v)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.fullmatch(r"--(\d{2})-?(\d{2})", v)  # 4.0: a birthday without a year
    if m:
        return f"--{m.group(1)}-{m.group(2)}"
    return v


def parse_vcards(text: str, source: str = "") -> list[Contact]:
    """Every vCard in ``text``. Cards without a name and without an email or phone are
    skipped (some exports contain empty cards)."""
    unfolded = _FOLD.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    # 2.1 quoted-printable soft line breaks: '=' at the end of a line continues it
    unfolded = re.sub(r"=\n(?=[^\n])", "", unfolded)
    contacts: list[Contact] = []
    card: list[str] | None = None
    for line in unfolded.split("\n"):
        upper = line.strip().upper()
        if upper == "BEGIN:VCARD":
            card = []
        elif upper == "END:VCARD":
            if card is not None:
                c = _card(card, source)
                if c is not None:
                    contacts.append(c)
            card = None
        elif card is not None and line.strip():
            card.append(line)
    return contacts


def _card(lines: list[str], source: str) -> Contact | None:
    fn = ""
    n: list[str] = []
    nick = ""
    emails: list[tuple[str, bool]] = []  # (labelled value, preferred)
    phones: list[tuple[str, bool]] = []
    org = title = bday = note = uid = ""
    addresses: list[str] = []
    urls: list[str] = []
    labels: dict[str, str] = {}  # Apple: item1.X-ABLabel → a custom label for item1.*
    grouped: list[tuple[str, str, int]] = []  # (group, kind, index) to relabel later
    for line in lines:
        m = _LINE.match(line)
        if not m:
            continue
        name = m.group("name").upper()
        params = _params(m.group("params") or "")
        value = _decode(m.group("value"), params).strip()
        group = (m.group("group") or "").lower()
        if not value:
            continue
        pref = "pref" in params.get("TYPE", []) or params.get("PREF") == ["1"]
        if name == "FN":
            fn = _unescape(value)
        elif name == "N":
            n = [_unescape(p).strip() for p in _split(value, ";")]
        elif name == "NICKNAME":
            nick = _unescape(_split(value, ",")[0]).strip()
        elif name == "EMAIL":
            emails.append((_with_label(_unescape(value), params), pref))
            if group:
                grouped.append((group, "email", len(emails) - 1))
        elif name == "TEL":
            v = _unescape(value)
            v = v[4:] if v.lower().startswith("tel:") else v  # 4.0 URIs
            phones.append((_with_label(v, params), pref))
            if group:
                grouped.append((group, "phone", len(phones) - 1))
        elif name == "ORG":
            org = ", ".join(p for p in (_unescape(x).strip() for x in _split(value, ";")) if p)
        elif name == "TITLE":
            title = _unescape(value)
        elif name == "BDAY":
            bday = _birthday(value)
        elif name == "ADR":
            parts = [_unescape(p).strip() for p in _split(value, ";")]
            # po box; extended; street; city; region; postal code; country
            addr = ", ".join(p for p in parts[1:] if p)
            if addr:
                addresses.append(_with_label(addr, params))
        elif name == "URL":
            urls.append(_unescape(value))
        elif name == "NOTE":
            note = (note + "\n" if note else "") + _unescape(value)
        elif name == "UID":
            uid = value
        elif name == "X-ABLABEL" and group:
            labels[group] = re.sub(r"^_\$!<|>!\$_$", "", _unescape(value)).lower()
    for group, kind, idx in grouped:  # Apple exports the label on a sibling line
        label = labels.get(group)
        if not label:
            continue
        seq = emails if kind == "email" else phones
        value, pref = seq[idx]
        seq[idx] = (f"{_plain(value)} ({label})", pref)

    first = n[1] if len(n) > 1 else ""
    last = n[0] if n else ""
    if not fn:
        fn = " ".join(p for p in (first, last) if p) or nick
    if not fn and not emails and not phones:
        return None
    if not fn:
        fn = _plain(emails[0][0]) if emails else _plain(phones[0][0])
    sort_pref = lambda items: [v for v, _ in sorted(items, key=lambda x: not x[1])]  # noqa: E731
    email_values = sort_pref(emails)
    phone_values = sort_pref(phones)
    ident = (
        uid
        or hashlib.sha1(
            (fn.lower() + "|" + "|".join(_plain(e).lower() for e in email_values)).encode()
        ).hexdigest()[:12]
    )
    return Contact(
        id=re.sub(r"[^A-Za-z0-9._:@-]", "", ident)[:64]
        or hashlib.sha1(fn.encode()).hexdigest()[:12],
        name=fn,
        first=first,
        last=last,
        nickname=nick,
        emails=email_values,
        phones=phone_values,
        org=org,
        title=title,
        birthday=bday,
        addresses=addresses,
        urls=urls,
        note=note.strip(),
        source=source,
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def render_vcard(contact: Contact) -> str:
    """A 4.0 card for the agent's own book. Labels in parentheses become TYPE params."""
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"UID:{contact.id}", f"FN:{_escape(contact.name)}"]
    if contact.first or contact.last:
        lines.append(f"N:{_escape(contact.last)};{_escape(contact.first)};;;")
    if contact.nickname:
        lines.append(f"NICKNAME:{_escape(contact.nickname)}")
    for kind, values in (("EMAIL", contact.emails), ("TEL", contact.phones)):
        for v in values:
            m = re.search(r"\(([^)]*)\)\s*$", v)
            params = f";TYPE={m.group(1)}" if m else ""
            lines.append(f"{kind}{params}:{_escape(_plain(v))}")
    if contact.org:
        lines.append(f"ORG:{_escape(contact.org)}")
    if contact.title:
        lines.append(f"TITLE:{_escape(contact.title)}")
    if contact.birthday:
        lines.append(f"BDAY:{contact.birthday}")
    for a in contact.addresses:
        lines.append(f"ADR:;;{_escape(_plain(a))};;;;")
    for u in contact.urls:
        lines.append(f"URL:{u}")
    if contact.note:
        lines.append(f"NOTE:{_escape(contact.note)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


__all__ = ["Contact", "parse_vcards", "render_vcard"]
