"""The always-on OpenMuse: threads, background workers, goals scheduler, ideas, profile.

This is the piece that keeps working after you close the app. It owns one
:class:`~openmuse.app.OpenMuseApp` (LLM, tools, Sentinel, vault, memory, goals)
and runs one agent per *thread* — the main chat plus any side chats — so the
user can fire off several requests without waiting for the last one to finish.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as time_of_day
from pathlib import Path
from typing import Any

from openmuse import __version__, prompts
from openmuse.agent import Incoming, MuseAgent
from openmuse.app import OpenMuseApp
from openmuse.config import Settings
from openmuse.goals import Goal
from openmuse.llm import BaseLLM
from openmuse.logger import logger
from openmuse.memory.consolidate import TidyReport, tidy
from openmuse.reminders import Reminder
from openmuse.schema import Attachment, Message, Role
from openmuse.sentinel.grants import SCOPES
from openmuse.server.connections import Connections
from openmuse.server.events import MAIN_THREAD, EventBus, Timeline, new_id, now_iso
from openmuse.server.push import PushService
from openmuse.server.webui import WebUI, current_thread
from openmuse.tools.browser import Browser
from openmuse.tools.reminder_tools import Reminders
from openmuse.tools.trigger_tools import Triggers
from openmuse.triggers import MailWatcher, Trigger, matches

IDEAS_PROMPT = """You are {name}, the user's personal agent. Based on what you know about them, propose {n} concrete, genuinely useful things you could do for them right now. Prefer tasks you can actually complete with your tools (research, comparisons, planning, drafting, tracking, reminders, organising files, advancing their goals).

What you know:
{context}

Answer with a JSON array only, no prose. Each item: {{"title": "<short title, max 8 words>", "detail": "<one sentence on what you would do and why it helps>", "prompt": "<the exact request the user could send you to start>", "area": "<one of: planning, research, goals, money, health, home, learning, people, files, fun>"}}. Write in the user's language ({language})."""

IDEA_AREAS = (
    "planning",
    "research",
    "goals",
    "money",
    "health",
    "home",
    "learning",
    "people",
    "files",
    "fun",
)

FEED_PROMPT = """You are {name}, the user's personal agent, writing their personal feed: a few short posts made just for them, to read when they open the app. Think of a thoughtful friend who knows what they care about: a nudge on a goal, something worth knowing about a topic they follow, a small plan for the day, a question worth thinking about, a summary of something you noticed. Be specific to this person; never generic filler.

The user's feed instructions (what they want to read here, how often, in what tone):
{instructions}

What you know about them:
{context}

Write {n} posts. Answer with a JSON array only, no prose. Each item: {{"title": "<max 10 words>", "body": "<60-160 words of Markdown; short paragraphs or a list; no heading>", "area": "<one of: planning, research, goals, money, health, home, learning, people, files, fun>", "prompt": "<a request the user could send you to follow up, or empty>"}}. Write in the user's language ({language})."""

FEED_EVERY_HOURS = 24
FEED_KEEP = 200

STARTER_IDEAS = [
    {
        "title": "Plan my week",
        "detail": "Tell me what's on your plate and I'll turn it into a realistic plan with the important things first.",
        "prompt": "Help me plan my week. Ask me what I need to get done, then propose a schedule.",
        "area": "planning",
    },
    {
        "title": "Research & compare options",
        "detail": "Laptops, flights, insurance, a new phone plan — I'll gather the facts and compare them for you.",
        "prompt": "I need to make a purchase decision. Ask me what I'm choosing between, then research and compare the options.",
        "area": "research",
    },
    {
        "title": "Set up a long-term goal",
        "detail": "Share a goal (learn a language, run a 10k, save for a trip) and I'll break it into steps and keep track.",
        "prompt": "I want to set up a long-term goal. Ask me about it, then create a plan with concrete steps and track it.",
        "area": "goals",
    },
    {
        "title": "Tell me about yourself",
        "detail": "The more I know about your preferences, routines and constraints, the more useful I get. I'll remember what matters.",
        "prompt": "Ask me a few questions about myself so you can help me better, and remember the answers.",
        "area": "people",
    },
    {
        "title": "Build a quick tracker",
        "detail": "Spending, habits, workouts, reading — I can write a small script or document to track it for you.",
        "prompt": "Build me a simple tracker. Ask me what I want to track and how, then create it in the workspace.",
        "area": "files",
    },
]


