"""Contacts: vCard parsing, the address book, the tool, the app's Connections and the CLI."""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openmuse.cli import app as cli_app
from openmuse.config import (
    ContactSourceSettings,
    ContactsSettings,
    EmailSettings,
    Settings,
    load_app_settings,
)
from openmuse.contacts import OWN, ContactBook, parse_vcards, render_vcard
from openmuse.llm import MockLLM
from openmuse.schema import RiskLevel
from openmuse.server import create_app
from openmuse.server.service import MuseService
from openmuse.tools import Contacts, SendEmail


def private(path: Path) -> bool:
    """0600 — where the file system has modes (Windows keeps files under the user's profile)."""
    return os.name != "posix" or (path.stat().st_mode & 0o777) == 0o600


GOOGLE = """BEGIN:VCARD
VERSION:3.0
FN:Alice Zhang
N:Zhang;Alice;;;
NICKNAME:Ali
EMAIL;TYPE=INTERNET;TYPE=WORK:alice.zhang@acme.example
EMAIL;TYPE=INTERNET;TYPE=HOME;TYPE=pref:alice@example.com
TEL;TYPE=CELL:+86 138 0000 1234
ORG:Acme Corp;Design
TITLE:Design Lead
BDAY:19900517
ADR;TYPE=WORK:;;1 Infinite Loop;Cupertino;CA;95014;USA
NOTE:Met at the offsite\\, likes matcha\\; prefers WeChat.
URL:https://alice.example
UID:google-1
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:张伟
N:张;伟;;;
EMAIL:zhangwei@example.cn
TEL;TYPE=CELL:13900001111
ORG:快手
END:VCARD
BEGIN:VCARD
VERSION:3.0
N:;;;;
FN:
EMAIL:
END:VCARD
"""

APPLE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nPRODID:-//Apple Inc.//iOS 17.0//EN\r\nN:Doe;John;;;\r\n"
    "FN:John Doe\r\nitem1.EMAIL;type=INTERNET;type=pref:john@doe.example\r\n"
    "item1.X-ABLabel:_$!<Other>!$_\r\nitem2.EMAIL;type=INTERNET:jd@work.example\r\n"
    "item2.X-ABLabel:assistant\r\nTEL;type=CELL;type=VOICE;type=pref:(555) 010-0000\r\n"
    "NOTE:This is a very long note that gets folded across multiple lines in the\r\n"
    "  file because vCard lines are limited to 75 octets.\r\nEND:VCARD\r\n"
)

OLD = (
    "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Müller;Hans\r\n"
    "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Hans M=C3=BCller\r\n"
    "EMAIL;PREF;INTERNET:hans@example.de\r\nTEL;CELL:+49 170 0000000\r\nEND:VCARD\r\n"
)


def test_parse_google_export():
    alice, wei = parse_vcards(GOOGLE, source="Google")  # the empty card is skipped
    assert alice.id == "google-1" and alice.name == "Alice Zhang" and alice.nickname == "Ali"
    assert alice.first == "Alice" and alice.last == "Zhang"
    # the preferred address first, types as short labels, 'internet' dropped
    assert alice.emails == ["alice@example.com (home)", "alice.zhang@acme.example (work)"]
    assert alice.emails_plain == ["alice@example.com", "alice.zhang@acme.example"]
    assert alice.phones == ["+86 138 0000 1234 (mobile)"]
    assert alice.org == "Acme Corp, Design" and alice.title == "Design Lead"
    assert alice.birthday == "1990-05-17"
    assert alice.addresses == ["1 Infinite Loop, Cupertino, CA, 95014, USA (work)"]
    assert alice.note == "Met at the offsite, likes matcha; prefers WeChat."
    assert alice.urls == ["https://alice.example"] and alice.source == "Google"
    assert wei.name == "张伟" and wei.org == "快手" and re.fullmatch(r"[0-9a-f]{12}", wei.id)
    rendered = alice.render()
    assert rendered.startswith("Alice Zhang (Ali) — Design Lead, Acme Corp, Design  [google-1]")
    assert "  email: alice@example.com (home), alice.zhang@acme.example (work)" in rendered


