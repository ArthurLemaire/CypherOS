"""The agent loop: think (LLM) → act (tools through the Sentinel) → repeat."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from openmuse import prompts
from openmuse.config import Settings
from openmuse.goals import GoalStore
from openmuse.llm.base import BaseLLM
from openmuse.logger import logger
from openmuse.memory import MemoryStore
from openmuse.schema import AgentState, Message, Role, ToolResult
from openmuse.sentinel import AuditLog, Sentinel
from openmuse.tools.base import ToolCollection
from openmuse.ui import UI


class MuseAgent:
    def __init__(
        self,
        settings: Settings,
        llm: BaseLLM,
        tools: ToolCollection,
        sentinel: Sentinel,
        ui: UI,
        audit: AuditLog,
        memory: MemoryStore | None = None,
        goals: GoalStore | None = None,
        session_file: Path | None = None,
    ):
        self.settings = settings
        self.llm = llm
        self.tools = tools
        self.sentinel = sentinel
        self.ui = ui
        self.audit = audit
        self.memory = memory
        self.goals = goals
        self.session_file = session_file
        self.messages: list[Message] = []
        self.state = AgentState.IDLE
        self.turns = 0

    # ------------------------------------------------------------------ prompt
    def build_system_prompt(self, user_input: str) -> str:
        a = self.settings.agent
        language_rule = (
            prompts.LANGUAGE_AUTO
            if a.language in ("", "auto")
            else prompts.LANGUAGE_FIXED.format(language=a.language)
        )
        memories = ""
        if self.memory is not None and self.settings.memory.enabled:
            items = self.memory.relevant(user_input, limit=self.settings.memory.max_inject)
            if items:
                memories = prompts.MEMORY_SECTION.format(
                    items="\n".join(f"- {m.render()}" for m in items)
                )
        goals = ""
        if self.goals is not None:
            active = self.goals.list("active")[:5]
            if active:
                lines = []
                for g in active:
                    nxt = g.next_step
                    lines.append(
                        f"- {g.id}: {g.title} (progress {g.progress}"
                        + (f", next: {nxt.idx}. {nxt.title}" if nxt else "")
                        + ")"
                    )
                goals = prompts.GOALS_SECTION.format(items="\n".join(lines))
        profile = (
            prompts.USER_PROFILE_SECTION.format(profile=a.user_profile.strip())
            if a.user_profile.strip()
            else ""
        )
        extra = (
            f"\n## Additional instructions\n{a.instructions.strip()}\n"
            if a.instructions.strip()
            else ""
        )
        return prompts.SYSTEM_PROMPT.format(
            name=a.name,
            language_rule=language_rule,
            now=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M (%A, UTC%z)"),
            workspace=str(a.workspace.resolve()),
            sentinel_mode=self.settings.sentinel.mode,
            tool_names=", ".join(t.name for t in self.tools),
            user_profile=profile,
            memories=memories,
            goals=goals,
            extra=extra,
        )

    # ------------------------------------------------------------------ context window
    def context_messages(self) -> list[Message]:
        limit = self.settings.agent.max_context_messages
        msgs = self.messages
        if len(msgs) <= limit:
            return list(msgs)
        cutoff = len(msgs) - limit
        # Never start in the middle of a tool exchange: advance to the next user message.
        while cutoff < len(msgs) and msgs[cutoff].role != Role.USER:
            cutoff += 1
        return list(msgs[cutoff:]) if cutoff < len(msgs) else list(msgs[-limit:])

    # ------------------------------------------------------------------ stuck detection
    def _is_stuck(self) -> bool:
        assistants = [m for m in self.messages if m.role == Role.ASSISTANT][-3:]
        if len(assistants) < 3:
            return False

        def sig(m: Message) -> str:
            calls = [(tc.function.name, tc.function.arguments) for tc in (m.tool_calls or [])]
            return json.dumps([m.content, calls], ensure_ascii=False, sort_keys=True)

        return len({sig(m) for m in assistants}) == 1

    # ------------------------------------------------------------------ main loop
    async def run(self, user_input: str) -> str:
        if self.state == AgentState.RUNNING:
            raise RuntimeError("agent is already running")
        self.state = AgentState.RUNNING
        self.turns += 1
        self.messages.append(Message.user(user_input))
        self.audit.record("user_message", content=user_input)
        system_prompt = self.build_system_prompt(user_input)
        tool_params = self.tools.to_params()
        final: str | None = None
        step = 0
        empty_replies = 0
        try:
            while step < self.settings.agent.max_steps:
                step += 1
                context = [Message.system(system_prompt), *self.context_messages()]
                response = await self.llm.ask(
                    context, tools=tool_params, on_delta=self.ui.on_text_delta
                )
                assistant = response.to_message()
                assistant.meta.update({"step": step, "usage": response.usage})
                self.messages.append(assistant)
                self.ui.on_assistant_message(response.content, response.reasoning)
                self.audit.record(
                    "assistant_message",
                    step=step,
                    content=response.content or "",
                    tool_calls=[tc.function.name for tc in response.tool_calls],
                    usage=response.usage,
                )

                if not response.tool_calls:
                    if response.content:
                        final = response.content
                        break
                    empty_replies += 1
                    if empty_replies >= 2:
                        final = ""
                        break
                    self.messages.append(
                        Message.user(
                            "(Your reply was empty. Continue the task, or call `terminate` if it is done.)"
                        )
                    )
                    continue

                stop = False
                for call in response.tool_calls:
                    tool = self.tools.get(call.name)
                    summary = tool.assess(call.arguments).summary if tool else f"{call.name}(?)"
                    self.ui.on_tool_call(call, summary)
                    if tool is None:
                        result = ToolResult.fail(
                            f"unknown tool '{call.name}'. Available tools: {', '.join(t.name for t in self.tools)}"
                        )
                    else:
                        result = await self.sentinel.guard(call, tool)
                    self.ui.on_tool_result(call, result)
                    self.messages.append(Message.tool(result.for_model(), call.id, call.name))
                    if result.stop:
                        final = result.output
                        stop = True
                if stop:
                    break
                if self._is_stuck():
                    logger.warning("agent seems stuck – nudging")
                    self.messages.append(Message.user(prompts.STUCK_PROMPT))
            else:
                # Step budget exhausted: ask for a wrap-up without tools.
                self.messages.append(Message.user(prompts.MAX_STEPS_PROMPT))
                context = [Message.system(system_prompt), *self.context_messages()]
                response = await self.llm.ask(context, tools=None, on_delta=self.ui.on_text_delta)
                self.messages.append(response.to_message())
                self.ui.on_assistant_message(response.content, response.reasoning)
                final = response.content or "(step limit reached)"
            self.state = AgentState.FINISHED
        except Exception:
            self.state = AgentState.ERROR
            raise
        finally:
            self._save_session()
        return final or ""

    # ------------------------------------------------------------------ session persistence
    def reset(self) -> None:
        self.messages.clear()
        self.sentinel.tainted = False
        self.state = AgentState.IDLE

    def _save_session(self) -> None:
        if not self.session_file:
            return
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {
                "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "turns": self.turns,
                "messages": [m.model_dump(mode="json") for m in self.messages],
            }
            self.session_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        except OSError as exc:  # pragma: no cover
            logger.warning("could not save session: {}", exc)

    def load_session(self, path: Path) -> int:
        data = json.loads(Path(path).read_text("utf-8"))
        self.messages = [Message.model_validate(m) for m in data.get("messages", [])]
        self.turns = int(data.get("turns", 0))
        return len(self.messages)


__all__ = ["MuseAgent"]
