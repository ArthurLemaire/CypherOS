"""Connections: the model, email, the browser and MCP servers, set up from the app.

Muse's Connections screen is where you plug things in and take them out again. Here that
means: non-secret settings go to ``<data_dir>/app-settings.json`` (layered over
``config.toml`` on every start, for the app and the CLI alike); secrets go straight into
the encrypted vault and are referred to as ``{{vault:NAME}}``. Nothing here is ever shown
to the model — it only gets the tools that result.
"""

from __future__ import annotations

import asyncio
import imaplib
import re
import smtplib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openmuse.config import (
    CalendarFeedSettings,
    ContactSourceSettings,
    MCPServerSettings,
    apply_app_settings,
    load_app_settings,
    save_app_settings,
)
from openmuse.contacts import OWN
from openmuse.logger import logger
from openmuse.schema import Message
from openmuse.tools import (
    Calendar,
    Contacts,
    MCPManager,
    ReadEmails,
    SendEmail,
    playwright_available,
)
from openmuse.tools.browser import Browser

if TYPE_CHECKING:
    from openmuse.server.service import MuseService

LLM_KEY = "LLM_API_KEY"
EMAIL_ADDRESS = "EMAIL_ADDRESS"
EMAIL_PASSWORD = "EMAIL_PASSWORD"

PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek",
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-flash", "deepseek-chat", "deepseek-reasoner"],
    },
    "openai": {
        "label": "OpenAI",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-5-mini", "gpt-5", "gpt-4.1"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4", "openai/gpt-5-mini"],
    },
    "ollama": {
        "label": "Ollama (local)",
        "provider": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": ["qwen3:8b", "llama3.1:8b"],
        "no_key": True,
    },
    "custom": {"label": "Other OpenAI-compatible endpoint", "provider": "openai", "base_url": ""},
}


def _vault_name(feed_name: str, prefix: str = "CALENDAR_") -> str:
    return prefix + (re.sub(r"[^A-Z0-9]+", "_", feed_name.upper()).strip("_") or "FEED")


def _link_or_path(url: str) -> bool:
    """An http(s)/file link, or a path: absolute, ``~``, or a Windows drive letter."""
    return url.startswith(("http://", "https://", "file://", "/", "~")) or bool(
        re.match(r"^[A-Za-z]:[\\/]", url)
    )