def test_parse_apple_groups_folding_and_v21_quoted_printable():
    (john,) = parse_vcards(APPLE)
    assert john.emails == ["john@doe.example (other)", "jd@work.example (assistant)"]
    assert john.phones == ["(555) 010-0000 (mobile)"]
    assert john.note.endswith("limited to 75 octets.") and "\n" not in john.note
    (hans,) = parse_vcards(OLD)
    assert hans.name == "Hans Müller" and hans.emails == ["hans@example.de"]
    assert hans.phones == ["+49 170 0000000 (mobile)"]


def test_render_round_trips():
    (alice, _) = parse_vcards(GOOGLE)
    text = render_vcard(alice)
    assert text.startswith("BEGIN:VCARD\r\nVERSION:4.0\r\nUID:google-1\r\nFN:Alice Zhang\r\n")
    assert "EMAIL;TYPE=home:alice@example.com" in text
    assert "NOTE:Met at the offsite\\, likes matcha\\; prefers WeChat." in text
    (again,) = parse_vcards(text)
    assert again.emails == alice.emails and again.phones == alice.phones
    assert again.org == alice.org and again.note == alice.note and again.birthday == "1990-05-17"


def book_for(tmp_path: Path, *files: tuple[str, str]) -> ContactBook:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sources = []
    for name, text in files:
        path = tmp_path / f"{name}.vcf"
        path.write_text(text, encoding="utf-8")
        sources.append(ContactSourceSettings(name=name, url=str(path)))
    return ContactBook(
        ContactsSettings(sources=sources),
        own_file=tmp_path / "data" / "contacts.vcf",
        cache_file=tmp_path / "data" / "contacts-cache.json",
    )


def test_book_reads_files_searches_and_dedupes(tmp_path: Path):
    book = book_for(tmp_path, ("Google", GOOGLE), ("iPhone", APPLE), ("Old", OLD))
    assert book.configured and len(book) == 4
    names = lambda q: [c.name for c in book.search(q)]  # noqa: E731
    assert names("ali") == ["Alice Zhang"], "a prefix of the name or nickname"
    assert names("alice zhang") == ["Alice Zhang"], "every word must match"
    assert names("alice smith") == []
    assert names("acme") == ["Alice Zhang"], "the company"
    assert names("张") == ["张伟"], "a character inside a CJK name"
    assert names("0000 1234") == ["Alice Zhang"], "digits of a phone number"
    assert names("jd@work.example") == ["John Doe"], "an address"
    assert names("doe") == ["John Doe"] and names("müller") == ["Hans Müller"]
    assert names("nobody") == []
    assert book.by_email("ALICE@example.com").name == "Alice Zhang"
    assert book.by_email("x@y.z") is None
    # the same person in two sources is one person
    twice = book_for(tmp_path / "twice", ("A", GOOGLE), ("B", GOOGLE))
    assert len(twice) == 2
    status = book.status()
    assert status["count"] == 4 and [s["name"] for s in status["sources"]] == [
        OWN,
        "Google",
        "iPhone",
        "Old",
    ]
    assert status["sources"][1]["contacts"] == 2 and not status["sources"][1]["error"]


def test_book_reports_a_missing_file_and_a_bad_placeholder(tmp_path: Path):
    book = ContactBook(
        ContactsSettings(
            sources=[
                ContactSourceSettings(name="Gone", url=str(tmp_path / "nope.vcf")),
                ContactSourceSettings(name="Vault", url="{{vault:CONTACTS_X}}"),
            ]
        ),
        own_file=tmp_path / "contacts.vcf",
    )
    status = {s["name"]: s for s in book.status()["sources"]}
    assert "cannot read" in status["Gone"]["error"]
    assert "placeholder" in status["Vault"]["error"]
    assert len(book) == 0


