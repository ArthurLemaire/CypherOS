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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openmuse import __version__, prompts
from openmuse.agent import MuseAgent
from openmuse.app import OpenMuseApp
from openmuse.config import Settings
from openmuse.goals import Goal
from openmuse.llm import BaseLLM
from openmuse.logger import logger
from openmuse.memory.consolidate import TidyReport, tidy
from openmuse.reminders import Reminder
from openmuse.schema import Message
from openmuse.sentinel.grants import SCOPES
from openmuse.server.connections import Connections
from openmuse.server.events import MAIN_THREAD, EventBus, Timeline, new_id, now_iso
from openmuse.server.push import PushService
from openmuse.server.webui import WebUI, current_thread
from openmuse.tools.browser import Browser
from openmuse.tools.reminder_tools import Reminders

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


PROACTIVITY = ("off", "low", "default", "high")
# how the configured interval stretches or shrinks per level
_INTERVAL_FACTOR = {"low": 2.0, "default": 1.0, "high": 0.5}
_QUIET_HOURS_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)-([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class Profile:
    name: str = "Muse"
    emoji: str = "✨"
    color: str = "#7c3aed"
    style: str = ""
    # what the user wants to be called
    user_name: str = ""
    # how eagerly background work runs and reaches out: off · low · default · high
    proactivity: str = "default"
    goal_interval_minutes: int = 60
    # "22:00-08:00" (server local time): no background passes in this window
    quiet_hours: str = ""

    @property
    def proactive(self) -> bool:
        return self.proactivity != "off"

    @property
    def interval_seconds(self) -> int:
        factor = _INTERVAL_FACTOR.get(self.proactivity, 1.0)
        return max(60, int(self.goal_interval_minutes * 60 * factor))

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        window = _parse_quiet_hours(self.quiet_hours)
        if window is None:
            return False
        start, end = window
        local = (now or datetime.now()).astimezone()
        minute = local.hour * 60 + local.minute
        if start <= end:
            return start <= minute < end
        return minute >= start or minute < end  # wraps midnight

    def quiet_hours_end(self, now: datetime | None = None) -> datetime | None:
        """When the current quiet window ends, or None if we are not in one."""
        if not self.in_quiet_hours(now):
            return None
        _, end = _parse_quiet_hours(self.quiet_hours)  # type: ignore[misc]
        now = (now or datetime.now()).astimezone()
        candidate = now.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "emoji": self.emoji,
            "color": self.color,
            "style": self.style,
            "user_name": self.user_name,
            "proactivity": self.proactivity,
            "proactive": self.proactive,
            "goal_interval_minutes": self.goal_interval_minutes,
            "quiet_hours": self.quiet_hours,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        p = cls()
        for k, v in data.items():
            if k != "proactive" and hasattr(p, k) and v is not None:
                setattr(p, k, v)
        if "proactivity" not in data and "proactive" in data:
            # profiles written before the dial existed
            p.proactivity = "default" if data["proactive"] else "off"
        if p.proactivity not in PROACTIVITY:
            p.proactivity = "default"
        p.name = (str(p.name).strip() or "Muse")[:40]
        p.emoji = str(p.emoji)[:8] or "✨"
        p.color = str(p.color)[:16] or "#7c3aed"
        p.style = str(p.style)[:1000]
        p.user_name = str(p.user_name).strip()[:60]
        p.goal_interval_minutes = max(5, min(int(p.goal_interval_minutes), 24 * 60))
        p.quiet_hours = str(p.quiet_hours).strip()
        if p.quiet_hours and _parse_quiet_hours(p.quiet_hours) is None:
            p.quiet_hours = ""
        return p


def _parse_quiet_hours(value: str) -> tuple[int, int] | None:
    m = _QUIET_HOURS_RE.match(value.strip()) if value else None
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    return (start, end) if start != end else None


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
    # background prompts (goal work, ideas) → the short label shown as the approval purpose
    purposes: dict[str, str] = field(default_factory=dict)

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
            workspace=settings.agent.workspace.resolve(),
            exclude=(settings.data_dir,),
        )
        self.ui._timelines_provider = lambda: [(t.id, t.timeline) for t in self.threads.values()]
        self.push = PushService(settings.data_dir)
        self.ui.on_event = self._maybe_push
        self.app = OpenMuseApp(settings, ui=self.ui, llm=llm, session_id="app")
        self.watch_browser()
        self._watch_reminders()
        self.connections = Connections(self)
        self.token = self._load_token()
        self._scheduler: asyncio.Task[None] | None = None
        self._tidying = False
        self._started = False
        self.started_at = now_iso()
        self.next_goal_pass_at: datetime | None = None
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
            await self.connections.close()
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
        extra = ""
        if self.profile.user_name:
            extra += (
                f"\nThe user's name is {self.profile.user_name}; address them by it when natural."
            )
        if self.profile.style.strip():
            extra += f"\nYour personality / style, chosen by the user: {self.profile.style.strip()}"
        a.instructions = (self._base_instructions.rstrip() + extra).strip()

    def update_profile(self, data: dict[str, Any]) -> Profile:
        data = {k: v for k, v in data.items() if v is not None}
        if "proactive" in data and "proactivity" not in data:
            # the old switch: off, or back to the default level
            data["proactivity"] = (
                "off"
                if not data["proactive"]
                else (self.profile.proactivity if self.profile.proactive else "default")
            )
        data.pop("proactive", None)
        merged = {**self.profile.to_dict(), **data}
        merged.pop("proactive", None)
        before = (
            self.profile.proactivity,
            self.profile.goal_interval_minutes,
            self.profile.quiet_hours,
        )
        self.profile = Profile.from_dict(merged)
        if before != (
            self.profile.proactivity,
            self.profile.goal_interval_minutes,
            self.profile.quiet_hours,
        ):
            self.schedule_next_pass()
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
        # Cards that were waiting for an answer when the server stopped can't be answered
        # any more: the agent run behind them is gone.
        stale = [
            ev
            for ev in timeline.events
            if ev.get("type") in ("approval", "question") and ev.get("status") == "pending"
        ]
        for ev in stale:
            timeline.update(ev["id"], status="expired")
        running = [
            ev
            for ev in timeline.events
            if ev.get("type") == "tool" and ev.get("status") == "running"
        ]
        for ev in running:
            timeline.update(ev["id"], status="error", output="interrupted by a restart")
        for ev in timeline.events:
            if ev.get("type") == "browser" and ev.get("status") == "live":
                timeline.update(ev["id"], status="done")
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
            calendar=self.app.calendar,
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
            if label:
                thread.purposes[text] = label
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
                    purpose = thread.purposes.pop(text, None)
                    self.ui.begin_run(thread.id, background=purpose)
                    final = await thread.agent.run(text, purpose=purpose)
                    quiet, final = (
                        prompts.split_quiet(final or "") if purpose else (False, final or "")
                    )
                    self._finish_run(thread, purpose, final.strip(), quiet)
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
                    self.ui.end_run(thread.id)
                    thread.agent.inbox = None
                    thread.busy = False
                    thread.updated_at = now_iso()
                    self.ui.set_status("idle", "", thread.id)
                    self.bus.publish({"kind": "thread", "thread": thread.meta()})
        finally:
            current_thread.reset(token)

    def _finish_run(self, thread: Thread, purpose: str | None, final: str, quiet: bool) -> None:
        """The run's last word: shown as the assistant bubble unless it is on screen
        already, and flagged ``final`` so clients can tell it from the step narration
        before it. Background runs push it once, here, not per step."""
        event: dict[str, Any] | None = None
        if (
            final
            and thread.id not in self.ui.reply_shown
            and final != self.ui.last_assistant_text.get(thread.id)
        ):
            event = {"type": "assistant", "text": final, "thread": thread.id, "final": True}
            if quiet:
                event["quiet"] = True
            event = self.ui.emit(event)
        else:
            eid = self.ui.last_assistant_event.get(thread.id)
            if eid and (existing := self.ui.get_timeline(thread.id).get(eid)):
                if not existing.get("final"):
                    self.ui.patch(thread.id, eid, final=True)
                event = existing
        if purpose and event and event.get("text") and not event.get("quiet"):
            self._push_background(event)

    # ------------------------------------------------------------------ approvals
    def decide(
        self, approval_id: str, approved: bool, scope: str = "once", reason: str = ""
    ) -> bool:
        if scope not in SCOPES:
            scope = "once"
        return self.ui.resolve_approval(approval_id, approved, scope, reason)

    def forget_approvals(self) -> None:
        self.app.sentinel.forget_approvals()
        self.bus.publish({"kind": "approvals_reset"})

    def revoke_grant(self, key: str) -> bool:
        ok = self.app.sentinel.revoke(key)
        if ok:
            self.bus.publish({"kind": "approvals_reset"})
        return ok

    # ------------------------------------------------------------------ browser view
    @property
    def browser(self) -> Browser | None:
        tool = self.app.tools.get("browser")
        return tool if isinstance(tool, Browser) else None

    def watch_browser(self) -> None:
        """Show the user what the browser tool sees. Called again when the tool is added."""
        tool = self.browser
        if tool is not None:
            tool.on_frame = self.ui.on_browser_frame

    async def browser_control(self, thread: str, body: dict[str, Any]) -> dict[str, Any]:
        """The user takes over the agent's browser from the app (tap, type, open a URL)."""
        tool = self.browser
        if tool is None:
            raise LookupError("the browser tool is not enabled")
        action = str(body.get("action") or "")
        if action not in ("click", "type", "key", "scroll", "navigate", "look"):
            raise ValueError(f"unknown browser action '{action}'")
        if action not in ("look", "navigate") and not tool.open:
            raise LookupError("the browser is not open right now — open a URL first")
        return await tool.user_action(
            action,
            thread,
            x=body.get("x"),
            y=body.get("y"),
            text=body.get("text"),
            key=body.get("key"),
            dy=body.get("dy"),
            url=body.get("url"),
        )

    # ------------------------------------------------------------------ push
    def pending_count(self) -> int:
        """Cards waiting for the user, across threads — the app badge number."""
        return len(self.ui.pending_approvals) + len(self.ui.pending_questions)

    @staticmethod
    def _push_url(thread: str) -> str:
        return "/" if thread == MAIN_THREAD else f"/?thread={thread}"

    def _maybe_push(self, event: dict[str, Any]) -> None:
        """Called with every persisted event: a card that needs you gets a push. Background
        results go through ``_push_background`` once the run is over, so the step-by-step
        narration never leaves the app; the service worker drops the notification anyway
        if the app is on screen."""
        if not self.push.enabled or not self.push.subscriptions:
            return
        kind = event.get("type")
        thread = event.get("thread") or MAIN_THREAD
        name = self.profile.name
        if kind == "approval" and event.get("status") == "pending":
            self.push.notify(
                f"{name} needs your approval",
                event.get("summary") or event.get("tool") or "",
                tag=f"approval-{event['id']}",
                url=self._push_url(thread),
                badge=self.pending_count(),
                kind="approval",
            )
        elif kind == "question" and event.get("status") == "pending":
            self.push.notify(
                f"{name} has a question",
                event.get("text") or "",
                tag=f"question-{event['id']}",
                url=self._push_url(thread),
                badge=self.pending_count(),
                kind="question",
            )

    def _push_background(self, event: dict[str, Any]) -> None:
        """The last word of a background run (a goal pass, a check-in) worth surfacing."""
        if not self.push.enabled or not self.push.subscriptions:
            return
        thread = event.get("thread") or MAIN_THREAD
        name = self.profile.name
        about = str(event.get("about") or "")
        title = about.replace("Working on your goal: ", "") or name
        if about.startswith("Check-in: "):
            title = f"{name} · check-in"
        elif about.startswith("Reminder: "):
            title = f"{name} · reminder"
        elif about.startswith("Routine: "):
            title = about[len("Routine: ") :] or name
        self.push.notify(
            title,
            _first_lines(str(event["text"])),
            tag=f"background-{thread}",
            url=self._push_url(thread),
            badge=self.pending_count(),
            kind="background",
        )

    # ------------------------------------------------------------------ goals
    def advance_goal(self, goal_id: str) -> Goal:
        goal = self.app.goals.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status != "active":
            raise ValueError(f"goal is {goal.status}")
        surfacing = prompts.SURFACING.get(self.profile.proactivity, prompts.SURFACING["default"])
        self.send(
            MAIN_THREAD,
            prompts.ADVANCE_GOAL_PROMPT.format(goal=goal.render(), surfacing=surfacing),
            source="goal",
            label=f"Working on your goal: {goal.title}",
        )
        return goal

    def _next_pass_delay(self) -> float:
        """Seconds until the next background pass: the level's interval, pushed past the
        quiet window if it would land inside one."""
        delay = float(self.profile.interval_seconds)
        due = datetime.now().astimezone() + timedelta(seconds=delay)
        end = self.profile.quiet_hours_end(due)
        if end is not None:
            # a second past the end, so the pass does not wake up still inside the window
            delay = max(delay, (end - datetime.now().astimezone()).total_seconds() + 1)
        return delay

    def schedule_next_pass(self) -> None:
        """(Re)compute when the next background pass is due — on start, after a pass, and
        whenever the level, the interval or the quiet hours change."""
        self.next_goal_pass_at = datetime.now(UTC) + timedelta(seconds=self._next_pass_delay())

    def check_in(self, goal_id: str) -> Goal:
        """Send the reminder for a goal now: a short message from the agent, no work done."""
        goal = self.app.goals.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        if goal.status != "active":
            raise ValueError(f"goal is {goal.status}")
        self.send(
            MAIN_THREAD,
            prompts.CHECK_IN_PROMPT.format(
                goal=goal.render(),
                today=datetime.now().astimezone().strftime("%A, %Y-%m-%d"),
                quiet=prompts.QUIET_MARKER,
            ),
            source="goal",
            label=f"Check-in: {goal.title}",
        )
        self.app.goals.mark_checked_in(goal.id)
        return goal

    def _run_due_check_ins(self) -> None:
        """Reminders the user asked for fire at any proactivity level, but not in quiet hours
        (they wait for the window to end) and not over a conversation in progress."""
        if self.profile.in_quiet_hours():
            return
        main = self.threads.get(MAIN_THREAD)
        if main is None or main.busy or not main.inbox.empty():
            return
        for goal in self.app.goals.due_check_ins():
            self.check_in(goal.id)
            break  # one at a time; the next tick picks up the rest

    def _pick_goal_for_pass(self) -> Goal | None:
        """Overdue first, then the one that has waited longest."""
        candidates = [g for g in self.app.goals.list("active") if g.next_step is not None]
        candidates.sort(key=lambda g: (not g.overdue, g.updated_at))
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------ reminders
    def _watch_reminders(self) -> None:
        """New items from the tool belong to the chat they were set in, and the Upcoming
        view learns about them right away."""
        tool = self.app.tools.get("reminders")
        if isinstance(tool, Reminders):
            tool.thread_of = current_thread.get
            tool.on_change = lambda: self.bus.publish({"kind": "reminders"})

    def create_reminder(
        self, text: str, at: str = "", repeat: str = "", kind: str = "remind", thread: str = ""
    ) -> Reminder:
        item = self.app.reminders.create(
            text, at=at, repeat=repeat, kind=kind, thread=thread or MAIN_THREAD
        )
        self.bus.publish({"kind": "reminders"})
        return item

    def cancel_reminder(self, reminder_id: str) -> Reminder | None:
        item = self.app.reminders.cancel(reminder_id)
        if item is not None:
            self.bus.publish({"kind": "reminders"})
        return item

    def fire_reminder(self, reminder_id: str) -> Reminder:
        """Hand a reminder or routine to the agent now, in the chat it was set from."""
        item = self.app.reminders.get(reminder_id)
        if item is None:
            raise KeyError(reminder_id)
        if item.status != "active":
            raise ValueError(f"reminder is {item.status}")
        thread = item.thread if item.thread in self.threads else MAIN_THREAD
        now = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M")
        template = prompts.REMINDER_PROMPT if item.kind == "remind" else prompts.ROUTINE_PROMPT
        label = ("Reminder: " if item.kind == "remind" else "Routine: ") + _short(item.text)
        self.send(
            thread,
            template.format(now=now, text=item.text, quiet=prompts.QUIET_MARKER),
            source="reminder",
            label=label,
        )
        fired = self.app.reminders.mark_fired(item.id)
        self.bus.publish({"kind": "reminders"})
        return fired or item

    def _run_due_reminders(self) -> None:
        """A time the user named is kept whatever the proactivity level or the quiet hours;
        the message queues behind a conversation in progress rather than skipping."""
        for item in self.app.reminders.due():
            try:
                self.fire_reminder(item.id)
            except (KeyError, ValueError):  # pragma: no cover - raced with a cancel
                continue

    async def _goal_scheduler(self) -> None:
        self.schedule_next_pass()
        while True:
            try:
                self._run_due_reminders()
                self._run_due_check_ins()
                await self._refresh_calendar()
                due = self.next_goal_pass_at or datetime.now(UTC)
                remaining = (due - datetime.now(UTC)).total_seconds()
                if remaining > 0:
                    # short naps so a changed setting takes effect without a restart
                    await asyncio.sleep(min(remaining, 30))
                    continue
                self.schedule_next_pass()
                if not self.profile.proactive or self.profile.in_quiet_hours():
                    continue
                main = self.threads.get(MAIN_THREAD)
                if main is None or main.busy or not main.inbox.empty():
                    continue
                if self.memory_tidy_due():
                    # housekeeping takes this tick; the goal pass is next time
                    await self.tidy_memory()
                    continue
                goal = self._pick_goal_for_pass()
                if goal is not None:
                    self.advance_goal(goal.id)  # one goal per tick keeps the chat readable
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001  pragma: no cover
                logger.warning("goal scheduler error: {}", exc)
                await asyncio.sleep(30)

    # ------------------------------------------------------------------ calendar
    async def _refresh_calendar(self) -> None:
        """Fetch the calendar feeds when the cache is older than ``refresh_minutes``; the
        Feed and the system prompt read the cache. Runs whatever the proactivity level:
        it is the user's own data, not a background task."""
        cal = self.app.calendar
        if not cal.configured or not cal.stale():
            return
        before = cal.fetched_at
        await cal.refresh()
        if cal.fetched_at != before:
            self.bus.publish({"kind": "calendar", "calendar": self.calendar_view()})

    def calendar_view(self, days: int = 2) -> dict[str, Any]:
        """Today's and tomorrow's events with the feeds' status, for the app."""
        cal = self.app.calendar
        status = cal.status()
        today = datetime.now(cal.tz).date()
        items = cal.agenda(today, days) if cal.configured else []
        return {
            **status,
            "configured": cal.configured,
            "today": today.isoformat(),
            "events": [o.to_dict() for o in items],
        }

    # ------------------------------------------------------------------ memory tidy-up
    TIDY_MIN_LINES = 12  # nothing to tidy below this
    TIDY_EVERY_NEW = 8  # lines added since the last pass…
    TIDY_EVERY = timedelta(days=7)  # …or this long, whichever comes first

    def memory_tidy_due(self) -> bool:
        """A tidy-up is due when the store grew by a handful of lines since the last one,
        or a week went by — and never while one is running."""
        store = self.app.memory
        if store is None or self._tidying:
            return False
        count = store.count()
        if count < self.TIDY_MIN_LINES:
            return False
        last_at = store.get_meta("tidied_at")
        if not last_at or store.get_meta("tidy_more") == "1":
            return True
        if count - int(store.get_meta("tidied_count", "0") or 0) >= self.TIDY_EVERY_NEW:
            return True
        try:
            return datetime.now(UTC) - datetime.fromisoformat(last_at) >= self.TIDY_EVERY
        except ValueError:
            return True

    async def tidy_memory(self, dry_run: bool = False) -> dict[str, Any]:
        """One pass of ``memory.tidy``: merge duplicates, keep the newer fact, drop what
        was never a fact about the user. What changed goes to the Feed and to the log
        behind *Memory → Recent changes*, where each change can be undone."""
        store = self.app.memory
        if store is None:
            raise ValueError("memory is disabled")
        if self._tidying:
            raise ValueError("a tidy-up is already running")
        self._tidying = True
        try:
            report = await tidy(store, self.app.llm, dry_run=dry_run)
        finally:
            self._tidying = False
        if dry_run:
            return report.to_dict()
        store.set_meta("tidied_at", datetime.now(UTC).isoformat(timespec="seconds"))
        store.set_meta("tidied_count", str(store.count()))
        store.set_meta("tidy_more", "1" if report.more else "0")  # continue next tick
        self.bus.publish({"kind": "memory"})
        if report.changed:
            label = "Tidied memory"
            self.ui.emit(
                {
                    "type": "notice",
                    "level": "info",
                    "text": label,
                    "source": "memory",
                    "thread": MAIN_THREAD,
                }
            )
            summary = _tidy_summary(report, self.settings.agent.language)
            self.ui.emit(
                {
                    "type": "assistant",
                    "text": summary,
                    "thread": MAIN_THREAD,
                    "source": "background",
                    "about": label,
                    "final": True,
                }
            )
            self.threads[MAIN_THREAD].updated_at = now_iso()
        return report.to_dict()

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
        response = await self.app.llm.ask_complete([Message.user(prompt)], tools=None)
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
                    "path": p.relative_to(ws).as_posix(),
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

    # ------------------------------------------------------------------ feed / upcoming
    def feed(self, limit: int = 60) -> list[dict[str, Any]]:
        """What happened without you asking, newest first: one entry per background pass
        (its final reply, plus any file it made) and every card still waiting for you."""
        items: list[dict[str, Any]] = []
        for t in self.threads.values():
            items.extend(self._feed_of(t))
        items.sort(key=lambda i: i["ts"], reverse=True)
        return items[:limit]

    def _feed_of(self, t: Thread) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def item(ev: dict[str, Any], kind: str, title: str, text: str) -> dict[str, Any]:
            return {
                "id": ev["id"],
                "ts": ev["ts"],
                "kind": kind,
                "title": title,
                "text": text,
                "thread": t.id,
                "thread_title": t.title,
                "path": ev.get("path"),
                # a pass that found nothing worth interrupting you for
                "quiet": bool(ev.get("quiet")),
            }

        # A background pass is the notice that starts it followed by everything the agent
        # says or makes until you speak. Only its last word goes to the Feed — the
        # step-by-step narration stays in the chat.
        run: dict[str, Any] | None = None

        def flush() -> None:
            if run is None:
                return
            last = run["said"][-1] if run["said"] else None
            if last is not None:
                out.append(item(last, "background", run["label"], last.get("text", "")))
            elif t.busy and run is runs[-1]:
                out.append(item(run["start"], "background", run["label"], "Working on it…"))
            for art in run["made"]:
                out.append(item(art, "artifact", f"Made {art.get('name', 'a file')}", run["label"]))

        runs: list[dict[str, Any]] = []
        for ev in t.timeline.events:
            kind, src = ev.get("type"), ev.get("source")
            if kind == "approval":
                if ev.get("status") == "pending":
                    out.append(
                        item(ev, "approval", "Waiting for your approval", ev.get("summary", ""))
                    )
                continue
            if kind == "question":
                if ev.get("status") == "pending":
                    out.append(
                        item(
                            ev,
                            "question",
                            f"{self.profile.name} has a question",
                            ev.get("text", ""),
                        )
                    )
                continue
            if kind == "notice" and src not in (None, "background"):
                flush()
                run = {"label": ev.get("text", ""), "start": ev, "said": [], "made": []}
                runs.append(run)
            elif src == "background":
                if run is None:
                    run = {
                        "label": ev.get("about") or "While you were away",
                        "start": ev,
                        "said": [],
                        "made": [],
                    }
                    runs.append(run)
                if kind == "artifact":
                    run["made"].append(ev)
                elif kind in ("assistant", "notice"):
                    run["said"].append(ev)
            elif kind == "user":
                flush()
                run = None
        flush()
        return out

    def upcoming(self) -> dict[str, Any]:
        """What is scheduled: the next background pass and the goals it would work on."""
        active = [g for g in self.app.goals.list("active") if g.next_step is not None]
        active.sort(key=lambda g: (not g.overdue, g.updated_at))
        queue = [
            {
                "goal_id": g.id,
                "title": g.title,
                "category": g.category,
                "due": g.due or None,
                "overdue": g.overdue,
                "next_step": g.next_step.title if g.next_step else None,
                "progress": {
                    "done": sum(1 for s in g.steps if s.status in ("done", "skipped")),
                    "total": len(g.steps),
                },
            }
            for g in active
        ]
        check_ins = sorted(
            (
                {"goal_id": g.id, "title": g.title, "at": g.next_check_in, "cadence": g.check_in}
                for g in self.app.goals.list("active")
                if g.next_check_in
            ),
            key=lambda c: c["at"],
        )
        quiet_until = self.profile.quiet_hours_end()
        return {
            "check_ins": check_ins,
            "reminders": [r.to_dict() for r in self.app.reminders.list(None)],
            "proactive": self.profile.proactive,
            "proactivity": self.profile.proactivity,
            "interval_minutes": self.profile.goal_interval_minutes,
            "effective_interval_minutes": self.profile.interval_seconds // 60,
            "quiet_hours": self.profile.quiet_hours,
            "quiet_until": quiet_until.isoformat(timespec="seconds") if quiet_until else None,
            "next_pass_at": (
                self.next_goal_pass_at.isoformat(timespec="seconds")
                if self.next_goal_pass_at and self.profile.proactive
                else None
            ),
            "queue": queue,
            "busy": any(t.busy for t in self.threads.values()),
        }

    # ------------------------------------------------------------------ state snapshots
    def activity(self, n: int = 100) -> dict[str, Any]:
        s = self.app.sentinel
        s.grants.purge_expired()
        return {
            "audit": self.app.audit.tail(n),
            "grants": [g.to_dict() for g in s.active_grants()],
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
            "onboarded": bool(self.connections.data.get("onboarded")),
            "llm_ready": bool(s.llm.api_key and not self.app.vault.has_placeholders(s.llm.api_key))
            or bool(
                s.llm.base_url
                and "127.0.0.1" in s.llm.base_url
                or "localhost" in (s.llm.base_url or "")
            ),
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


def _tidy_summary(report: TidyReport, language: str = "auto") -> str:
    """The tidy-up as one chat message: what was merged and dropped, and where to undo it.

    Written in 中文 when that is the reply language, or when the language is "auto" and the
    memories themselves are Chinese; English otherwise (the two languages the app ships in).
    """
    n_m, n_d = len(report.merged), len(report.dropped)
    if language in ("", "auto"):
        text = " ".join(m.content for c in report.merged + report.dropped for m in c.before)
        zh = prompts.detect_language(text) == "Chinese"
    else:
        zh = language.lower().startswith(("中文", "zh", "chinese", "简体", "繁體"))
    if zh:
        parts = ([f"合并了 {n_m} 条"] if n_m else []) + ([f"删除了 {n_d} 条"] if n_d else [])
        head = "我整理了一下记忆——" + "，".join(parts) + "："
        tail = "每一处改动都可以在「记忆 → 最近的改动」里撤销。"
    else:
        parts = ([f"merged {n_m} line{'s' if n_m != 1 else ''}"] if n_m else []) + (
            [f"dropped {n_d}"] if n_d else []
        )
        head = "I tidied your memory — " + " and ".join(parts) + ":"
        tail = "Each change can be undone under Memory → Recent changes."
    body = "\n".join(f"- {line}" for line in report.lines(zh=zh))
    return f"{head}\n{body}\n\n{tail}"


def _short(text: str, limit: int = 60) -> str:
    """One line of ``text`` for a label."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _first_lines(text: str, limit: int = 200) -> str:
    """The first sentence or two of a reply, without markdown, for a notification body."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def goal_to_dict(g: Goal) -> dict[str, Any]:
    done = sum(1 for s in g.steps if s.status in ("done", "skipped"))
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "status": g.status,
        "notes": g.notes,
        "category": g.category,
        "due": g.due,
        "overdue": g.overdue,
        "check_in": g.check_in,
        "next_check_in": g.next_check_in or None,
        "proposal": g.proposal,
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


def _idea_objects(text: str) -> list[Any]:
    """The JSON objects in a model reply that should have been a JSON array.

    Usually it is one: ``[{...}, {...}]``, possibly inside a code fence. When the
    array does not parse — a real newline inside a string, a trailing comma, the
    reply cut off at max_tokens before the closing bracket — each ``{...}`` that
    parses on its own is kept, so one bad item does not cost the whole list.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1], strict=False)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder(strict=False)
    found: list[Any] = []
    pos = text.find("{")
    while pos >= 0:
        try:
            obj, stop = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            pos = text.find("{", pos + 1)
            continue
        found.append(obj)
        pos = text.find("{", stop)
    return found


def _parse_ideas(text: str) -> list[dict[str, str]]:
    ideas: list[dict[str, str]] = []
    for item in _idea_objects(text):
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