class Connections:
    def __init__(self, svc: MuseService):
        self.svc = svc
        self.data = load_app_settings(svc.data_dir)
        # MCP servers added from the app, connected on demand: name -> manager
        self._mcp: dict[str, MCPManager] = {}
        # calendar feeds that come from config.toml (the app cannot delete those, only its own)
        app_feeds = {f.get("name") for f in (self.data.get("calendar") or {}).get("feeds") or []}
        self._toml_feeds = [
            f for f in svc.settings.connectors.calendar.feeds if f.name not in app_feeds
        ]
        app_sources = {
            c.get("name") for c in (self.data.get("contacts") or {}).get("sources") or []
        }
        self._toml_sources = [
            c for c in svc.settings.connectors.contacts.sources if c.name not in app_sources
        ]

    # ------------------------------------------------------------------ helpers
    @property
    def settings(self):  # noqa: ANN201
        return self.svc.settings

    @property
    def vault(self):  # noqa: ANN201
        return self.svc.app.vault

    def _save(self) -> None:
        save_app_settings(self.svc.data_dir, self.data)

    def _publish(self) -> None:
        self.svc.bus.publish({"kind": "connections", "connections": self.view()})
        self.svc.bus.publish({"kind": "settings", "settings": self.svc.settings_view()})

    # ------------------------------------------------------------------ view
    def view(self) -> dict[str, Any]:
        s = self.settings
        key = s.llm.api_key
        if not key:
            key_source = "none"
        elif self.vault.has_placeholders(key):
            key_source = "vault" if self.vault.get(LLM_KEY) else "missing"
        else:
            key_source = "config"
        email = s.connectors.email
        address = self.vault.get(EMAIL_ADDRESS) or ""
        configured = bool(
            email.imap_host and email.smtp_host and address and self.vault.get(EMAIL_PASSWORD)
        )
        app_mcp = {m["name"] for m in (self.data.get("mcp") or {}).get("servers") or []}
        live_tools: dict[str, int] = {}
        for t in self.svc.app.tools:
            server = getattr(t, "server", None)
            if server:
                live_tools[server] = live_tools.get(server, 0) + 1
        return {
            "llm": {
                "provider": s.llm.provider,
                "model": s.llm.model,
                "base_url": s.llm.base_url or "",
                "tool_mode": s.llm.tool_mode,
                "stream": s.llm.stream,
                "key_source": key_source,
                "from_app": bool(self.data.get("llm")),
            },
            "providers": PROVIDERS,
            "email": {
                "enabled": email.enabled,
                "configured": configured,
                "address": address,
                "imap_host": email.imap_host,
                "imap_port": email.imap_port,
                "smtp_host": email.smtp_host,
                "smtp_port": email.smtp_port,
                "smtp_starttls": email.smtp_starttls,
                "password_set": bool(self.vault.get(EMAIL_PASSWORD)),
            },
            "calendar": self._calendar_view(),
            "contacts": self._contacts_view(),
            "browser": {"enabled": s.browser.enabled, "available": playwright_available()},
            "mcp": [
                {
                    "name": m.name,
                    "command": m.command,
                    "args": m.args,
                    "url": m.url,
                    "risk": m.risk.value,
                    "tools": live_tools.get(m.name, 0),
                    "connected": m.name in live_tools,
                    "from_app": m.name in app_mcp,
                }
                for m in s.mcp.servers
            ],
            "vault": self.vault.names(),
            "onboarded": bool(self.data.get("onboarded")),
        }

    def _calendar_view(self) -> dict[str, Any]:
        cal = self.settings.connectors.calendar
        status = {f["name"]: f for f in self.svc.app.calendar.status()["feeds"]}
        app_names = {f.get("name") for f in self._calendar_data().get("feeds") or []}
        return {
            "enabled": cal.enabled,
            "configured": cal.enabled and bool(cal.feeds),
            "refresh_minutes": cal.refresh_minutes,
            "day_start": cal.day_start,
            "day_end": cal.day_end,
            "feeds": [
                {
                    "name": f.name,
                    "from_app": f.name in app_names,
                    "events": status.get(f.name, {}).get("events", 0),
                    "fetched_at": status.get(f.name, {}).get("fetched_at"),
                    "error": status.get(f.name, {}).get("error", ""),
                }
                for f in cal.feeds
            ],
        }

    def _contacts_view(self) -> dict[str, Any]:
        settings = self.settings.connectors.contacts
        book = self.svc.app.contacts
        status = {s["name"]: s for s in book.status()["sources"]}
        app_names = {c.get("name") for c in self._contacts_data().get("sources") or []}
        return {
            "enabled": settings.enabled,
            "configured": settings.enabled and book.configured,
            "count": len(book) if settings.enabled else 0,
            "own": len(book.own),
            "sources": [
                {
                    "name": c.name,
                    "from_app": c.name in app_names,
                    "file": not c.url.startswith(("http://", "https://", "{{")),
                    "contacts": status.get(c.name, {}).get("contacts", 0),
                    "fetched_at": status.get(c.name, {}).get("fetched_at"),
                    "error": status.get(c.name, {}).get("error", ""),
                }
                for c in settings.sources
            ],
        }

    # ------------------------------------------------------------------ model
    def set_llm(self, body: dict[str, Any]) -> dict[str, Any]:
        llm = dict(self.data.get("llm") or {})
        for key in ("provider", "model", "base_url", "tool_mode"):
            if body.get(key) is not None:
                llm[key] = str(body[key]).strip()
        if llm.get("provider") not in (None, "openai", "openai_responses"):
            raise ValueError("provider must be 'openai' or 'openai_responses'")
        if llm.get("tool_mode") not in (None, "", "auto", "native", "prompt"):
            raise ValueError("tool_mode must be 'auto', 'native' or 'prompt'")
        api_key = body.get("api_key")
        if api_key:
            self.vault.set(LLM_KEY, str(api_key).strip())
            llm["api_key"] = "{{vault:" + LLM_KEY + "}}"
        elif api_key == "":
            # an explicitly empty key: no key at all (local models)
            self.vault.delete(LLM_KEY)
            llm["api_key"] = ""
        self.data["llm"] = llm
        self._save()
        apply_app_settings(self.settings, {"llm": llm})
        if llm.get("api_key") == "":
            self.settings.llm.api_key = ""
        self._swap_llm()
        self._publish()
        return self.view()["llm"]

    def _swap_llm(self) -> None:
        old = self.svc.app.llm
        new = self.svc.app.make_llm()
        self.svc.app.llm = new
        for t in self.svc.threads.values():
            t.agent.llm = new
        asyncio.get_event_loop().create_task(old.close())
        logger.info(
            "model switched to {} @ {}", self.settings.llm.model, self.settings.llm.base_url
        )

    async def test_llm(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            response = await asyncio.wait_for(
                self.svc.app.llm.ask([Message.user("Reply with the single word OK.")], tools=None),
                timeout=45,
            )
        except TimeoutError:
            return {"ok": False, "error": "no answer within 45 s"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
        return {
            "ok": True,
            "reply": (response.content or "").strip()[:200],
            "ms": int((loop.time() - started) * 1000),
        }

    # ------------------------------------------------------------------ email
    def set_email(self, body: dict[str, Any]) -> dict[str, Any]:
        email = dict(self.data.get("email") or {})
        for key in ("imap_host", "smtp_host"):
            if body.get(key) is not None:
                email[key] = str(body[key]).strip()
        for key in ("imap_port", "smtp_port"):
            if body.get(key) is not None:
                email[key] = int(body[key])
        if body.get("smtp_starttls") is not None:
            email["smtp_starttls"] = bool(body["smtp_starttls"])
        if body.get("address") is not None:
            self.vault.set(EMAIL_ADDRESS, str(body["address"]).strip())
        if body.get("password"):
            self.vault.set(EMAIL_PASSWORD, str(body["password"]))
        if body.get("enabled") is not None:
            email["enabled"] = bool(body["enabled"])
        elif (
            email.get("imap_host")
            and email.get("smtp_host")
            and self.vault.get(EMAIL_ADDRESS)
            and self.vault.get(EMAIL_PASSWORD)
        ):
            # everything needed is there: connecting is what saving it means
            email["enabled"] = True
        self.data["email"] = email
        self._save()
        apply_app_settings(self.settings, {"email": email})
        self._sync_email_tools()
        self._publish()
        return self.view()["email"]

    def disconnect_email(self) -> dict[str, Any]:
        self.vault.delete(EMAIL_PASSWORD)
        self.vault.delete(EMAIL_ADDRESS)
        self.data["email"] = {**(self.data.get("email") or {}), "enabled": False}
        self._save()
        self.settings.connectors.email.enabled = False
        self._sync_email_tools()
        self._publish()
        return self.view()["email"]

    def _sync_email_tools(self) -> None:
        tools = self.svc.app.tools
        enabled = self.settings.connectors.email.enabled
        if enabled and "read_emails" not in tools:
            tools.add(
                ReadEmails(settings=self.settings.connectors.email, vault=self.vault),
                SendEmail(
                    settings=self.settings.connectors.email,
                    vault=self.vault,
                    book=self.svc.app.contacts,
                ),
            )
        elif not enabled:
            tools.remove("read_emails")
            tools.remove("send_email")
        for t in tools:
            if t.name in ("read_emails", "send_email"):
                t.settings = self.settings.connectors.email  # type: ignore[attr-defined]

    async def test_email(self) -> dict[str, Any]:
        email = self.settings.connectors.email
        address = self.vault.get(EMAIL_ADDRESS) or ""
        password = self.vault.get(EMAIL_PASSWORD) or ""
        if not (email.imap_host and email.smtp_host and address and password):
            return {"ok": False, "error": "fill in the servers, the address and the password first"}

        def probe() -> dict[str, Any]:
            out: dict[str, Any] = {"ok": True}
            try:
                imap = imaplib.IMAP4_SSL(email.imap_host, email.imap_port, timeout=15)
                imap.login(address, password)
                status, data = imap.select("INBOX", readonly=True)
                out["inbox"] = int(data[0]) if status == "OK" and data and data[0] else None
                imap.logout()
            except (imaplib.IMAP4.error, OSError) as exc:
                return {"ok": False, "error": f"IMAP: {exc}"[:300]}
            try:
                smtp = smtplib.SMTP(email.smtp_host, email.smtp_port, timeout=15)
                if email.smtp_starttls:
                    smtp.starttls()
                smtp.login(address, password)
                smtp.quit()
            except (smtplib.SMTPException, OSError) as exc:
                return {"ok": False, "error": f"SMTP: {exc}"[:300]}
            return out

        return await asyncio.to_thread(probe)

    # ------------------------------------------------------------------ calendar
    def _calendar_data(self) -> dict[str, Any]:
        return dict(self.data.get("calendar") or {})

    def _apply_calendar(self, calendar: dict[str, Any]) -> None:
        self.data["calendar"] = calendar
        self._save()
        settings = self.settings.connectors.calendar
        # feeds from config.toml stay; the app's feeds come after them and win on a name clash
        app_feeds = [CalendarFeedSettings.model_validate(f) for f in calendar.get("feeds") or []]
        app_names = {f.name for f in app_feeds}
        settings.feeds = [f for f in self._toml_feeds if f.name not in app_names] + app_feeds
        settings.enabled = bool(calendar.get("enabled", bool(settings.feeds)))
        for key in ("refresh_minutes", "day_start", "day_end"):
            if calendar.get(key) not in (None, ""):
                setattr(settings, key, calendar[key])
        self._sync_calendar_tool()
        self._publish()

    def _sync_calendar_tool(self) -> None:
        tools = self.svc.app.tools
        enabled = self.settings.connectors.calendar.enabled
        if enabled and "calendar" not in tools:
            tools.add(
                Calendar(feeds=self.svc.app.calendar, workspace=self.settings.agent.workspace)
            )
        elif not enabled:
            tools.remove("calendar")

    async def add_calendar_feed(self, body: dict[str, Any]) -> dict[str, Any]:
        """Add (or replace) a feed; the link goes to the vault, the settings keep a placeholder."""
        name = str(body.get("name") or "").strip()
        url = str(body.get("url") or "").strip()
        if not name:
            raise ValueError("the calendar needs a name")
        if not url:
            raise ValueError("paste the calendar's .ics link (or a path to an .ics file)")
        if not _link_or_path(url):
            raise ValueError("the link must start with https:// (or be a path to an .ics file)")
        secret = _vault_name(name)
        self.vault.set(secret, url)
        calendar = self._calendar_data()
        feeds = [f for f in calendar.get("feeds") or [] if f.get("name") != name]
        feeds.append({"name": name, "url": f"{{{{vault:{secret}}}}}"})
        calendar["feeds"] = feeds
        calendar["enabled"] = True
        self._apply_calendar(calendar)
        status = await self.svc.app.calendar.refresh(force=True)
        state = next((f for f in status["feeds"] if f["name"] == name), None)
        if state and state.get("error"):
            # keep it (the user can fix the link) but say what went wrong
            return {**self.view()["calendar"], "error": state["error"]}
        self.svc.bus.publish({"kind": "calendar", "calendar": self.svc.calendar_view()})
        return self.view()["calendar"]

    def remove_calendar_feed(self, name: str) -> bool:
        calendar = self._calendar_data()
        feeds = calendar.get("feeds") or []
        if not any(f.get("name") == name for f in feeds):
            # a feed from config.toml: it can be switched off, not deleted from here
            return False
        calendar["feeds"] = [f for f in feeds if f.get("name") != name]
        self.vault.delete(_vault_name(name))
        if not calendar["feeds"] and not self._toml_feeds:
            calendar["enabled"] = False
        self._apply_calendar(calendar)
        self.svc.app.calendar.states.pop(name, None)
        self.svc.bus.publish({"kind": "calendar", "calendar": self.svc.calendar_view()})
        return True

    def set_calendar(self, body: dict[str, Any]) -> dict[str, Any]:
        """Working hours, refresh interval, on/off."""
        calendar = self._calendar_data()
        if body.get("enabled") is not None:
            calendar["enabled"] = bool(body["enabled"])
        if body.get("refresh_minutes") is not None:
            calendar["refresh_minutes"] = max(5, int(body["refresh_minutes"]))
        for key in ("day_start", "day_end"):
            if body.get(key):
                value = str(body[key]).strip()
                if not re.fullmatch(r"\d{2}:\d{2}", value):
                    raise ValueError(f"{key} must be HH:MM")
                calendar[key] = value
        self._apply_calendar(calendar)
        return self.view()["calendar"]

    async def test_calendar(self) -> dict[str, Any]:
        cal = self.svc.app.calendar
        if not cal.configured:
            return {"ok": False, "error": "add a calendar link first"}
        status = await cal.refresh(force=True)
        broken = [f for f in status["feeds"] if f["error"]]
        if broken:
            return {"ok": False, "error": "; ".join(f"{f['name']}: {f['error']}" for f in broken)}
        self.svc.bus.publish({"kind": "calendar", "calendar": self.svc.calendar_view()})
        return {
            "ok": True,
            "events": sum(f["events"] for f in status["feeds"]),
            "feeds": len(status["feeds"]),
        }

    # ------------------------------------------------------------------ contacts
    def _contacts_data(self) -> dict[str, Any]:
        return dict(self.data.get("contacts") or {})

    def _apply_contacts(self, contacts: dict[str, Any]) -> None:
        self.data["contacts"] = contacts
        self._save()
        settings = self.settings.connectors.contacts
        app_sources = [
            ContactSourceSettings.model_validate(c) for c in contacts.get("sources") or []
        ]
        app_names = {c.name for c in app_sources}
        settings.sources = [c for c in self._toml_sources if c.name not in app_names] + app_sources
        if contacts.get("enabled") is not None:
            settings.enabled = bool(contacts["enabled"])
        self.svc.app.contacts.read_files()
        self._sync_contacts_tool()
        self._publish()

    def _sync_contacts_tool(self) -> None:
        tools = self.svc.app.tools
        enabled = self.settings.connectors.contacts.enabled
        if enabled and "contacts" not in tools:
            tools.add(Contacts(book=self.svc.app.contacts))
        elif not enabled:
            tools.remove("contacts")

    async def add_contacts_source(self, body: dict[str, Any]) -> dict[str, Any]:
        """A ``.vcf`` link or path. A link goes to the vault (it may be a private URL)."""
        name = str(body.get("name") or "").strip()
        url = str(body.get("url") or "").strip()
        if not name:
            raise ValueError("the address book needs a name")
        if name == OWN:
            raise ValueError(f"{OWN!r} is the agent's own book; pick another name")
        if not url:
            raise ValueError("paste a link to the .vcf file, or a path to one")
        if not _link_or_path(url):
            raise ValueError("the link must start with https:// (or be a path to a .vcf file)")
        if url.startswith(("http://", "https://")):
            secret = _vault_name(name, "CONTACTS_")
            self.vault.set(secret, url)
            url = f"{{{{vault:{secret}}}}}"
        contacts = self._contacts_data()
        sources = [c for c in contacts.get("sources") or [] if c.get("name") != name]
        sources.append({"name": name, "url": url})
        contacts["sources"] = sources
        contacts["enabled"] = True
        self._apply_contacts(contacts)
        status = await self.svc.app.contacts.refresh(only=name)
        state = next((c for c in status["sources"] if c["name"] == name), None)
        self._publish()
        if state and state.get("error"):
            return {**self.view()["contacts"], "error": state["error"]}
        return self.view()["contacts"]

    async def import_contacts(self, name: str, text: str) -> dict[str, Any]:
        """A ``.vcf`` file uploaded from the phone: kept under ``<data_dir>/contacts/`` and
        added as a source."""
        name = name.strip() or "Imported"
        if name == OWN:
            raise ValueError(f"{OWN!r} is the agent's own book; pick another name")
        if "BEGIN:VCARD" not in text.upper():
            raise ValueError("that is not a vCard (.vcf) file")
        folder = self.settings.contacts_dir
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9\u3400-\u9fff_-]+", "-", name).strip("-") or "contacts"
        path = folder / f"{stem}.vcf"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        return await self.add_contacts_source({"name": name, "url": str(path)})

    def remove_contacts_source(self, name: str) -> bool:
        contacts = self._contacts_data()
        sources = contacts.get("sources") or []
        hit = next((c for c in sources if c.get("name") == name), None)
        if hit is None:
            return False  # from config.toml: switched off there, not here
        contacts["sources"] = [c for c in sources if c.get("name") != name]
        self.vault.delete(_vault_name(name, "CONTACTS_"))
        url = str(hit.get("url") or "")
        try:
            uploaded = self.settings.contacts_dir.resolve()
            path = Path(url).resolve()
            if path.is_relative_to(uploaded) and path.is_file():
                path.unlink()  # an upload of ours: gone with the source
        except (OSError, ValueError):
            pass
        self._apply_contacts(contacts)
        self.svc.app.contacts.states.pop(name, None)
        self._publish()
        return True

    def set_contacts(self, body: dict[str, Any]) -> dict[str, Any]:
        contacts = self._contacts_data()
        if body.get("enabled") is not None:
            contacts["enabled"] = bool(body["enabled"])
        self._apply_contacts(contacts)
        return self.view()["contacts"]

    async def test_contacts(self) -> dict[str, Any]:
        book = self.svc.app.contacts
        status = await book.refresh()
        self._publish()
        broken = [c for c in status["sources"] if c["error"]]
        if broken:
            return {
                "ok": False,
                "error": "; ".join(f"{c['name']}: {c['error']}" for c in broken),
            }
        return {"ok": True, "contacts": status["count"], "sources": len(status["sources"])}

    # ------------------------------------------------------------------ browser
    def set_browser(self, enabled: bool) -> dict[str, Any]:
        self.data["browser"] = {"enabled": bool(enabled)}
        self._save()
        self.settings.browser.enabled = bool(enabled)
        tools = self.svc.app.tools
        s = self.settings
        if enabled and playwright_available() and "browser" not in tools:
            tools.add(
                Browser(
                    headless=s.browser.headless,
                    timeout_ms=s.browser.timeout_ms,
                    workspace=s.agent.workspace,
                )
            )
            self.svc.watch_browser()
        elif not enabled:
            tools.remove("browser")
        self._publish()
        return self.view()["browser"]

    # ------------------------------------------------------------------ mcp
    async def add_mcp(self, body: dict[str, Any]) -> dict[str, Any]:
        cfg = MCPServerSettings.model_validate(
            {
                k: v
                for k, v in body.items()
                if k
                in ("name", "command", "args", "env", "url", "risk", "egress", "reads_private_data")
            }
        )
        if not cfg.name.strip():
            raise ValueError("the server needs a name")
        if not (cfg.command or cfg.url):
            raise ValueError("give either a command to run or a URL to connect to")
        await self.remove_mcp(cfg.name, save=False)
        servers = [
            m
            for m in (self.data.get("mcp") or {}).get("servers") or []
            if m.get("name") != cfg.name
        ]
        servers.append(cfg.model_dump(mode="json"))
        self.data["mcp"] = {"servers": servers}
        self._save()
        apply_app_settings(self.settings, {"mcp": {"servers": [cfg.model_dump(mode="json")]}})
        manager = MCPManager([cfg])
        tools = await manager.connect()
        if not tools:
            await manager.close()
            self._publish()
            raise RuntimeError(f"could not connect to '{cfg.name}' (see the server log)")
        self._mcp[cfg.name] = manager
        self.svc.app.tools.add(*tools)
        self._publish()
        return self.view()

    async def remove_mcp(self, name: str, save: bool = True) -> bool:
        servers = (self.data.get("mcp") or {}).get("servers") or []
        known = any(m.get("name") == name for m in servers)
        if save and not known:
            return False
        for t in [t for t in self.svc.app.tools if getattr(t, "server", None) == name]:
            self.svc.app.tools.remove(t.name)
        manager = self._mcp.pop(name, None)
        if manager is not None:
            await manager.close()
        self.settings.mcp.servers = [m for m in self.settings.mcp.servers if m.name != name]
        if save:
            self.data["mcp"] = {"servers": [m for m in servers if m.get("name") != name]}
            self._save()
            self._publish()
        return True

    async def close(self) -> None:
        for manager in self._mcp.values():
            await manager.close()

    # ------------------------------------------------------------------ vault / onboarding
    def set_secret(self, name: str, value: str) -> list[str]:
        self.vault.set(name, value)
        self._publish()
        return self.vault.names()

    def delete_secret(self, name: str) -> bool:
        ok = self.vault.delete(name)
        if ok:
            self._publish()
        return ok

    def set_onboarded(self, done: bool = True) -> None:
        self.data["onboarded"] = bool(done)
        self._save()
        self._publish()


__all__ = ["EMAIL_ADDRESS", "EMAIL_PASSWORD", "LLM_KEY", "PROVIDERS", "Connections"]