async def test_book_fetches_links_and_caches_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/all.vcf":
            return httpx.Response(200, text=GOOGLE)
        if request.url.path == "/page.html":
            return httpx.Response(200, text="<html>not a card</html>")
        return httpx.Response(404, text="gone")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", client)
    settings = ContactsSettings(
        sources=[
            ContactSourceSettings(name="Cloud", url="https://contacts.example/all.vcf"),
            ContactSourceSettings(name="Page", url="https://contacts.example/page.html"),
            ContactSourceSettings(name="Missing", url="https://contacts.example/missing.vcf"),
        ]
    )
    cache = tmp_path / "contacts-cache.json"
    book = ContactBook(settings, own_file=tmp_path / "own.vcf", cache_file=cache)
    assert len(book) == 0, "links wait for refresh"
    status = {s["name"]: s for s in (await book.refresh())["sources"]}
    assert status["Cloud"]["contacts"] == 2 and not status["Cloud"]["error"]
    assert status["Page"]["error"] == "not a vCard file"
    assert status["Missing"]["error"] == "HTTP 404"
    assert len(book) == 2 and cache.exists() and private(cache)
    # a new book answers from the cache without the network
    monkeypatch.setattr(httpx, "AsyncClient", None)
    again = ContactBook(settings, own_file=tmp_path / "own.vcf", cache_file=cache)
    assert len(again) == 2 and again.search("alice")[0].source == "Cloud"


def test_own_book_add_update_remove(tmp_path: Path):
    book = book_for(tmp_path, ("Google", GOOGLE))
    bob = book.add("Bob Li", email="bob@example.com", note="landlord")
    assert bob.id == "own-bob-li" and bob.source == OWN and bob.first == "Bob"
    own_file = tmp_path / "data" / "contacts.vcf"
    assert own_file.exists() and private(own_file)
    # same name again: an update, not a second Bob
    bob2 = book.add("bob li", phone="+86 150 0000 0000", org="Rent Co", note="landlord")
    assert bob2.id == bob.id and len(book.own) == 1
    assert bob2.emails == ["bob@example.com"] and bob2.phones == ["+86 150 0000 0000"]
    assert bob2.org == "Rent Co" and bob2.note == "landlord"
    assert len(book) == 3 and book.by_email("bob@example.com").name == "Bob Li"
    assert [c.name for c in book.search("bob")] == ["Bob Li"]
    with pytest.raises(ValueError):
        book.add("Nobody")  # nothing to reach them by
    with pytest.raises(ValueError):
        book.add("", email="x@y.z")
    # people from a source cannot be removed here; own ones can
    assert book.remove("google-1") is None
    assert book.remove(bob.id).name == "Bob Li" and book.own == []
    # a fresh book reads the own file back
    assert len(book_for(tmp_path, ("Google", GOOGLE)).own) == 0


async def test_contacts_tool(tmp_path: Path):
    book = book_for(tmp_path, ("Google", GOOGLE), ("iPhone", APPLE))
    tool = Contacts(book=book)
    assert tool.risk == RiskLevel.SAFE and tool.reads_private_data
    assert tool.assess({"action": "search", "query": "ali"}).reads_private_data
    assert not tool.assess({"action": "add", "name": "x"}).reads_private_data
    r = await tool.execute(action="search", query="ali")
    assert r.ok and r.output.startswith("Alice Zhang (Ali)") and "[google-1]" in r.output
    r = await tool.execute(action="search", query="nobody")
    assert r.ok and "No one matching 'nobody'" in r.output and "rather than guess" in r.output
    r = await tool.execute(action="search")
    assert not r.ok
    r = await tool.execute(action="get", contact_id="google-1")
    assert r.ok and "alice@example.com" in r.output
    assert not (await tool.execute(action="get", contact_id="zzz")).ok
    r = await tool.execute(action="list", limit=2)
    assert r.ok and r.output.startswith("3 people; the first 2:\nAlice Zhang")
    r = await tool.execute(action="add", name="Bob Li", email="bob@example.com", note="landlord")
    assert r.ok and r.output.startswith(f"Saved to {OWN}.") and len(book) == 4
    r = await tool.execute(action="remove", contact_id="google-1")
    assert not r.ok and "only people in the agent's own book" in r.error
    r = await tool.execute(action="remove", contact_id="own-bob-li")
    assert r.ok and len(book) == 3
    assert not (await tool.execute(action="dance")).ok


