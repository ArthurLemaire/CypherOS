"""Composition root: wires settings → stores, vault, Sentinel, tools, LLM, agent."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from openmuse import prompts
from openmuse.agent import MuseAgent
from openmuse.config import Settings
from openmuse.goals import GoalStore
from openmuse.llm import BaseLLM, create_llm
from openmuse.logger import logger, setup_logging
from openmuse.memory import MemoryStore
from openmuse.sentinel import AuditLog, Sentinel
from openmuse.tools import (
    AskUser,
    Browser,
    Files,
    Forget,
    Goals,
    MCPManager,
    PythonExecute,
    ReadEmails,
    Recall,
    Remember,
    SendEmail,
    Shell,
    Terminate,
    ToolCollection,
    WebFetch,
    WebSearch,
    playwright_available,
)
from openmuse.ui import UI
from openmuse.vault import CredentialVault


class OpenMuseApp:
    def __init__(
        self, settings: Settings, ui: UI, llm: BaseLLM | None = None, session_id: str | None = None
    ):
        self.settings = settings
        self.ui = ui
        setup_logging(settings.log_level, settings.data_dir / "logs")
        settings.ensure_dirs()
        self.session_id = (
            session_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        )

        self.vault = CredentialVault(settings.vault_file, settings.vault_key_file)
        self.memory = MemoryStore(settings.memory_db) if settings.memory.enabled else None
        self.goals = GoalStore(settings.goals_db)
        self.audit = AuditLog(settings.audit_file, session_id=self.session_id)
        self.sentinel = Sentinel(
            settings.sentinel,
            audit=self.audit,
            ui=ui,
            vault=self.vault,
            persistent_approvals_file=settings.data_dir / "approvals.json",
        )
        self.llm = llm or self.make_llm()
        self.mcp = MCPManager(settings.mcp.servers) if settings.mcp.servers else None
        self.tools = self._build_tools()
        self.agent = MuseAgent(
            settings=settings,
            llm=self.llm,
            tools=self.tools,
            sentinel=self.sentinel,
            ui=ui,
            audit=self.audit,
            memory=self.memory,
            goals=self.goals,
            session_file=settings.data_dir / "sessions" / f"{self.session_id}.json",
        )

    # ------------------------------------------------------------------ llm
    def make_llm(self) -> BaseLLM:
        """The model client. ``llm.api_key`` may be a ``{{vault:NAME}}`` reference (that is
        how a key entered in the app is stored); it is resolved here, for the HTTP client
        only — the model itself never sees it."""
        llm_settings = self.settings.llm
        if self.vault.has_placeholders(llm_settings.api_key):
            key = self.vault.resolve(llm_settings.api_key, strict=False)
            if self.vault.has_placeholders(key):
                logger.warning("llm.api_key refers to a vault secret that is not set: {}", key)
                key = ""
            llm_settings = llm_settings.model_copy(update={"api_key": key})
        return create_llm(llm_settings)

    # ------------------------------------------------------------------ tools
    def _build_tools(self) -> ToolCollection:
        s = self.settings
        ws: Path = s.agent.workspace
        tools = ToolCollection(
            Terminate(),
            AskUser(ui=self.ui),
            Files(workspace=ws),
            Shell(workspace=ws),
            PythonExecute(workspace=ws),
            WebSearch(),
            WebFetch(),
            Goals(store=self.goals),
        )
        if self.memory is not None:
            tools.add(
                Remember(store=self.memory), Recall(store=self.memory), Forget(store=self.memory)
            )
        if s.connectors.email.enabled:
            tools.add(
                ReadEmails(settings=s.connectors.email, vault=self.vault),
                SendEmail(settings=s.connectors.email, vault=self.vault),
            )
        if s.browser.enabled:
            if playwright_available():
                tools.add(
                    Browser(
                        headless=s.browser.headless, timeout_ms=s.browser.timeout_ms, workspace=ws
                    )
                )
            else:
                logger.warning(
                    "browser.enabled=true but playwright is missing: pip install 'openmuse[browser]'"
                )
        return tools

    async def start(self) -> OpenMuseApp:
        """Connect optional MCP servers. Call once before using the agent."""
        if self.mcp is not None:
            for tool in await self.mcp.connect():
                self.tools.add(tool)
        return self

    async def close(self) -> None:
        await self.tools.cleanup()
        if self.mcp is not None:
            await self.mcp.close()
        await self.llm.close()
        if self.memory is not None:
            self.memory.close()
        self.goals.close()

    async def __aenter__(self) -> OpenMuseApp:
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------ high-level ops
    async def run(self, task: str) -> str:
        return await self.agent.run(task)

    async def advance_goal(self, goal_id: str) -> str:
        goal = self.goals.get(goal_id)
        if goal is None:
            raise ValueError(f"no goal {goal_id}")
        if goal.status != "active":
            raise ValueError(f"goal {goal_id} is {goal.status}")
        self.agent.reset()
        return await self.agent.run(prompts.ADVANCE_GOAL_PROMPT.format(goal=goal.render()))


__all__ = ["OpenMuseApp"]
