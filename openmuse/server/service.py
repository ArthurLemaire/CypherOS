"""The always-on Muse: threads, background workers, goals scheduler, ideas, profile.

This is the piece that keeps working after you close the app. It owns one
:class:`~openmuse.app.OpenMuseApp` (LLM, tools, Sentinel, vault, memory, goals)
and runs one agent per *thread* — the main chat plus any side chats — so the
user can fire off several requests without waiting for the last one to finish.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openmuse import __version__, prompts
from openmuse.agent import MuseAgent
from openmuse.app import OpenMuseApp
from openmuse.config import Settings
from openmuse.goals import Goal
from openmuse.llm import BaseLLM
from openmuse.logger import logger
from openmuse.schema import Message
from openmuse.server.events import MAIN_THREAD, EventBus, Timeline, new_id, now_iso
from openmuse.server.webui import WebUI, current_thread

IDEAS_PROMPT = """You are {name}, the user's personal agent. Based on what you know about them, propose {n} concrete, genuinely useful things you could do for them right now. Prefer tasks you can actually complete with your tools (research, comparisons, planning, drafting, tracking, reminders, organising files, advancing their goals).

What you know:
{context}

Answer with a JSON array only, no prose. Each item: {{"title": "<short title, max 8 words>", "detail": "<one sentence on what you would do and why it helps>", "prompt": "<the exact request the user could send you to start>"}}. Write in the user's language ({language})."""

STARTER_IDEAS = [
    {
        "title": "Plan my week",
        "detail": "Tell me what's on your plate and I'll turn it into a realistic plan with the important things first.",
        "prompt": "Help me plan my week. Ask me what I need to get done, then propose a schedule.",
    },
    {
        "title": "Research & compare options",
        "detail": "Laptops, flights, insurance, a new phone plan — I'll gather the facts and compare them for you.",
        "prompt": "I need to make a purchase decision. Ask me what I'm choosing between, then research and compare the options.",
    },
    {
        "title": "Set up a long-term goal",
        "detail": "Share a goal (learn a language, run a 10k, save for a trip) and I'll break it into steps and keep track.",
        "prompt": "I want to set up a long-term goal. Ask me about it, then create a plan with concrete steps and track it.",
    },
    {
        "title": "Tell me about yourself",
        "detail": "The more I know about your preferences, routines and constraints, the more useful I get. I'll remember what matters.",
        "prompt": "Ask me a few questions about myself so you can help me better, and remember the answers.",
    },
    {
        "title": "Build a quick tracker",
        "detail": "Spending, habits, workouts, reading — I can write a small script or document to track it for you.",
        "prompt": "Build me a simple tracker. Ask me what I want to track and how, then create it in the workspace.",
    },
]


@dataclass
class Profile:
    name: str = "Muse"
    emoji: str = "✨"
    color: str = "#7c3aed"
    style: str = ""
    proactive: bool = False
    goal_interval_minutes: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "emoji": self.emoji,
            "color": self.color,
            "style": self.style,
            "proactive": self.proactive,
            "goal_interval_minutes": self.goal_interval_minutes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        p = cls()
        for k, v in data.items():
            if hasattr(p, k) and v is not None:
                setattr(p, k, v)
        p.name = (str(p.name).strip() or "Muse")[:40]
        p.emoji = str(p.emoji)[:8] or "✨"
        p.color = str(p.color)[:16] or "#7c3aed"
        p.style = str(p.style)[:1000]
        p.goal_interval_minutes = max(5, min(int(p.goal_interval_minutes), 24 * 60))
        return p


@dataclass
class Thread:
    id: str
    title: str
    created_at: str
    updated_at: str
    timeline: Timeline
    agent: MuseAgent
    inbox: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    worker: asyncio.Task[None] | None = None
    busy: bool = False

    def meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "busy": self.busy,
            "queued": self.inbox.qsize(),
            "events": len(self.timeline.events),
        }