def test_send_email_names_recipients_and_warns_about_strangers(tmp_path: Path):
    book = book_for(tmp_path, ("Google", GOOGLE))
    email = EmailSettings(enabled=True, smtp_host="smtp.example")
    tool = SendEmail(settings=email, book=book)
    a = tool.assess({"to": "alice@example.com", "subject": "Hi"})
    assert a.summary.startswith("send_email to=Alice Zhang <alice@example.com>") and not a.warnings
    b = tool.assess({"to": "Alice@example.com, eve@evil.example", "subject": "Hi"})
    assert "Alice Zhang <alice@example.com>, eve@evil.example" in b.summary
    assert b.warnings == ["eve@evil.example is not in the address book"]
    assert b.target == "alice@example.com,eve@evil.example"
    # no address book at all: nothing is a stranger, the card shows what was given
    plain = SendEmail(settings=email, book=None).assess({"to": "eve@evil.example"})
    assert plain.summary.startswith("send_email to=eve@evil.example") and not plain.warnings
    empty = SendEmail(settings=email, book=book_for(tmp_path / "empty"))
    assert not empty.assess({"to": "eve@evil.example"}).warnings


# ----------------------------------------------------------------------------- the app
def test_contacts_in_the_app(settings: Settings, tmp_path: Path):
    settings.server.token = "secret-token"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        view = client.get("/api/connections").json()["contacts"]
        assert view["enabled"] and not view["configured"] and view["count"] == 0
        assert "contacts" in service.app.tools, "the tool is there for the agent's own book"
        assert client.get("/api/settings").json()["connectors"]["contacts"] is False
        # upload a .vcf from the phone: kept under <data_dir>/contacts, read at once
        r = client.post(
            "/api/connections/contacts/import?name=iPhone",
            content=APPLE.encode(),
            headers={"Content-Type": "text/vcard"},
        )
        assert r.status_code == 200, r.text
        view = r.json()
        assert view["configured"] and view["count"] == 1
        (src,) = view["sources"]
        assert src["name"] == "iPhone" and src["file"] and src["from_app"] and src["contacts"] == 1
        saved = settings.contacts_dir / "iPhone.vcf"
        assert saved.exists() and private(saved)
        assert load_app_settings(settings.data_dir)["contacts"]["sources"][0]["url"] == str(saved)
        # not a vCard
        r = client.post("/api/connections/contacts/import?name=Bad", content=b"hello")
        assert r.status_code == 400 and "not a vCard" in r.json()["detail"]
        # a file path as a source
        google = tmp_path / "google.vcf"
        google.write_text(GOOGLE, encoding="utf-8")
        r = client.post(
            "/api/connections/contacts/sources", json={"name": "Google", "url": str(google)}
        )
        assert r.status_code == 200 and r.json()["count"] == 3
        assert client.get("/api/settings").json()["connectors"]["contacts"] is True
        # look-ups as the agent does them
        found = client.get("/api/contacts?q=ali").json()
        assert found["count"] == 3 and [p["name"] for p in found["people"]] == ["Alice Zhang"]
        assert [p["name"] for p in client.get("/api/contacts?limit=2").json()["people"]] == [
            "Alice Zhang",
            "John Doe",
        ]
        assert client.post("/api/connections/contacts/test").json() == {
            "ok": True,
            "contacts": 3,
            "sources": 3,
        }
        # a link goes to the vault
        r = client.post(
            "/api/connections/contacts/sources",
            json={"name": "Cloud", "url": "https://contacts.example/all.vcf"},
        )
        assert r.status_code == 200
        assert service.app.vault.get("CONTACTS_CLOUD") == "https://contacts.example/all.vcf"
        assert settings.connectors.contacts.sources[-1].url == "{{vault:CONTACTS_CLOUD}}"
        assert r.json().get("error"), "no network in the test: reading it failed, and it says so"
        # removing: the upload is deleted with its source, the vault entry with the link's
        assert client.delete("/api/connections/contacts/sources/iPhone").status_code == 200
        assert not saved.exists()
        assert client.delete("/api/connections/contacts/sources/Cloud").status_code == 200
        assert service.app.vault.get("CONTACTS_CLOUD") is None
        assert client.delete("/api/connections/contacts/sources/Nope").status_code == 404
        assert client.get("/api/connections").json()["contacts"]["count"] == 2
        # off: the tool goes away and comes back
        assert (
            client.put("/api/connections/contacts", json={"enabled": False}).json()["enabled"]
            is False
        )
        assert "contacts" not in service.app.tools
        assert client.put("/api/connections/contacts", json={"enabled": True}).json()["configured"]
        assert "contacts" in service.app.tools
        # the reserved name
        r = client.post("/api/connections/contacts/sources", json={"name": OWN, "url": str(google)})
        assert r.status_code == 400
        # the system prompt says how many people there are
        prompt = service.threads["main"].agent.build_system_prompt("hi")
        assert "- Address book: 2 people" in prompt