PROACTIVITY = ("off", "low", "default", "high")
# how the configured interval stretches or shrinks per level
_INTERVAL_FACTOR = {"low": 2.0, "default": 1.0, "high": 0.5}
_QUIET_HOURS_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)-([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class Profile:
    name: str = "OpenMuse"
    # the face: one of the plush dolls shipped with the app (web/public/avatars), or "" for the emoji
    avatar: str = "sunny"
    emoji: str = "✨"
    color: str = "#0064d4"
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
            "avatar": self.avatar,
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
        p.name = (str(p.name).strip() or "OpenMuse")[:40]
        if "avatar" not in data:
            # a profile from before the dolls: keep the emoji it has
            p.avatar = ""
        p.avatar = re.sub(r"[^a-z0-9-]", "", str(p.avatar).lower())[:32]
        p.emoji = str(p.emoji)[:8] or "✨"
        p.color = str(p.color)[:16] or "#0064d4"
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
    inbox: asyncio.Queue[str | Incoming] = field(default_factory=asyncio.Queue)
    worker: asyncio.Task[None] | None = None
    stopping: bool = False
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
        self._mail_polled_at: float | None = None
        self._fired_pruned_at: float | None = None
        self.mail_checked_at: str | None = None
        self.mail_watch_error = ""
        self._watch_triggers()
        self.connections = Connections(self)
        self.token = self._load_token()
        self._scheduler: asyncio.Task[None] | None = None
        self._tidying = False
        self._writing_feed = False
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
            contacts=self.app.contacts,
            skills=self.app.skills,
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

    def stop_thread(self, thread_id: str) -> bool:
        """The stop button: end the run in progress and drop what was queued behind it.
        The conversation stays; a pending approval or question closes unanswered."""
        thread = self.threads.get(thread_id)
        if thread is None or not thread.busy or thread.worker is None or thread.worker.done():
            return False
        while not thread.inbox.empty():
            thread.inbox.get_nowait()
        for ev in list(thread.timeline.tail(50)):
            if ev.get("type") in ("approval", "question") and ev.get("status") == "pending":
                self.ui.patch(thread_id, ev["id"], status="expired")
        thread.stopping = True
        thread.worker.cancel()
        return True

    def _settle_stopped(self, thread: Thread) -> None:
        """After a cancelled run: the transcript must not end on a tool call the model never
        saw answered, and the agent goes back to idle so the next message runs cleanly."""
        agent = thread.agent
        msgs = agent.messages
        while msgs and msgs[-1].role == Role.TOOL:
            msgs.pop()
        if msgs and msgs[-1].role == Role.ASSISTANT and msgs[-1].tool_calls:
            for tc in msgs[-1].tool_calls:
                msgs.append(
                    Message.tool("Stopped by the user before this ran.", tc.id, tc.function.name)
                )
        agent.state = agent.state.__class__.IDLE
        agent._save_session()
        thread.stopping = False
        self.ui.emit({"type": "notice", "level": "info", "text": "Stopped.", "thread": thread.id})

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
        self,
        thread_id: str,
        text: str,
        source: str = "user",
        label: str = "",
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Queue a message for a thread. Returns the timeline event that was created.

        ``files`` are workspace paths of attachments (uploaded first with ``save_upload``);
        a message may be attachments alone."""
        text = text.strip()
        attachments = [self.attachment(path) for path in files or []]
        if not text and not attachments:
            raise ValueError("empty message")
        thread = self.threads.get(thread_id) or self._make_thread(thread_id, thread_id)
        thread.updated_at = now_iso()
        if source == "user":
            event_data: dict[str, Any] = {"type": "user", "text": text, "thread": thread_id}
            if attachments:
                event_data["files"] = [a.model_dump() for a in attachments]
            event = self.ui.emit(event_data)
            self.bus.publish({"kind": "thread", "thread": thread.meta()})
            if not attachments and self.ui.answer_question(thread_id, text):
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
        thread.inbox.put_nowait(Incoming(text, attachments) if attachments else text)
        self._ensure_worker(thread)
        return event

    # ------------------------------------------------------------------ attachments
    def attachment(self, rel: str) -> Attachment:
        """An attachment record for a file in the workspace (the path as the app has it)."""
        target = self.resolve_workspace_path(rel)
        if not target.is_file():
            raise ValueError(f"no such file: {rel}")
        path = target.relative_to(self.workspace()).as_posix()
        return Attachment(
            path=path,
            name=target.name,
            size=target.stat().st_size,
            kind=Attachment.kind_of(target.name),
            mime=mimetypes.guess_type(target.name)[0] or "",
        )

    def save_upload(self, name: str, data: bytes) -> Attachment:
        """A file from the phone into ``attachments/<date>/`` in the workspace, under a
        safe version of its name (a second file with the same name gets a suffix)."""
        limit = self.settings.server.max_upload_mb * 1024 * 1024
        if len(data) > limit:
            raise ValueError(f"file is larger than {self.settings.server.max_upload_mb} MB")
        safe = re.sub(
            r"[^\w.\- ()\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", "_", Path(name).name
        ).strip(" ._")
        safe = safe[:120] or "file"
        folder = self.workspace() / "attachments" / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / safe
        stem, suffix = target.stem, target.suffix
        n = 2
        while target.exists():
            target = folder / f"{stem} ({n}){suffix}"
            n += 1
        target.write_bytes(data)
        return self.attachment(target.relative_to(self.workspace()).as_posix())

    def _ensure_worker(self, thread: Thread) -> None:
        if thread.worker is None or thread.worker.done():
            thread.worker = asyncio.create_task(self._worker(thread), name=f"thread-{thread.id}")

    async def _worker(self, thread: Thread) -> None:
        token = current_thread.set(thread.id)
        try:
            while not thread.inbox.empty():
                item = thread.inbox.get_nowait()
                incoming = item if isinstance(item, Incoming) else Incoming(item)
                text = incoming.text
                thread.busy = True
                thread.agent.inbox = thread.inbox
                self.bus.publish({"kind": "thread", "thread": thread.meta()})
                self.ui.set_status("working", "Thinking…", thread.id)
                try:
                    purpose = thread.purposes.pop(text, None)
                    self.ui.begin_run(thread.id, background=purpose)
                    final = await thread.agent.run(text, purpose=purpose, files=incoming.files)
                    quiet, final = (
                        prompts.split_quiet(final or "") if purpose else (False, final or "")
                    )
                    self._finish_run(thread, purpose, final.strip(), quiet)
                except asyncio.CancelledError:
                    if thread.stopping:
                        self._settle_stopped(thread)
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
        elif about.startswith(("New mail: ", "Coming up: ", "Webhook: ")):
            title = f"{name} · {about.split(': ', 1)[0].lower()}"
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

    # ------------------------------------------------------------------ triggers
    def _watch_triggers(self) -> None:
        """Triggers set from the chat belong to that chat; the app and the inbox watcher
        learn about a new one right away."""
        tool = self.app.tools.get("triggers")
        if isinstance(tool, Triggers):
            tool.thread_of = current_thread.get
            tool.on_change = self._triggers_changed
            tool.available = self.app.trigger_kinds
            tool.base_url = self.base_url()

    def _triggers_changed(self) -> None:
        self._mail_polled_at = None  # look at the inbox on the next tick
        self.bus.publish({"kind": "triggers"})

    def base_url(self) -> str:
        """Where this server is reached — the address a webhook is given."""
        from openmuse.server import lan_ip  # here: the package imports this module

        s = self.settings.server
        host = s.host if s.host not in ("", "0.0.0.0", "::") else (lan_ip() or "127.0.0.1")
        return f"http://{host}:{s.port}"

    def hook_url(self, trigger: Trigger) -> str:
        return f"{self.base_url()}/api/hooks/{trigger.id}?key={trigger.secret}"

    def create_trigger(
        self, kind: str, text: str, match: str = "", lead_minutes: int = 30, thread: str = ""
    ) -> Trigger:
        have = self.app.trigger_kinds()
        if not have.get(kind, True):
            raise ValueError(
                "connect a mailbox first" if kind == "mail" else "add a calendar first"
            )
        item = self.app.triggers.create(
            kind, text, match=match, lead_minutes=lead_minutes, thread=thread or MAIN_THREAD
        )
        self._triggers_changed()
        return item

    def cancel_trigger(self, trigger_id: str) -> Trigger | None:
        item = self.app.triggers.cancel(trigger_id)
        if item is not None:
            self.bus.publish({"kind": "triggers"})
        return item

    def fire_trigger(
        self, trigger_id: str, what: str, context: str = "", key: str = "", title: str = ""
    ) -> Trigger | None:
        """Hand a trigger to the agent now, with what happened as context, in the chat it
        was set from. ``key`` names the occurrence (a mail's UID, an event's start, a
        delivery id): the same key never fires twice, so this returns None the second time.
        ``title`` is the short form for the Feed (the subject, the event, the hook's name)."""
        item = self.app.triggers.get(trigger_id)
        if item is None:
            raise KeyError(trigger_id)
        if item.status != "active":
            raise ValueError(f"trigger is {item.status}")
        if not self.app.triggers.mark_fired(item.id, key or new_id()):
            return None
        thread = item.thread if item.thread in self.threads else MAIN_THREAD
        now = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M")
        prefix = {"mail": "New mail: ", "event": "Coming up: ", "hook": "Webhook: "}[item.kind]
        context = context.strip()[:6000]
        block = f"{_fence(context)}\n{context}\n{_fence(context)}\n\n" if context else ""
        if item.kind != "hook":
            # the mail or the event is the user's private data: from here on, sending
            # anything to a host that is not allowlisted is an approval
            self.app.sentinel.tainted = True
        self.send(
            thread,
            prompts.TRIGGER_PROMPT.format(
                now=now, what=what, context=block, text=item.text, quiet=prompts.QUIET_MARKER
            ),
            source="trigger",
            label=prefix + _short(title or item.match or what),
        )
        self.bus.publish({"kind": "triggers"})
        return self.app.triggers.get(item.id) or item

    def deliver_hook(self, trigger_id: str, key: str, body: str, content_type: str = "") -> Trigger:
        """A request to a trigger's webhook URL. Wrong id or key → KeyError (the caller
        answers 404 for both, so the URL cannot be probed); too soon → RuntimeError."""
        item = self.app.triggers.get(trigger_id)
        if item is None or item.kind != "hook" or not secrets.compare_digest(item.secret, key):
            raise KeyError(trigger_id)
        if item.status != "active":
            raise ValueError(f"trigger is {item.status}")
        if item.last_fired_at:
            since = datetime.now(UTC) - datetime.fromisoformat(item.last_fired_at)
            if since.total_seconds() < self.settings.triggers.hook_min_seconds:
                raise RuntimeError("too soon after the last delivery")
        body = body.strip()
        if content_type.startswith("application/json") and body:
            try:
                body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        name = item.match or item.id
        what = f"Webhook “{name}” was called" + (" with:" if body else " (empty body).")
        fired = self.fire_trigger(
            item.id, what=what, context=body, key=f"hook:{new_id()}", title=name
        )
        return fired or item

    def _mail_mark(self) -> str:
        """The meta key of the inbox high-water mark — one per mailbox, so a changed
        account starts fresh instead of replaying by UID."""
        email = self.settings.connectors.email
        account = self.app.vault.resolve(email.address, strict=False) or email.address
        return f"mail_uid:{email.imap_host}:{account}"

    async def _poll_mail(self) -> None:
        """Look at the inbox for the mail triggers, every ``mail_poll_minutes`` while at
        least one is active. Each new mail is offered to every mail trigger; a trigger
        fires once per mail."""
        triggers = self.app.triggers.active("mail")
        if not triggers:
            return
        email = self.settings.connectors.email
        watcher = MailWatcher(email, vault=self.app.vault)
        if not watcher.configured:
            return
        now = time.monotonic()
        every = max(1, self.settings.triggers.mail_poll_minutes) * 60
        if self._mail_polled_at is not None and now - self._mail_polled_at < every:
            return
        self._mail_polled_at = now
        store = self.app.triggers
        mark = self._mail_mark()
        last = int(store.get_meta(mark, "0") or 0)
        try:
            fresh, newest = await watcher.look(last)
        except (RuntimeError, OSError) as exc:
            self.mail_watch_error = str(exc)[:200]
            logger.warning("mail triggers: {}", exc)
            return
        self.mail_watch_error = ""
        self.mail_checked_at = now_iso()
        store.set_meta(mark, str(newest))
        for mail in fresh:
            for trig in triggers:
                if matches(trig.match, mail.sender, mail.subject):
                    self.fire_trigger(
                        trig.id,
                        what=f"New mail from {mail.sender}: {mail.subject or '(no subject)'}",
                        context=mail.render(),
                        key=mail.key,
                        title=mail.subject or mail.sender,
                    )
        self.bus.publish({"kind": "triggers"})

    def _run_event_triggers(self) -> None:
        """Fire event triggers ``lead_minutes`` before a matching event; an event that has
        already begun is left alone (a late brief helps no one)."""
        triggers = self.app.triggers.active("event")
        cal = self.app.calendar
        if not triggers or not cal.configured:
            return
        now = datetime.now(cal.tz)
        h, m = (int(x) for x in self.settings.connectors.calendar.day_start.split(":"))
        for occ in cal.agenda(now.date(), 3):  # a lead can be a day
            start = occ.start.astimezone(cal.tz)
            if occ.all_day:
                # an all-day event "starts" when the working day does, not at midnight
                start = datetime.combine(occ.start.date(), time_of_day(h, m), tzinfo=cal.tz)
            if start <= now:
                continue
            for trig in triggers:
                if not matches(trig.match, occ.summary, occ.location):
                    continue
                if now < start - timedelta(minutes=trig.lead_minutes):
                    continue
                minutes = max(1, int((start - now).total_seconds() // 60))
                when = "all day" if occ.all_day else f"{start:%H:%M}"
                where = f" · {occ.location}" if occ.location else ""
                self.fire_trigger(
                    trig.id,
                    what=f"Coming up: {occ.summary} — {start:%a %Y-%m-%d} {when}{where} (in {minutes} min)",
                    context=cal.render([occ], now.date())
                    + (f"\n\n{occ.description}" if occ.description else ""),
                    key=f"{occ.uid}:{occ.start.isoformat()}",
                    title=occ.summary,
                )

    def _prune_fired(self) -> None:
        """Firing records (a mail's UID, an event's start) are only needed until the
        occurrence is long past; drop the ones older than 90 days, once a day."""
        now = time.monotonic()
        if self._fired_pruned_at is not None and now - self._fired_pruned_at < 86400:
            return
        self._fired_pruned_at = now
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat(timespec="seconds")
        self.app.triggers.forget_fired_before(cutoff)

    def triggers_view(self) -> dict[str, Any]:
        items = []
        for t in self.app.triggers.list(None):
            d = t.to_dict()
            if t.kind == "hook":
                d["url"] = self.hook_url(t) if t.status == "active" else ""
            items.append(d)
        available = self.app.trigger_kinds()
        mail_error = self.mail_watch_error
        if not available["mail"] and any(
            t.kind == "mail" and t.status == "active" for t in self.app.triggers.list("active")
        ):
            mail_error = "no mailbox is connected"
        return {
            "items": items,
            "available": available,
            "mail_checked_at": self.mail_checked_at,
            "mail_error": mail_error,
            "mail_poll_minutes": self.settings.triggers.mail_poll_minutes,
        }

    async def _goal_scheduler(self) -> None:
        self.schedule_next_pass()
        while True:
            try:
                self._run_due_reminders()
                self._run_due_check_ins()
                await self._refresh_calendar()
                self._run_event_triggers()
                await self._poll_mail()
                self._prune_fired()
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
                if self.feed_posts_due():
                    await self.write_feed_posts()
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

    # ------------------------------------------------------------------ skills
    def skills_view(self) -> dict[str, Any]:
        lib = self.app.skills
        return {**lib.status(), "skills": [s.to_dict() for s in lib.all()]}

    def skill_view(self, name: str) -> dict[str, Any] | None:
        skill = self.app.skills.get(name)
        return skill.to_dict(body=True) if skill else None

    def save_skill(self, content: str, name: str = "") -> dict[str, Any]:
        """A skill from the text of a SKILL.md, written or pasted in the app."""
        skill = self.app.skills.save_text(content, name=name)
        self._publish_skills()
        return skill.to_dict(body=True)

    async def import_skill(self, url: str) -> dict[str, Any]:
        """A skill from a link to a SKILL.md — a raw file link, or a GitHub folder or file
        page, which is turned into one."""
        from openmuse.skills import fetch_skill_text

        skill = self.app.skills.save_text(await fetch_skill_text(url))
        self._publish_skills()
        return skill.to_dict(body=True)

    def remove_skill(self, name: str) -> bool:
        ok = self.app.skills.remove(name)
        if ok:
            self._publish_skills()
        return ok

    def set_skill_enabled(self, name: str, enabled: bool) -> dict[str, Any] | None:
        skill = self.app.skills.set_enabled(name, enabled)
        if skill is None:
            return None
        data = self.connections.data
        data["skills"] = {"disabled": list(self.settings.skills.disabled)}
        self.connections._save()
        self._publish_skills()
        return skill.to_dict()

    def _publish_skills(self) -> None:
        self.bus.publish({"kind": "skills", "skills": self.skills_view()})
        # the avatar menu shows the counts from the settings view
        self.bus.publish({"kind": "settings", "settings": self.settings_view()})

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

    # ------------------------------------------------------------------ feed posts
    def _feed_file(self) -> Path:
        return self.data_dir / "feed_posts.json"

    def feed_posts(self) -> dict[str, Any]:
        """The posts written for the user so far, newest first, and their feed instructions."""
        path = self._feed_file()
        if path.exists():
            try:
                data = json.loads(path.read_text("utf-8"))
                if isinstance(data, dict):
                    data.setdefault("instructions", "")
                    data.setdefault("generated_at", None)
                    data.setdefault("posts", [])
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {"instructions": "", "generated_at": None, "posts": []}

    def _save_feed(self, data: dict[str, Any]) -> None:
        data["posts"] = data["posts"][:FEED_KEEP]
        self._feed_file().write_text(json.dumps(data, ensure_ascii=False), "utf-8")

    def set_feed_instructions(self, text: str) -> dict[str, Any]:
        data = self.feed_posts()
        data["instructions"] = text.strip()[:2000]
        self._save_feed(data)
        self.bus.publish({"kind": "feed_posts"})
        return data

    def delete_feed_post(self, post_id: str) -> bool:
        data = self.feed_posts()
        before = len(data["posts"])
        data["posts"] = [p for p in data["posts"] if p.get("id") != post_id]
        if len(data["posts"]) == before:
            return False
        self._save_feed(data)
        self.bus.publish({"kind": "feed_posts"})
        return True

    def feed_posts_due(self) -> bool:
        """New posts are due once a day while background work is on — and only once there
        is something to write from (memory, a goal, or instructions from the user)."""
        if self._writing_feed:
            return False
        data = self.feed_posts()
        known = bool(data["instructions"]) or bool(self.app.goals.list("active"))
        if not known and self.app.memory is not None:
            known = self.app.memory.count() >= 5
        if not known:
            return False
        last = data.get("generated_at")
        if not last:
            return True
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(last)
        except ValueError:
            return True
        return age >= timedelta(hours=FEED_EVERY_HOURS)

    def _feed_context(self) -> list[str]:
        lines: list[str] = []
        if self.settings.agent.user_profile.strip():
            lines.append(f"- profile: {self.settings.agent.user_profile.strip()[:500]}")
        if self.profile.user_name:
            lines.append(f"- the user's name: {self.profile.user_name}")
        if self.app.memory is not None:
            for m in self.app.memory.all(limit=40):
                lines.append(f"- memory ({m.category}): {m.content}")
        for g in self.app.goals.list("active")[:8]:
            nxt = g.next_step
            lines.append(
                f"- goal: {g.title} (progress {g.progress}"
                + (f", next: {nxt.title}" if nxt else "")
                + ")"
            )
        cal = self.app.calendar
        if cal.configured:
            today = datetime.now().astimezone().date()
            if agenda := cal.agenda(today)[:8]:
                lines.append("- today on the calendar:\n" + cal.render(agenda, today))
        main = self.threads.get(MAIN_THREAD)
        if main is not None:
            recent = [e for e in main.timeline.events if e.get("type") in ("user", "assistant")][
                -6:
            ]
            for e in recent:
                lines.append(f"- recent {e['type']}: {str(e.get('text', ''))[:200]}")
        lines.append(f"- today's date: {datetime.now().strftime('%A %d %B %Y')}")
        return lines

    async def write_feed_posts(self, n: int = 3) -> dict[str, Any]:
        """Write a fresh batch of posts and notify the phone once about the first."""
        if self._writing_feed:
            return self.feed_posts()
        self._writing_feed = True
        try:
            data = self.feed_posts()
            language = self.settings.agent.language
            prompt = FEED_PROMPT.format(
                name=self.profile.name,
                n=n,
                instructions=data["instructions"]
                or "(none yet — write what a good personal agent would)",
                context="\n".join(self._feed_context()),
                language="the same language as the context above"
                if language in ("", "auto")
                else language,
            )
            response = await self.app.llm.ask_complete([Message.user(prompt)], tools=None)
            posts = _parse_posts(response.content or "")
            now = now_iso()
            for p in posts:
                p["id"] = new_id("post")
                p["ts"] = now
            data["posts"] = [*posts, *data["posts"]]
            data["generated_at"] = now
            self._save_feed(data)
            self.bus.publish({"kind": "feed_posts"})
            if posts:
                self.push.notify(
                    f"{self.profile.name} · {posts[0]['title']}",
                    _first_lines(posts[0]["body"]),
                    tag="feed-posts",
                    url=self._push_url(MAIN_THREAD).split("?")[0] + "?tab=feed",
                    kind="background",
                )
            return data
        finally:
            self._writing_feed = False

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
            "triggers": self.triggers_view(),
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
        skills = self.app.skills.status()
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
            "sandbox": {
                "mode": s.sandbox.mode,
                "active": self.app.sandbox.active,
                "status": self.app.sandbox.status,
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
                "calendar": s.connectors.calendar.enabled and bool(s.connectors.calendar.feeds),
                "contacts": s.connectors.contacts.enabled and self.app.contacts.configured,
                "browser": s.browser.enabled,
                "mcp": [m.name for m in s.mcp.servers],
            },
            "tools": [
                {"name": t.name, "risk": t.risk.value, "description": t.description[:160]}
                for t in self.app.tools
            ],
            "memory_enabled": s.memory.enabled,
            "skills": {
                "enabled": s.skills.enabled,
                "count": skills["count"],
                "yours": skills["yours"],
            },
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


def _fence(text: str) -> str:
    """A code fence the text cannot close: one backtick more than its longest run."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


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
            area = str(item.get("area", "")).strip().lower()
            ideas.append(
                {
                    "title": title[:80],
                    "detail": str(item.get("detail", "")).strip()[:300],
                    "prompt": prompt[:1000],
                    "area": area if area in IDEA_AREAS else "fun",
                }
            )
    return ideas[:8]


def _parse_posts(text: str) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    for item in _idea_objects(text):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        if title and body:
            area = str(item.get("area", "")).strip().lower()
            posts.append(
                {
                    "title": title[:120],
                    "body": body[:2000],
                    "area": area if area in IDEA_AREAS else "fun",
                    "prompt": str(item.get("prompt", "")).strip()[:1000],
                }
            )
    return posts[:6]


__all__ = ["MuseService", "Profile", "Thread", "goal_to_dict", "new_id"]