class MuseService:
    def __init__(self, settings: Settings, llm: BaseLLM | None = None):
        self.settings = settings
        settings.ensure_dirs()
        self.data_dir: Path = settings.data_dir
        self.threads_dir = self.data_dir / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.bus = EventBus()
        self.threads: dict[str, Thread] = {}
        self._base_instructions = settings.agent.instructions
        self.profile = self._load_profile()
        self._apply_profile()
        self.ui = WebUI(
            self.bus,
            self.timeline,
            approval_timeout=settings.server.approval_timeout,
            show_thinking=settings.agent.show_thinking,
        )
        self.ui._timelines_provider = lambda: [(t.id, t.timeline) for t in self.threads.values()]
        self.app = OpenMuseApp(settings, ui=self.ui, llm=llm, session_id="app")
        self.token = self._load_token()
        self._scheduler: asyncio.Task[None] | None = None
        self._started = False
        self.started_at = now_iso()
        self._load_threads()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._started:
            return
        await self.app.start()
        self._started = True
        self._scheduler = asyncio.create_task(self._goal_scheduler(), name="goal-scheduler")
        logger.info("MuseService started ({} threads)", len(self.threads))

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.cancel()
        for t in self.threads.values():
            if t.worker:
                t.worker.cancel()
        await asyncio.sleep(0)
        if self._started:
            await self.app.close()
        self._started = False

    # ------------------------------------------------------------------ token / profile
    def _load_token(self) -> str:
        if not self.settings.server.auth:
            return ""
        if self.settings.server.token:
            return self.settings.server.token
        path = self.data_dir / "server_token"
        if path.exists():
            tok = path.read_text("utf-8").strip()
            if tok:
                return tok
        tok = secrets.token_urlsafe(18)
        path.write_text(tok, "utf-8")
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover
            pass
        return tok

    def _load_profile(self) -> Profile:
        path = self.data_dir / "profile.json"
        if path.exists():
            try:
                return Profile.from_dict(json.loads(path.read_text("utf-8")))
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return Profile(name=self.settings.agent.name)

    def _save_profile(self) -> None:
        (self.data_dir / "profile.json").write_text(
            json.dumps(self.profile.to_dict(), ensure_ascii=False, indent=1), "utf-8"
        )

    def _apply_profile(self) -> None:
        a = self.settings.agent
        a.name = self.profile.name
        extra = (
            f"\nYour personality / style, chosen by the user: {self.profile.style.strip()}"
            if self.profile.style.strip()
            else ""
        )
        a.instructions = (self._base_instructions.rstrip() + extra).strip()

    def update_profile(self, data: dict[str, Any]) -> Profile:
        merged = {**self.profile.to_dict(), **{k: v for k, v in data.items() if v is not None}}
        self.profile = Profile.from_dict(merged)
        self._save_profile()
        self._apply_profile()
        self.bus.publish({"kind": "profile", "profile": self.profile.to_dict()})
        return self.profile

    # ------------------------------------------------------------------ threads
    def _load_threads(self) -> None:
        index = self.threads_dir / "index.json"
        metas: list[dict[str, Any]] = []
        if index.exists():
            try:
                metas = json.loads(index.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                metas = []
        if not any(m.get("id") == MAIN_THREAD for m in metas):
            metas.insert(0, {"id": MAIN_THREAD, "title": "Main chat", "created_at": now_iso()})
        for m in metas:
            self._make_thread(
                m["id"], m.get("title", m["id"]), m.get("created_at"), m.get("updated_at")
            )
        self._save_index()

    def _save_index(self) -> None:
        (self.threads_dir / "index.json").write_text(
            json.dumps(
                [
                    {
                        "id": t.id,
                        "title": t.title,
                        "created_at": t.created_at,
                        "updated_at": t.updated_at,
                    }
                    for t in self.threads.values()
                ],
                ensure_ascii=False,
                indent=1,
            ),
            "utf-8",
        )

    def _make_thread(
        self,
        thread_id: str,
        title: str,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> Thread:
        timeline = Timeline(thread_id, self.threads_dir / f"{thread_id}.json")
        session_file = self.threads_dir / f"{thread_id}.session.json"
        agent = MuseAgent(
            settings=self.settings,
            llm=self.app.llm,
            tools=self.app.tools,
            sentinel=self.app.sentinel,
            ui=self.ui,
            audit=self.app.audit,
            memory=self.app.memory,
            goals=self.app.goals,
            session_file=session_file,
        )
        if session_file.exists():
            try:
                agent.load_session(session_file)
            except (OSError, ValueError) as exc:
                logger.warning("could not restore session for {}: {}", thread_id, exc)
        thread = Thread(
            id=thread_id,
            title=title,
            created_at=created_at or now_iso(),
            updated_at=updated_at or created_at or now_iso(),
            timeline=timeline,
            agent=agent,
        )
        self.threads[thread_id] = thread
        return thread

    def timeline(self, thread_id: str) -> Timeline:
        thread = self.threads.get(thread_id)
        if thread is None:
            thread = self._make_thread(thread_id, thread_id)
            self._save_index()
        return thread.timeline

    def create_thread(self, title: str = "") -> Thread:
        tid = "t_" + uuid.uuid4().hex[:8]
        thread = self._make_thread(tid, title.strip() or "Side chat")
        self._save_index()
        self.bus.publish({"kind": "thread", "thread": thread.meta()})
        return thread

    def rename_thread(self, thread_id: str, title: str) -> Thread | None:
        thread = self.threads.get(thread_id)
        if thread is None:
            return None
        thread.title = title.strip() or thread.title
        thread.updated_at = now_iso()
        self._save_index()
        self.bus.publish({"kind": "thread", "thread": thread.meta()})
        return thread

    def delete_thread(self, thread_id: str) -> bool:
        if thread_id == MAIN_THREAD:
            return False
        thread = self.threads.pop(thread_id, None)
        if thread is None:
            return False
        if thread.worker:
            thread.worker.cancel()
        for p in (thread.timeline.path, thread.agent.session_file):
            if p and Path(p).exists():
                Path(p).unlink()
        self._save_index()
        self.bus.publish({"kind": "thread_deleted", "thread": thread_id})
        return True

    def clear_thread(self, thread_id: str) -> bool:
        thread = self.threads.get(thread_id)
        if thread is None or thread.busy:
            return False
        thread.timeline.clear()
        thread.agent.reset()
        thread.agent._save_session()
        self.bus.publish({"kind": "thread_cleared", "thread": thread_id})
        return True

    # ------------------------------------------------------------------ messaging
    def send(
        self, thread_id: str, text: str, source: str = "user", label: str = ""
    ) -> dict[str, Any]:
        """Queue a message for a thread. Returns the timeline event that was created."""
        text = text.strip()
        if not text:
            raise ValueError("empty message")
        thread = self.threads.get(thread_id) or self._make_thread(thread_id, thread_id)
        thread.updated_at = now_iso()
        if source == "user":
            event = self.ui.emit({"type": "user", "text": text, "thread": thread_id})
            self.bus.publish({"kind": "thread", "thread": thread.meta()})
            if self.ui.answer_question(thread_id, text):
                return event
        else:
            event = self.ui.emit(
                {
                    "type": "notice",
                    "level": "info",
                    "text": label or text,
                    "source": source,
                    "thread": thread_id,
                }
            )
        thread.inbox.put_nowait(text)
        self._ensure_worker(thread)
        return event

    def _ensure_worker(self, thread: Thread) -> None:
        if thread.worker is None or thread.worker.done():
            thread.worker = asyncio.create_task(self._worker(thread), name=f"thread-{thread.id}")

    async def _worker(self, thread: Thread) -> None:
        token = current_thread.set(thread.id)
        try:
            while not thread.inbox.empty():
                text = thread.inbox.get_nowait()
                thread.busy = True
                thread.agent.inbox = thread.inbox
                self.bus.publish({"kind": "thread", "thread": thread.meta()})
                self.ui.set_status("working", "Thinking…", thread.id)
                try:
                    final = await thread.agent.run(text)
                    if (
                        final
                        and final.strip()
                        and final.strip() != self.ui.last_assistant_text.get(thread.id)
                    ):
                        self.ui.emit(
                            {"type": "assistant", "text": final.strip(), "thread": thread.id}
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("thread {} failed", thread.id)
                    self.ui.emit(
                        {
                            "type": "notice",
                            "level": "error",
                            "text": f"Something went wrong: {type(exc).__name__}: {exc}",
                            "thread": thread.id,
                        }
                    )
                    if thread.agent.state.value == "error":
                        thread.agent.state = thread.agent.state.__class__.IDLE
                finally:
                    thread.agent.inbox = None
                    thread.busy = False
                    thread.updated_at = now_iso()
                    self.ui.set_status("idle", "", thread.id)
                    self.bus.publish({"kind": "thread", "thread": thread.meta()})
        finally:
            current_thread.reset(token)

    # ------------------------------------------------------------------ approvals
    def decide(
        self, approval_id: str, approved: bool, scope: str = "once", reason: str = ""
    ) -> bool:
        if scope not in ("once", "session", "always"):
            scope = "once"
        return self.ui.resolve_approval(approval_id, approved, scope, reason)

    def forget_approvals(self) -> None:
        self.app.sentinel.forget_approvals()
        self.bus.publish({"kind": "approvals_reset"})

    # ------------------------------------------------------------------ goals
    def advance_goal(self, goal_id: str) -> Goal:
        goal = self.app.goals.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status != "active":
            raise ValueError(f"goal is {goal.status}")
        self.send(
            MAIN_THREAD,
            prompts.ADVANCE_GOAL_PROMPT.format(goal=goal.render()),
            source="goal",
            label=f"Working on goal in the background: {goal.title}",
        )
        return goal

    async def _goal_scheduler(self) -> None:
        while True:
            try:
                await asyncio.sleep(max(60, self.profile.goal_interval_minutes * 60))
                if not self.profile.proactive:
                    continue
                main = self.threads.get(MAIN_THREAD)
                if main is None or main.busy or not main.inbox.empty():
                    continue
                for goal in self.app.goals.list("active"):
                    if goal.next_step is not None:
                        self.advance_goal(goal.id)
                        break  # one goal per tick keeps the chat readable
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001  pragma: no cover
                logger.warning("goal scheduler error: {}", exc)

    # ------------------------------------------------------------------ ideas
    def _ideas_file(self) -> Path:
        return self.data_dir / "ideas.json"

    def cached_ideas(self) -> dict[str, Any]:
        path = self._ideas_file()
        if path.exists():
            try:
                return json.loads(path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"generated_at": None, "source": "starter", "ideas": STARTER_IDEAS}

    async def refresh_ideas(self, n: int = 5) -> dict[str, Any]:
        context_lines: list[str] = []
        if self.app.memory is not None:
            for m in self.app.memory.all(limit=30):
                context_lines.append(f"- memory ({m.category}): {m.content}")
        for g in self.app.goals.list("active")[:8]:
            nxt = g.next_step
            context_lines.append(
                f"- goal: {g.title} (progress {g.progress}"
                + (f", next: {nxt.title}" if nxt else "")
                + ")"
            )
        main = self.threads.get(MAIN_THREAD)
        if main is not None:
            recent = [e for e in main.timeline.events if e.get("type") in ("user", "assistant")][
                -8:
            ]
            for e in recent:
                context_lines.append(f"- recent {e['type']}: {str(e.get('text', ''))[:200]}")
        if self.settings.agent.user_profile.strip():
            context_lines.insert(0, f"- profile: {self.settings.agent.user_profile.strip()[:500]}")
        if not context_lines:
            data = {"generated_at": now_iso(), "source": "starter", "ideas": STARTER_IDEAS}
            self._ideas_file().write_text(json.dumps(data, ensure_ascii=False), "utf-8")
            return data
        language = self.settings.agent.language
        prompt = IDEAS_PROMPT.format(
            name=self.profile.name,
            n=n,
            context="\n".join(context_lines),
            language="the same language as the context above"
            if language in ("", "auto")
            else language,
        )
        response = await self.app.llm.ask([Message.user(prompt)], tools=None)
        ideas = _parse_ideas(response.content or "")
        data = {
            "generated_at": now_iso(),
            "source": "model" if ideas else "starter",
            "ideas": ideas or STARTER_IDEAS,
        }
        self._ideas_file().write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        self.bus.publish({"kind": "ideas", "ideas": data})
        return data

    # ------------------------------------------------------------------ files / artifacts
    def workspace(self) -> Path:
        return self.settings.agent.workspace.resolve()

    def resolve_workspace_path(self, rel: str) -> Path:
        ws = self.workspace()
        target = (ws / rel).resolve()
        if target != ws and ws not in target.parents:
            raise PermissionError("path outside the workspace")
        return target

    def list_files(self, limit: int = 200) -> list[dict[str, Any]]:
        ws = self.workspace()
        out: list[dict[str, Any]] = []
        if not ws.exists():
            return out
        for p in ws.rglob("*"):
            if not p.is_file() or any(part.startswith(".") for part in p.relative_to(ws).parts):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            out.append(
                {
                    "path": str(p.relative_to(ws)),
                    "name": p.name,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(
                        timespec="seconds"
                    ),
                }
            )
            if len(out) >= 5000:
                break
        out.sort(key=lambda f: f["modified"], reverse=True)
        return out[:limit]

    # ------------------------------------------------------------------ state snapshots
    def activity(self, n: int = 100) -> dict[str, Any]:
        s = self.app.sentinel
        return {
            "audit": self.app.audit.tail(n),
            "approvals": {
                "session": sorted(s.session_allow),
                "persistent": sorted(s.persistent_allow),
            },
            "tainted": s.tainted,
        }

    def settings_view(self) -> dict[str, Any]:
        s = self.settings
        return {
            "version": __version__,
            "profile": self.profile.to_dict(),
            "sentinel": {
                "mode": s.sentinel.mode,
                "always_ask_tools": s.sentinel.always_ask_tools,
                "always_allow_tools": s.sentinel.always_allow_tools,
                "deny_tools": s.sentinel.deny_tools,
                "taint_tracking": s.sentinel.taint_tracking,
                "egress_allowlist": s.sentinel.egress_allowlist,
            },
            "llm": {"provider": s.llm.provider, "model": s.llm.model, "stream": s.llm.stream},
            "agent": {
                "language": s.agent.language,
                "max_steps": s.agent.max_steps,
                "show_thinking": s.agent.show_thinking,
                "workspace": str(s.agent.workspace),
            },
            "connectors": {
                "email": s.connectors.email.enabled,
                "browser": s.browser.enabled,
                "mcp": [m.name for m in s.mcp.servers],
            },
            "tools": [
                {"name": t.name, "risk": t.risk.value, "description": t.description[:160]}
                for t in self.app.tools
            ],
            "memory_enabled": s.memory.enabled,
            "data_dir": str(self.data_dir),
            "started_at": self.started_at,
        }

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if "profile" in data and isinstance(data["profile"], dict):
            self.update_profile(data["profile"])
        if (mode := data.get("sentinel_mode")) in ("ask", "strict", "auto"):
            self.settings.sentinel.mode = mode
        if "show_thinking" in data:
            self.settings.agent.show_thinking = bool(data["show_thinking"])
            self.ui.show_thinking = bool(data["show_thinking"])
        if (lang := data.get("language")) is not None:
            self.settings.agent.language = str(lang)[:20] or "auto"
        self.bus.publish({"kind": "settings", "settings": self.settings_view()})
        return self.settings_view()

    def state(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "profile": self.profile.to_dict(),
            "status": self.ui.overall_status(),
            "threads": [t.meta() for t in self.threads.values()],
            "pending_approvals": [
                ev
                for t in self.threads.values()
                for ev in t.timeline.events
                if ev.get("type") == "approval" and ev.get("status") == "pending"
            ],
            "goals": [goal_to_dict(g) for g in self.app.goals.list()],
            "settings": self.settings_view(),
        }


def goal_to_dict(g: Goal) -> dict[str, Any]:
    done = sum(1 for s in g.steps if s.status in ("done", "skipped"))
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "status": g.status,
        "notes": g.notes,
        "created_at": g.created_at,
        "updated_at": g.updated_at,
        "progress": {"done": done, "total": len(g.steps)},
        "next_step": g.next_step.title if g.next_step else None,
        "steps": [
            {
                "idx": s.idx,
                "title": s.title,
                "status": s.status,
                "note": s.note,
                "updated_at": s.updated_at,
            }
            for s in g.steps
        ],
    }


def _parse_ideas(text: str) -> list[dict[str, str]]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    ideas: list[dict[str, str]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if title and prompt:
            ideas.append(
                {
                    "title": title[:80],
                    "detail": str(item.get("detail", "")).strip()[:300],
                    "prompt": prompt[:1000],
                }
            )
    return ideas[:8]


__all__ = ["MuseService", "Profile", "Thread", "goal_to_dict", "new_id"]