# ----------------------------------------------------------------------------- CLI
def test_contacts_cli(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'data_dir = "{settings.data_dir}"\n[agent]\nworkspace = "{settings.agent.workspace}"\n'
        '[llm]\napi_key = "test"\n'
    )
    google = tmp_path / "google.vcf"
    google.write_text(GOOGLE, encoding="utf-8")
    runner = CliRunner()
    strip = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)  # noqa: E731
    r = runner.invoke(cli_app, ["contacts", "add-source", "Google", str(google), "-c", str(cfg)])
    assert r.exit_code == 0 and "added Google: 2 people" in strip(r.output)
    r = runner.invoke(cli_app, ["contacts", "search", "ali", "-c", str(cfg)])
    assert r.exit_code == 0 and "Alice Zhang (Ali)" in r.output and "[google-1]" in r.output
    r = runner.invoke(cli_app, ["contacts", "search", "nobody", "-c", str(cfg)])
    assert r.exit_code == 1
    r = runner.invoke(
        cli_app,
        [
            "contacts",
            "add",
            "Bob Li",
            "-e",
            "bob@example.com",
            "--note",
            "landlord",
            "-c",
            str(cfg),
        ],
    )
    assert r.exit_code == 0 and "[own-bob-li]" in r.output
    r = runner.invoke(cli_app, ["contacts", "list", "-c", str(cfg)])
    assert r.exit_code == 0 and "3 people; the first 3" in strip(r.output)
    r = runner.invoke(cli_app, ["contacts", "sources", "-c", str(cfg)])
    assert r.exit_code == 0 and "Google" in r.output and OWN in r.output
    r = runner.invoke(cli_app, ["contacts", "remove-source", "Google", "-c", str(cfg)])
    assert r.exit_code == 0 and "removed Google" in r.output
    r = runner.invoke(cli_app, ["contacts", "remove-source", "Google", "-c", str(cfg)])
    assert r.exit_code == 1
    r = runner.invoke(cli_app, ["doctor", "--no-model", "-c", str(cfg)])
    assert "contacts: 1 people" in strip(r.output) or "contacts: 1 person" in strip(r.output)
