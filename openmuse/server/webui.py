"""A :class:`openmuse.ui.UI` implementation that speaks *events* instead of printing.

One ``WebUI`` serves every thread. The thread an agent callback belongs to is
carried in a :mod:`contextvars` variable set by the worker task, so several
threads (main chat + side chats) can run at the same time and still land their
bubbles, tool chips and approval cards in the right place.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openmuse.logger import logger
from openmuse.prompts import split_quiet
from openmuse.schema import ToolCall, ToolResult
from openmuse.server.events import MAIN_THREAD, EventBus, Timeline, new_id, now_iso
from openmuse.ui import ApprovalDecision, ApprovalRequest

current_thread: contextvars.ContextVar[str] = contextvars.ContextVar(
    "openmuse_thread", default=MAIN_THREAD
)

_TOOL_LABELS = {
    "web_search": "Searching the web",
    "web_fetch": "Reading a web page",
    "files": "Working with files",
    "shell": "Running a command",
    "python_execute": "Running Python",
    "read_emails": "Reading email",
    "send_email": "Sending email",
    "browser": "Browsing",
    "goals": "Updating goals",
    "remember": "Saving a memory",
    "recall": "Recalling memories",
    "forget": "Forgetting a memory",
    "ask_user": "Waiting for you",
    "terminate": "Wrapping up",
}

# Tools that cannot create files; no point scanning the workspace around them.
_READ_ONLY_TOOLS = {
    "web_search",
    "web_fetch",
    "recall",
    "remember",
    "forget",
    "goals",
    "ask_user",
    "terminate",
    "read_emails",
    "send_email",
}
_SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", ".git"}
_SCAN_CAP = 3000


class WebUI:
    """Turns agent callbacks into timeline events + live WebSocket messages."""

    def __init__(
        self,
        bus: EventBus,
        get_timeline: Callable[[str], Timeline],
        approval_timeout: float = 3600.0,
        show_thinking: bool = False,
        workspace: Path | None = None,
        exclude: tuple[Path, ...] = (),
    ):
        self.bus = bus
        self.get_timeline = get_timeline
        self.approval_timeout = approval_timeout
        self.show_thinking = show_thinking
        self.workspace = workspace
        # directories inside the workspace that are OpenMuse's own (the data dir, when
        # someone points both at the same place) — never artifacts
        self.exclude = tuple(p.resolve() for p in exclude)
        # workspace snapshot taken before a tool ran, per thread; files that are new or
        # changed afterwards become artifact cards — whatever tool wrote them
        self._ws_before: dict[str, dict[str, float] | None] = {}
        # artifact events already shown in the current run: path -> event id
        self._artifacts: dict[str, dict[str, str]] = {}
        self.pending_approvals: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self.pending_questions: dict[str, asyncio.Future[str]] = {}  # thread -> future
        self.status: dict[str, dict[str, Any]] = {}
        # streaming state per thread
        self._stream_ids: dict[str, str] = {}
        self._stream_buf: dict[str, str] = {}
        self._tool_events: dict[str, str] = {}  # tool call id -> event id
        self.last_assistant_text: dict[str, str] = {}
        self._step_text: dict[str, str] = {}  # text of the response currently being handled
        # threads whose final reply is already on screen (text + terminate in one response)
        self.reply_shown: set[str] = set()
        # threads currently running background work (goal passes…) → the label of that work.
        # Events emitted meanwhile are tagged so the Feed can show what happened while you
        # were away.
        self.background: dict[str, str] = {}
        # called with every persisted event; the service decides what deserves a push
        self.on_event: Callable[[dict[str, Any]], None] | None = None

    # ------------------------------------------------------------------ run lifecycle
    def begin_run(self, thread: str, background: str | None = None) -> None:
        """Called by the service before each agent run in ``thread``."""
        self.reply_shown.discard(thread)
        self._artifacts[thread] = {}
        if background:
            self.background[thread] = background
        else:
            self.background.pop(thread, None)

    def end_run(self, thread: str) -> None:
        self.background.pop(thread, None)
        self._ws_before.pop(thread, None)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def thread() -> str:
        return current_thread.get()

    def _scan_workspace(self) -> dict[str, float] | None:
        """Relative path → mtime for every visible file, or None when the workspace is
        too big to diff cheaply (then only the files tool announces artifacts)."""
        ws = self.workspace
        if ws is None or not ws.is_dir():
            return None
        out: dict[str, float] = {}
        for root, dirs, files in os.walk(ws):
            here = Path(root)
            if any(here == x or x in here.parents for x in self.exclude):
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS]
            for name in files:
                if name.startswith("."):
                    continue
                p = Path(root) / name
                try:
                    out[p.relative_to(ws).as_posix()] = p.stat().st_mtime
                except OSError:
                    continue
                if len(out) > _SCAN_CAP:
                    return None
        return out

    def _announce_artifact(self, thread: str, rel: str, action: str) -> None:
        seen = self._artifacts.setdefault(thread, {})
        if rel in seen:
            # the same file touched again in this run: refresh the card, don't stack another
            self.patch(thread, seen[rel], action="update", updated_ts=now_iso())
            return
        ev = self.emit(
            {
                "type": "artifact",
                "path": rel,
                "name": rel.rsplit("/", 1)[-1],
                "action": action,
                "thread": thread,
            }
        )
        seen[rel] = ev["id"]

    def emit(self, event: dict[str, Any], persist: bool = True) -> dict[str, Any]:
        thread = event.get("thread") or self.thread()
        event["thread"] = thread
        if thread in self.background and "source" not in event:
            event["source"] = "background"
            event["about"] = self.background[thread]
        if persist:
            event = self.get_timeline(thread).add(event)
        else:
            event.setdefault("id", new_id())
            event.setdefault("ts", now_iso())
        self.bus.publish({"kind": "event", "event": event})
        if persist and self.on_event is not None:
            try:
                self.on_event(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("event hook failed: {}", exc)
        return event

    def patch(self, thread: str, event_id: str, **fields: Any) -> None:
        ev = self.get_timeline(thread).update(event_id, **fields)
        if ev is not None:
            self.bus.publish({"kind": "update", "event": ev})

    def set_status(self, state: str, detail: str = "", thread: str | None = None) -> None:
        thread = thread or self.thread()
        self.status[thread] = {"thread": thread, "state": state, "detail": detail, "ts": now_iso()}
        self.bus.publish({"kind": "status", "status": self.status[thread]})

    def overall_status(self) -> dict[str, Any]:
        """What the avatar shows: the busiest thread wins, main chat breaks ties."""
        working = [s for s in self.status.values() if s["state"] != "idle"]
        if not working:
            return {"state": "idle", "detail": "", "thread": MAIN_THREAD}
        working.sort(key=lambda s: (s["thread"] != MAIN_THREAD, s["ts"]))
        return working[0]

    # ------------------------------------------------------------------ UI protocol
    def on_text_delta(self, text: str) -> None:
        if not text:
            return
        thread = self.thread()
        sid = self._stream_ids.get(thread)
        if sid is None:
            sid = new_id("a")
            self._stream_ids[thread] = sid
            self._stream_buf[thread] = ""
            self.bus.publish({"kind": "stream_start", "thread": thread, "id": sid, "ts": now_iso()})
        self._stream_buf[thread] = self._stream_buf.get(thread, "") + text
        self.bus.publish({"kind": "delta", "thread": thread, "id": sid, "text": text})

    def on_assistant_message(self, content: str | None, reasoning: str | None) -> None:
        thread = self.thread()
        sid = self._stream_ids.pop(thread, None)
        self._stream_buf.pop(thread, None)
        if sid is not None:
            self.bus.publish({"kind": "stream_end", "thread": thread, "id": sid})
        text = (content or "").strip()
        quiet = False
        if thread in self.background:
            quiet, text = split_quiet(text)
            text = text.strip()
        if not text and not (self.show_thinking and reasoning):
            return
        event: dict[str, Any] = {"id": sid or new_id("a"), "type": "assistant", "text": text}
        if quiet:
            event["quiet"] = True
        if self.show_thinking and reasoning:
            event["reasoning"] = reasoning.strip()
        self.last_assistant_text[thread] = text
        self._step_text[thread] = text
        self.emit(event)

    def on_tool_call(self, call: ToolCall, summary: str) -> None:
        thread = self.thread()
        if call.name in ("terminate", "ask_user"):
            # The final summary becomes the assistant bubble and questions get their own
            # card — a chip for either would only duplicate them.
            if call.name == "terminate" and self._step_text.get(thread):
                # The model already said its piece in the same response; the summary it
                # hands to terminate would be the same thing twice.
                self.reply_shown.add(thread)
            self.set_status("working", _TOOL_LABELS.get(call.name, "Working…"), thread)
            return
        self._step_text.pop(thread, None)
        args = call.arguments if isinstance(call.arguments, dict) else {}
        ev = self.emit(
            {
                "type": "tool",
                "tool": call.name,
                "summary": summary,
                "args": _preview_args(args),
                "status": "running",
            }
        )
        self._tool_events[call.id] = ev["id"]
        if call.name not in _READ_ONLY_TOOLS:
            self._ws_before[thread] = self._scan_workspace()
        label = _TOOL_LABELS.get(call.name, f"Using {call.name}")
        self.set_status("working", f"{label}: {summary}" if summary else label, thread)

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        thread = self.thread()
        eid = self._tool_events.pop(call.id, None)
        status = (
            "ok"
            if result.ok
            else ("blocked" if "Sentinel blocked" in (result.error or "") else "error")
        )
        preview = (result.output or result.error or "")[:600]
        if eid:
            self.patch(thread, eid, status=status, output=preview)
        if result.ok and call.name not in _READ_ONLY_TOOLS:
            self._announce_new_files(thread, call)
        # Let the Goals / Memory tabs refresh when the agent changed them.
        if result.ok and call.name == "goals":
            self.bus.publish({"kind": "goals"})
        elif result.ok and call.name in ("remember", "forget"):
            self.bus.publish({"kind": "memory"})
        if call.name != "terminate":
            self.set_status("working", "Thinking…", thread)

    def _announce_new_files(self, thread: str, call: ToolCall) -> None:
        """Every file a tool created or changed in the workspace becomes an artifact card:
        a page from python_execute, a PDF from a shell command, a note from files."""
        before = self._ws_before.pop(thread, None)
        after = self._scan_workspace() if before is not None else None
        if before is not None and after is not None:
            for rel, mtime in after.items():
                if before.get(rel) != mtime:
                    self._announce_artifact(thread, rel, "write" if rel not in before else "update")
            return
        # no cheap diff available: fall back to what the files tool tells us
        if call.name == "files":
            args = call.arguments if isinstance(call.arguments, dict) else {}
            path = str(args.get("path") or "")
            if args.get("action") in ("write", "append") and path:
                if self.workspace is not None and Path(path).is_absolute():
                    try:
                        path = Path(path).resolve().relative_to(self.workspace.resolve()).as_posix()
                    except ValueError:
                        return
                self._announce_artifact(thread, path, str(args["action"]))

    def on_sentinel(self, decision: str, summary: str, reasons: list[str]) -> None:
        if decision == "deny":
            self.emit(
                {
                    "type": "notice",
                    "level": "warn",
                    "text": f"Sentinel blocked: {summary}"
                    + (f" — {'; '.join(reasons)}" if reasons else ""),
                }
            )

    def info(self, message: str) -> None:
        self.emit({"type": "notice", "level": "info", "text": message})

    def warn(self, message: str) -> None:
        self.emit({"type": "notice", "level": "warn", "text": message})

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        thread = self.thread()
        approval_id = new_id("ap")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ApprovalDecision] = loop.create_future()
        # registered before the card goes out, so whoever reacts to the event (push badge)
        # already counts it
        self.pending_approvals[approval_id] = fut
        ev = self.emit(
            {
                "id": approval_id,
                "type": "approval",
                "tool": request.tool,
                "summary": request.summary,
                "risk": request.risk.value,
                "reasons": request.reasons,
                "warnings": request.warnings,
                "egress_target": request.egress_target,
                "purpose": request.purpose,
                "target": request.target,
                "grant_key": request.grant_key,
                "grant_options": list(request.grant_options),
                "args": _preview_args(request.args),
                "status": "pending",
            }
        )
        self.set_status("waiting", f"Needs your approval: {request.summary}", thread)
        try:
            decision = await asyncio.wait_for(fut, timeout=self.approval_timeout)
        except TimeoutError:
            decision = ApprovalDecision(approved=False, reason="no answer (timed out)")
            self.patch(thread, ev["id"], status="expired")
        finally:
            self.pending_approvals.pop(approval_id, None)
        self.set_status("working", "Thinking…", thread)
        return decision

    def resolve_approval(
        self, approval_id: str, approved: bool, scope: str = "once", reason: str = ""
    ) -> bool:
        fut = self.pending_approvals.get(approval_id)
        if fut is None or fut.done():
            return False
        decision = ApprovalDecision(approved=approved, scope=scope, reason=reason)  # type: ignore[arg-type]
        for tl_thread, tl in self._all_timelines():
            if tl.get(approval_id) is not None:
                self.patch(
                    tl_thread,
                    approval_id,
                    status="approved" if approved else "denied",
                    scope=scope if approved else None,
                    decided_ts=now_iso(),
                )
                break
        fut.set_result(decision)
        return True

    async def ask_user(self, question: str) -> str:
        thread = self.thread()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self.pending_questions[thread] = fut
        ev = self.emit({"type": "question", "text": question, "status": "pending"})
        self.set_status("waiting", "Waiting for your answer", thread)
        try:
            answer = await asyncio.wait_for(fut, timeout=self.approval_timeout)
        except TimeoutError:
            answer = ""
            self.patch(thread, ev["id"], status="expired")
        finally:
            self.pending_questions.pop(thread, None)
        if answer:
            self.patch(thread, ev["id"], status="answered", answer=answer)
        self.set_status("working", "Thinking…", thread)
        return answer

    def answer_question(self, thread: str, text: str) -> bool:
        fut = self.pending_questions.get(thread)
        if fut is None or fut.done():
            return False
        fut.set_result(text)
        return True

    def has_pending_question(self, thread: str) -> bool:
        fut = self.pending_questions.get(thread)
        return fut is not None and not fut.done()

    # ------------------------------------------------------------------ internals
    _timelines_provider: Callable[[], list[tuple[str, Timeline]]] | None = None

    def _all_timelines(self) -> list[tuple[str, Timeline]]:
        if self._timelines_provider is None:
            return []
        try:
            return self._timelines_provider()
        except Exception as exc:  # noqa: BLE001  pragma: no cover
            logger.warning("timeline provider failed: {}", exc)
            return []


def _preview_args(args: dict[str, Any], limit: int = 400) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in args.items():
        s = v if isinstance(v, (int, float, bool)) or v is None else str(v)
        if isinstance(s, str) and len(s) > limit:
            s = s[:limit] + f"… [+{len(s) - limit} chars]"
        out[k] = s
    return out


__all__ = ["WebUI", "current_thread"]
