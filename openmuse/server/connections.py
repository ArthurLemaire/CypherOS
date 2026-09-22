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
import smtplib
from typing import TYPE_CHECKING, Any

from openmuse.config import (
    MCPServerSettings,
    apply_app_settings,
    load_app_settings,
    save_app_settings,
)
from openmuse.logger import logger
from openmuse.schema import Message
from openmuse.tools import MCPManager, ReadEmails, SendEmail, playwright_available
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


class Connections:
    def __init__(self, svc: MuseService):
        self.svc = svc
        self.data = load_app_settings(svc.data_dir)
        # MCP servers added from the app, connected on demand: name -> manager
        self._mcp: dict[str, MCPManager] = {}

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

    # ------------------------------------------------------------------ model
    def set_llm(self, body: dict[str, Any]) -> dict[str, Any]:
        llm = dict(self.data.get("llm") or {})
        for key in ("provider", "model", "base_url", "tool_mode"):
            if body.get(key) is not None:
                llm[key] = str(body[key]).strip()
        if llm.get("provider") not in (None, "openai", "openai_responses"):
            raise ValueError("provider must be 'openai' or 'openai_responses'")
        if llm.get("tool_mode") not in (None, "", "native", "prompt"):
            raise ValueError("tool_mode must be 'native' or 'prompt'")
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
                SendEmail(settings=self.settings.connectors.email, vault=self.vault),
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
