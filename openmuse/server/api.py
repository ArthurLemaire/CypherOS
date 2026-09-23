"""HTTP + WebSocket API for the OpenMuse app (and anything else that wants to talk to your Muse).

    GET  /api/state                      snapshot: profile, status, threads, goals, settings
    GET  /api/threads                    list threads          POST /api/threads {title}
    GET  /api/threads/{id}/events        timeline (?limit&before)
    POST /api/threads/{id}/send {text}   queue a message (non-blocking)
    POST /api/approvals/{id} {approved, scope, reason}
    DELETE /api/approvals                 forget every granted permission
    DELETE /api/approvals/grants/{key}    revoke one (key = "tool" or "tool:target")
    GET  /api/goals  POST /api/goals  GET|PATCH|DELETE /api/goals/{id}  POST /api/goals/{id}/advance|steps|check-in
    POST /api/goals/{id}/proposal/accept  DELETE /api/goals/{id}/proposal   the agent's plan change
    GET  /api/memory  POST /api/memory  DELETE /api/memory/{id}
    POST /api/memory/tidy (?dry_run=1)   GET /api/memory/changes   POST /api/memory/changes/{id}/restore
    GET  /api/ideas (?refresh=1)
    GET  /api/activity                   audit tail + approvals granted
    GET  /api/feed                        what happened without you asking
    GET  /api/upcoming                    next background pass and the goals in line
    GET  /api/calendar (?days&refresh=1)  today's and tomorrow's events from the calendar feeds
    GET  /api/files  GET /api/files/{path}  POST /api/files/upload?name=  (body: the bytes)
    GET|PUT /api/settings
    GET  /api/connections                 model, email, browser, MCP servers, vault names
    PUT  /api/connections/llm|embeddings|email|browser|calendar   POST /api/connections/llm|embeddings|email|calendar/test
    POST /api/connections/calendar/feeds {name,url}  DELETE /api/connections/calendar/feeds/{name}
    PUT  /api/connections/contacts {enabled}  POST /api/connections/contacts/sources {name,url}
    POST /api/connections/contacts/import?name= (body: the .vcf text)  DELETE /api/connections/contacts/sources/{name}
    POST /api/connections/contacts/test      GET /api/contacts?q=&limit=   look people up
    GET  /api/skills  GET /api/skills/{name}  PUT /api/skills/{name} {content}  DELETE /api/skills/{name}
    POST /api/skills/{name}/enabled {enabled}  POST /api/skills/import {url}
    POST /api/connections/mcp  DELETE /api/connections/mcp/{name}
    GET  /api/vault  PUT|DELETE /api/vault/{name}   (names only ever come back)
    POST /api/onboarded
    WS   /ws?token=…                     live events

All endpoints require ``Authorization: Bearer <token>`` (or ``?token=``) unless
``server.auth = false``. The token is printed (with a QR code) by ``openmuse serve``.
"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from openmuse.config import Settings
from openmuse.logger import logger
from openmuse.server.events import MAIN_THREAD
from openmuse.server.service import MuseService, goal_to_dict

STATIC_DIR = Path(__file__).parent / "static"


# ----------------------------------------------------------------------------- request models
class SendBody(BaseModel):
    text: str = Field("", max_length=20_000)
    # workspace paths from POST /api/files/upload; a message may be attachments alone
    files: list[str] = Field(default_factory=list, max_length=10)


class ThreadBody(BaseModel):
    title: str = ""


class ApprovalBody(BaseModel):
    approved: bool
    scope: str = "once"
    reason: str = ""


class GoalBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    steps: list[str] = Field(default_factory=list)
    category: str = ""
    due: str = ""
    check_in: str = ""


class GoalPatch(BaseModel):
    status: str | None = None
    note: str | None = None
    step_index: int | None = None
    step_status: str | None = None
    step_note: str | None = None
    # the goal's own fields; "" clears due / check_in
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category: str | None = None
    due: str | None = None
    check_in: str | None = None


class StepBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ReminderBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = "remind"
    at: str = ""
    repeat: str = ""
    thread: str = ""


class TriggerBody(BaseModel):
    kind: str = Field(pattern="^(mail|event|hook)$")
    text: str = Field(min_length=1, max_length=2000)
    match: str = Field(default="", max_length=200)
    lead_minutes: int = Field(default=30, ge=0, le=1440)
    thread: str = ""


class MemoryBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = "profile"


class SettingsBody(BaseModel):
    profile: dict[str, Any] | None = None
    sentinel_mode: str | None = None
    show_thinking: bool | None = None
    language: str | None = None


class LLMBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    tool_mode: str | None = None
    # a new key goes straight into the vault; "" removes the key; None keeps it
    api_key: str | None = None


class EmbeddingsBody(BaseModel):
    mode: str | None = None  # auto | on | off
    model: str | None = None  # "" → the default for the endpoint
    base_url: str | None = None  # "" → the model's endpoint
    api_key: str | None = None  # into the vault; "" → the model's key; None keeps it


class SearchBody(BaseModel):
    provider: str | None = None  # duckduckgo | brave | tavily | searxng
    api_key: str | None = None  # into the vault; "" removes it; None keeps it
    base_url: str | None = None  # SearXNG instance


class EmailBody(BaseModel):
    enabled: bool | None = None
    address: str | None = None
    password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool | None = None


class BrowserBody(BaseModel):
    enabled: bool


class CalendarFeedBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2000)


class ContactsSourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2000)


class ContactsBody(BaseModel):
    enabled: bool | None = None


class SkillBody(BaseModel):
    content: str = Field(max_length=70_000)  # the SKILL.md text


class SkillEnabledBody(BaseModel):
    enabled: bool


class SkillImportBody(BaseModel):
    url: str = Field(max_length=2000)


class CalendarBody(BaseModel):
    enabled: bool | None = None
    refresh_minutes: int | None = Field(default=None, ge=5, le=1440)
    day_start: str | None = None
    day_end: str | None = None


class MCPBody(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    risk: str = "moderate"
    egress: bool = True
    reads_private_data: bool = False


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=10_000)


class OnboardedBody(BaseModel):
    done: bool = True


class BrowserControlBody(BaseModel):
    """The user drives the agent's browser. ``x``/``y`` are fractions of the frame."""

    action: str
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    text: str | None = Field(default=None, max_length=4000)
    key: str | None = Field(default=None, max_length=40)
    dy: float | None = Field(default=None, ge=-5000, le=5000)
    url: str | None = Field(default=None, max_length=2000)


class PushSubscribeBody(BaseModel):
    # the PushSubscription.toJSON() of the browser: {endpoint, expirationTime, keys{p256dh, auth}}
    subscription: dict[str, Any]


class PushUnsubscribeBody(BaseModel):
    endpoint: str


# ----------------------------------------------------------------------------- app factory
def create_app(settings: Settings, service: MuseService | None = None) -> FastAPI:
    svc = service or MuseService(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await svc.start()
        try:
            yield
        finally:
            await svc.stop()

    app = FastAPI(
        title="OpenMuse",
        version=svc.settings_view()["version"],
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.service = svc

    if settings.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ------------------------------------------------------------------ auth
    def _check_token(token: str | None) -> None:
        if not svc.token:
            return
        if not token or not secrets.compare_digest(token.encode(), svc.token.encode()):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        _check_token(token or request.query_params.get("token"))

    dep = [Depends(auth)]

    def _thread_or_404(thread_id: str):  # noqa: ANN202
        thread = svc.threads.get(thread_id)
        if thread is None:
            raise HTTPException(404, "no such thread")
        return thread

    def _goal_or_404(goal_id: str):  # noqa: ANN202
        goal = svc.app.goals.get(goal_id)
        if goal is None:
            raise HTTPException(404, "no such goal")
        return goal

    # ------------------------------------------------------------------ state
    @app.get("/api/state", dependencies=dep)
    async def get_state() -> dict[str, Any]:
        return svc.state()

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": svc.settings_view()["version"], "auth": bool(svc.token)}

    # ------------------------------------------------------------------ threads & chat
    @app.get("/api/threads", dependencies=dep)
    async def list_threads() -> list[dict[str, Any]]:
        return [t.meta() for t in svc.threads.values()]

    @app.post("/api/threads", dependencies=dep)
    async def create_thread(body: ThreadBody) -> dict[str, Any]:
        return svc.create_thread(body.title).meta()

    @app.patch("/api/threads/{thread_id}", dependencies=dep)
    async def rename_thread(thread_id: str, body: ThreadBody) -> dict[str, Any]:
        thread = svc.rename_thread(thread_id, body.title)
        if thread is None:
            raise HTTPException(404, "no such thread")
        return thread.meta()

    @app.delete("/api/threads/{thread_id}", dependencies=dep)
    async def delete_thread(thread_id: str) -> dict[str, Any]:
        if thread_id == MAIN_THREAD:
            raise HTTPException(400, "the main chat cannot be deleted")
        if not svc.delete_thread(thread_id):
            raise HTTPException(404, "no such thread")
        return {"ok": True}

    @app.post("/api/threads/{thread_id}/clear", dependencies=dep)
    async def clear_thread(thread_id: str) -> dict[str, Any]:
        _thread_or_404(thread_id)
        if not svc.clear_thread(thread_id):
            raise HTTPException(409, "thread is busy")
        return {"ok": True}

    @app.get("/api/threads/{thread_id}/events", dependencies=dep)
    async def thread_events(
        thread_id: str, limit: int = Query(200, ge=1, le=1000), before: str | None = None
    ) -> dict[str, Any]:
        thread = _thread_or_404(thread_id)
        events = thread.timeline.tail(limit, before)
        return {
            "thread": thread.meta(),
            "events": events,
            "has_more": len(thread.timeline.events) > len(events),
        }

    @app.post("/api/threads/{thread_id}/send", dependencies=dep)
    async def send_message(thread_id: str, body: SendBody) -> dict[str, Any]:
        thread = _thread_or_404(thread_id)
        try:
            event = svc.send(thread.id, body.text, files=body.files)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"event": event, "thread": thread.meta()}

    # ------------------------------------------------------------------ approvals
    @app.post("/api/approvals/{approval_id}", dependencies=dep)
    async def decide_approval(approval_id: str, body: ApprovalBody) -> dict[str, Any]:
        if not svc.decide(approval_id, body.approved, body.scope, body.reason):
            raise HTTPException(404, "no pending approval with that id")
        return {"ok": True}

    @app.delete("/api/approvals", dependencies=dep)
    async def reset_approvals() -> dict[str, Any]:
        svc.forget_approvals()
        return {"ok": True}

    @app.delete("/api/approvals/grants/{key:path}", dependencies=dep)
    async def revoke_grant(key: str) -> dict[str, Any]:
        if not svc.revoke_grant(key):
            raise HTTPException(404, "no such permission")
        return {"ok": True}

    # ------------------------------------------------------------------ goals
    @app.get("/api/goals", dependencies=dep)
    async def list_goals(
        status: str | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        return [goal_to_dict(g) for g in svc.app.goals.list(status, category)]

    @app.post("/api/goals", dependencies=dep)
    async def create_goal(body: GoalBody) -> dict[str, Any]:
        try:
            goal = svc.app.goals.create(
                body.title,
                body.description,
                [s for s in body.steps if s.strip()],
                category=body.category,
                due=body.due,
                check_in=body.check_in,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(goal)

    @app.get("/api/goals/{goal_id}", dependencies=dep)
    async def get_goal(goal_id: str) -> dict[str, Any]:
        return goal_to_dict(_goal_or_404(goal_id))

    @app.patch("/api/goals/{goal_id}", dependencies=dep)
    async def patch_goal(goal_id: str, body: GoalPatch) -> dict[str, Any]:
        _goal_or_404(goal_id)
        store = svc.app.goals
        try:
            if body.status:
                store.set_status(goal_id, body.status)
            if body.note:
                store.append_note(goal_id, body.note)
            if body.step_index is not None and (body.step_status or body.step_note is not None):
                store.update_step(goal_id, body.step_index, body.step_status, body.step_note)
            if any(
                v is not None
                for v in (body.title, body.description, body.category, body.due, body.check_in)
            ):
                store.update(
                    goal_id,
                    title=body.title,
                    description=body.description,
                    category=body.category,
                    due=body.due,
                    check_in=body.check_in,
                )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.post("/api/goals/{goal_id}/check-in", dependencies=dep)
    async def check_in_goal(goal_id: str) -> dict[str, Any]:
        """Send this goal's reminder now."""
        try:
            goal = svc.check_in(goal_id)
        except KeyError as exc:
            raise HTTPException(404, "no such goal") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return goal_to_dict(goal)

    @app.post("/api/goals/{goal_id}/proposal/accept", dependencies=dep)
    async def accept_proposal(goal_id: str) -> dict[str, Any]:
        goal = _goal_or_404(goal_id)
        if not goal.proposal:
            raise HTTPException(409, "nothing proposed")
        svc.app.goals.accept_proposal(goal_id)
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.delete("/api/goals/{goal_id}/proposal", dependencies=dep)
    async def dismiss_proposal(goal_id: str) -> dict[str, Any]:
        goal = _goal_or_404(goal_id)
        if not goal.proposal:
            raise HTTPException(409, "nothing proposed")
        svc.app.goals.dismiss_proposal(goal_id)
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.post("/api/goals/{goal_id}/steps", dependencies=dep)
    async def add_step(goal_id: str, body: StepBody) -> dict[str, Any]:
        _goal_or_404(goal_id)
        svc.app.goals.add_step(goal_id, body.title)
        svc.bus.publish({"kind": "goals"})
        return goal_to_dict(_goal_or_404(goal_id))

    @app.post("/api/goals/{goal_id}/advance", dependencies=dep)
    async def advance_goal(goal_id: str) -> dict[str, Any]:
        try:
            goal = svc.advance_goal(goal_id)
        except KeyError as exc:
            raise HTTPException(404, "no such goal") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return goal_to_dict(goal)

    @app.delete("/api/goals/{goal_id}", dependencies=dep)
    async def delete_goal(goal_id: str) -> dict[str, Any]:
        if not svc.app.goals.delete(goal_id):
            raise HTTPException(404, "no such goal")
        svc.bus.publish({"kind": "goals"})
        return {"ok": True}

    # ------------------------------------------------------------------ reminders
    @app.get("/api/reminders", dependencies=dep)
    async def list_reminders(all: bool = False) -> list[dict[str, Any]]:  # noqa: A002
        """Active reminders and routines, soonest first; ``?all=1`` adds recently finished ones."""
        return [r.to_dict() for r in svc.app.reminders.list(None if all else "active")]

    @app.post("/api/reminders", dependencies=dep)
    async def create_reminder(body: ReminderBody) -> dict[str, Any]:
        try:
            item = svc.create_reminder(
                body.text, at=body.at, repeat=body.repeat, kind=body.kind, thread=body.thread
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return item.to_dict()

    @app.post("/api/reminders/{reminder_id}/fire", dependencies=dep)
    async def fire_reminder(reminder_id: str) -> dict[str, Any]:
        """Deliver it now instead of waiting for its time."""
        try:
            return svc.fire_reminder(reminder_id).to_dict()
        except KeyError as exc:
            raise HTTPException(404, "no such reminder") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/reminders/{reminder_id}", dependencies=dep)
    async def cancel_reminder(reminder_id: str) -> dict[str, Any]:
        item = svc.cancel_reminder(reminder_id)
        if item is None:
            if svc.app.reminders.get(reminder_id) is None:
                raise HTTPException(404, "no such reminder")
            raise HTTPException(409, "already finished")
        return item.to_dict()

    # ------------------------------------------------------------------ triggers
    @app.get("/api/triggers", dependencies=dep)
    async def list_triggers() -> dict[str, Any]:
        """Triggers (active and cancelled), which kinds have their connector, and how the
        inbox watch is doing."""
        return svc.triggers_view()

    @app.post("/api/triggers", dependencies=dep)
    async def create_trigger(body: TriggerBody) -> dict[str, Any]:
        try:
            item = svc.create_trigger(
                body.kind,
                body.text,
                match=body.match,
                lead_minutes=body.lead_minutes,
                thread=body.thread,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        out = item.to_dict()
        if item.kind == "hook":
            out["url"] = svc.hook_url(item)
        return out

    @app.post("/api/triggers/{trigger_id}/fire", dependencies=dep)
    async def fire_trigger(trigger_id: str) -> dict[str, Any]:
        """Run it now with a sample occurrence, to see what it does."""
        item = svc.app.triggers.get(trigger_id)
        if item is None:
            raise HTTPException(404, "no such trigger")
        what = {
            "mail": "A test: you pressed Run now, as if a matching mail had just arrived (none did)",
            "event": "A test: you pressed Run now, as if a matching event were about to start",
            "hook": "A test: you pressed Run now, as if the webhook had been called (empty body)",
        }[item.kind]
        try:
            fired = svc.fire_trigger(
                trigger_id, what=what, key=f"test:{secrets.token_hex(4)}", title="test run"
            )
        except KeyError as exc:
            raise HTTPException(404, "no such trigger") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return (fired or item).to_dict()

    @app.delete("/api/triggers/{trigger_id}", dependencies=dep)
    async def cancel_trigger(trigger_id: str) -> dict[str, Any]:
        item = svc.cancel_trigger(trigger_id)
        if item is None:
            if svc.app.triggers.get(trigger_id) is None:
                raise HTTPException(404, "no such trigger")
            raise HTTPException(409, "already cancelled")
        return item.to_dict()

    @app.post("/api/hooks/{trigger_id}")
    async def deliver_hook(trigger_id: str, request: Request) -> dict[str, Any]:
        """A trigger's webhook. No app token: the key in the URL is the credential, and a
        wrong id or key is a 404 either way. The body (up to 64 KB, JSON or text) is what
        the agent gets as context."""
        key = request.query_params.get("key") or request.headers.get("x-hook-key") or ""
        raw = await request.body()
        if len(raw) > 64 * 1024:
            raise HTTPException(413, "body too large (64 KB max)")
        body = raw.decode("utf-8", errors="replace")
        try:
            item = svc.deliver_hook(trigger_id, key, body, request.headers.get("content-type", ""))
        except KeyError as exc:
            raise HTTPException(404, "not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"ok": True, "trigger": item.id, "fired": item.fired}

    # ------------------------------------------------------------------ memory
    @app.get("/api/memory", dependencies=dep)
    async def list_memory() -> list[dict[str, Any]]:
        if svc.app.memory is None:
            return []
        return [m.__dict__ for m in svc.app.memory.all()]

    @app.post("/api/memory", dependencies=dep)
    async def add_memory(body: MemoryBody) -> dict[str, Any]:
        if svc.app.memory is None:
            raise HTTPException(400, "memory is disabled")
        item = svc.app.memory.add(body.content, body.category or "profile", source="user")
        svc.bus.publish({"kind": "memory"})
        return item.__dict__

    @app.delete("/api/memory/{memory_id}", dependencies=dep)
    async def forget_memory(memory_id: str) -> dict[str, Any]:
        if svc.app.memory is None or not svc.app.memory.forget(memory_id):
            raise HTTPException(404, "no such memory")
        svc.bus.publish({"kind": "memory"})
        return {"ok": True}

    @app.post("/api/memory/tidy", dependencies=dep)
    async def tidy_memory(dry_run: bool = False) -> dict[str, Any]:
        """One tidy-up pass now (merge duplicates, drop non-facts); ``dry_run`` only plans."""
        try:
            return await svc.tidy_memory(dry_run=dry_run)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/memory/changes", dependencies=dep)
    async def memory_changes(limit: int = Query(30, ge=1, le=200)) -> list[dict[str, Any]]:
        """What tidy-ups and updates changed, newest first; each entry can be restored."""
        if svc.app.memory is None:
            return []
        return [c.to_dict() for c in svc.app.memory.history(limit)]

    @app.post("/api/memory/changes/{change_id}/restore", dependencies=dep)
    async def restore_memory_change(change_id: str) -> dict[str, Any]:
        if svc.app.memory is None:
            raise HTTPException(400, "memory is disabled")
        change = svc.app.memory.restore(change_id)
        if change is None:
            raise HTTPException(404, "no such change")
        svc.bus.publish({"kind": "memory"})
        return change.to_dict()

    # ------------------------------------------------------------------ ideas
    @app.get("/api/ideas", dependencies=dep)
    async def ideas(refresh: bool = False) -> dict[str, Any]:
        if refresh:
            try:
                return await svc.refresh_ideas()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ideas refresh failed: {}", exc)
                data = svc.cached_ideas()
                data["error"] = f"{type(exc).__name__}: {exc}"
                return data
        return svc.cached_ideas()

    # ------------------------------------------------------------------ activity / settings
    @app.get("/api/activity", dependencies=dep)
    async def activity(n: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
        return svc.activity(n)

    @app.get("/api/settings", dependencies=dep)
    async def get_settings() -> dict[str, Any]:
        return svc.settings_view()

    @app.put("/api/settings", dependencies=dep)
    async def put_settings(body: SettingsBody) -> dict[str, Any]:
        return svc.update_settings(body.model_dump(exclude_none=True))

    # ------------------------------------------------------------------ files
    # ------------------------------------------------------------------ connections
    conn = svc.connections

    @app.get("/api/connections", dependencies=dep)
    async def get_connections() -> dict[str, Any]:
        return conn.view()

    @app.put("/api/connections/llm", dependencies=dep)
    async def put_llm(body: LLMBody) -> dict[str, Any]:
        try:
            return conn.set_llm(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/llm/test", dependencies=dep)
    async def test_llm() -> dict[str, Any]:
        return await conn.test_llm()

    @app.put("/api/connections/embeddings", dependencies=dep)
    async def put_embeddings(body: EmbeddingsBody) -> dict[str, Any]:
        try:
            return conn.set_embeddings(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/embeddings/test", dependencies=dep)
    async def test_embeddings() -> dict[str, Any]:
        return await conn.test_embeddings()

    @app.put("/api/connections/search", dependencies=dep)
    async def put_search(body: SearchBody) -> dict[str, Any]:
        try:
            return conn.set_search(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/search/test", dependencies=dep)
    async def test_search() -> dict[str, Any]:
        return await conn.test_search()

    @app.put("/api/connections/email", dependencies=dep)
    async def put_email(body: EmailBody) -> dict[str, Any]:
        return conn.set_email(body.model_dump(exclude_none=True))

    @app.delete("/api/connections/email", dependencies=dep)
    async def delete_email() -> dict[str, Any]:
        return conn.disconnect_email()

    @app.post("/api/connections/email/test", dependencies=dep)
    async def test_email() -> dict[str, Any]:
        return await conn.test_email()

    @app.put("/api/connections/browser", dependencies=dep)
    async def put_browser(body: BrowserBody) -> dict[str, Any]:
        return conn.set_browser(body.enabled)

    @app.put("/api/connections/calendar", dependencies=dep)
    async def put_calendar(body: CalendarBody) -> dict[str, Any]:
        try:
            return conn.set_calendar(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/calendar/feeds", dependencies=dep)
    async def add_calendar_feed(body: CalendarFeedBody) -> dict[str, Any]:
        try:
            return await conn.add_calendar_feed(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/connections/calendar/feeds/{name}", dependencies=dep)
    async def delete_calendar_feed(name: str) -> dict[str, Any]:
        if not conn.remove_calendar_feed(name):
            raise HTTPException(404, "no such calendar (feeds from config.toml are removed there)")
        return conn.view()["calendar"]

    @app.post("/api/connections/calendar/test", dependencies=dep)
    async def test_calendar() -> dict[str, Any]:
        return await conn.test_calendar()

    @app.get("/api/calendar", dependencies=dep)
    async def calendar(days: int = Query(2, ge=1, le=31), refresh: int = 0) -> dict[str, Any]:
        if refresh:
            await svc.app.calendar.refresh(force=True)
        else:
            await svc.app.calendar.refresh()
        return svc.calendar_view(days)

    @app.put("/api/connections/contacts", dependencies=dep)
    async def put_contacts(body: ContactsBody) -> dict[str, Any]:
        return conn.set_contacts(body.model_dump(exclude_none=True))

    @app.post("/api/connections/contacts/sources", dependencies=dep)
    async def add_contacts_source(body: ContactsSourceBody) -> dict[str, Any]:
        try:
            return await conn.add_contacts_source(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/connections/contacts/import", dependencies=dep)
    async def import_contacts(
        request: Request, name: str = Query("", max_length=40)
    ) -> dict[str, Any]:
        """The text of a ``.vcf`` file as the request body (no multipart needed; 16 MB max)."""
        raw = await request.body()
        if len(raw) > 16 * 1024 * 1024:
            raise HTTPException(413, "the file is larger than 16 MB")
        try:
            return await conn.import_contacts(name, raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/connections/contacts/sources/{name}", dependencies=dep)
    async def delete_contacts_source(name: str) -> dict[str, Any]:
        if not conn.remove_contacts_source(name):
            raise HTTPException(
                404, "no such address book (sources from config.toml are removed there)"
            )
        return conn.view()["contacts"]

    @app.post("/api/connections/contacts/test", dependencies=dep)
    async def test_contacts() -> dict[str, Any]:
        return await conn.test_contacts()

    @app.get("/api/contacts", dependencies=dep)
    async def contacts(
        q: str = Query("", max_length=200), limit: int = Query(8, ge=1, le=50)
    ) -> dict[str, Any]:
        """Look people up as the agent does (``q`` empty: the first people alphabetically)."""
        book = svc.app.contacts
        people = (
            book.search(q, limit=limit)
            if q.strip()
            else sorted(book.contacts, key=lambda c: c.name.lower())[:limit]
        )
        return {"count": len(book), "people": [c.to_dict() for c in people]}

    # ------------------------------------------------------------------ skills
    @app.get("/api/skills", dependencies=dep)
    async def skills() -> dict[str, Any]:
        return svc.skills_view()

    @app.get("/api/skills/{name}", dependencies=dep)
    async def skill(name: str) -> dict[str, Any]:
        view = svc.skill_view(name)
        if view is None:
            raise HTTPException(404, "no such skill")
        return view

    @app.put("/api/skills/{name}", dependencies=dep)
    async def put_skill(name: str, body: SkillBody) -> dict[str, Any]:
        """Write one of your skills from the text of its SKILL.md (a built-in of the same
        name is replaced by it)."""
        try:
            return svc.save_skill(body.content, name=name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"could not write the skill: {exc}") from exc

    @app.delete("/api/skills/{name}", dependencies=dep)
    async def delete_skill(name: str) -> dict[str, Any]:
        if not svc.remove_skill(name):
            raise HTTPException(
                404, "no such skill of yours (built-in skills are switched off, not removed)"
            )
        return svc.skills_view()

    @app.post("/api/skills/{name}/enabled", dependencies=dep)
    async def skill_enabled(name: str, body: SkillEnabledBody) -> dict[str, Any]:
        view = svc.set_skill_enabled(name, body.enabled)
        if view is None:
            raise HTTPException(404, "no such skill")
        return view

    @app.post("/api/skills/import", dependencies=dep)
    async def import_skill(body: SkillImportBody) -> dict[str, Any]:
        try:
            return await svc.import_skill(body.url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — a network error, reported as such
            raise HTTPException(502, f"could not fetch the skill: {exc}") from exc

    @app.post("/api/connections/mcp", dependencies=dep)
    async def add_mcp(body: MCPBody) -> dict[str, Any]:
        try:
            return await conn.add_mcp(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.delete("/api/connections/mcp/{name}", dependencies=dep)
    async def remove_mcp(name: str) -> dict[str, Any]:
        if not await conn.remove_mcp(name):
            raise HTTPException(404, "no such server (servers from config.toml are removed there)")
        return {"ok": True}

    @app.get("/api/vault", dependencies=dep)
    async def vault_names() -> list[str]:
        return svc.app.vault.names()

    @app.put("/api/vault/{name}", dependencies=dep)
    async def vault_set(name: str, body: SecretBody) -> list[str]:
        try:
            return conn.set_secret(name, body.value)
        except Exception as exc:  # noqa: BLE001 - VaultError on a bad name
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/vault/{name}", dependencies=dep)
    async def vault_delete(name: str) -> dict[str, Any]:
        if not conn.delete_secret(name):
            raise HTTPException(404, "no such secret")
        return {"ok": True}

    @app.post("/api/onboarded", dependencies=dep)
    async def onboarded(body: OnboardedBody) -> dict[str, Any]:
        conn.set_onboarded(body.done)
        return {"onboarded": body.done}

    # ------------------------------------------------------------------ browser view
    @app.get("/api/browser/{thread_id}/frames/{frame_id}.jpg", dependencies=dep)
    async def browser_frame(thread_id: str, frame_id: str) -> Response:
        jpeg = svc.ui.browser_frame(thread_id, frame_id)
        if jpeg is None:
            raise HTTPException(404, "that frame is gone")
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=86400, immutable"},
        )

    @app.post("/api/browser/{thread_id}/control", dependencies=dep)
    async def browser_control(thread_id: str, body: BrowserControlBody) -> dict[str, Any]:
        _thread_or_404(thread_id)
        try:
            return await svc.browser_control(thread_id, body.model_dump(exclude_none=True))
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - playwright raises many error types
            raise HTTPException(502, f"browser error: {str(exc).splitlines()[0][:200]}") from exc

    # ------------------------------------------------------------------ push
    @app.get("/api/push", dependencies=dep)
    async def push_view() -> dict[str, Any]:
        return svc.push.view()

    @app.post("/api/push/subscribe", dependencies=dep)
    async def push_subscribe(body: PushSubscribeBody, request: Request) -> dict[str, Any]:
        try:
            svc.push.subscribe(body.subscription, ua=request.headers.get("user-agent", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return svc.push.view()

    @app.post("/api/push/unsubscribe", dependencies=dep)
    async def push_unsubscribe(body: PushUnsubscribeBody) -> dict[str, Any]:
        svc.push.unsubscribe(body.endpoint)
        return svc.push.view()

    @app.post("/api/push/test", dependencies=dep)
    async def push_test() -> dict[str, Any]:
        return await svc.push.test(svc.profile.name)

    @app.get("/api/feed", dependencies=dep)
    async def feed(limit: int = Query(60, ge=1, le=500)) -> list[dict[str, Any]]:
        return svc.feed(limit)

    @app.get("/api/upcoming", dependencies=dep)
    async def upcoming() -> dict[str, Any]:
        return svc.upcoming()

    @app.get("/api/files", dependencies=dep)
    async def list_files(limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
        return svc.list_files(limit)

    @app.post("/api/files/upload", dependencies=dep)
    async def upload_file(
        request: Request, name: str = Query(..., min_length=1, max_length=255)
    ) -> dict[str, Any]:
        """A file to attach to a message: the bytes as the request body (no multipart),
        the file name in ``name``. Lands in ``attachments/<date>/`` in the workspace;
        the reply is what to put in ``files`` when sending."""
        limit = svc.settings.server.max_upload_mb * 1024 * 1024
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise HTTPException(
                413, f"the file is larger than {svc.settings.server.max_upload_mb} MB"
            )
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise HTTPException(
                    413, f"the file is larger than {svc.settings.server.max_upload_mb} MB"
                )
            chunks.append(chunk)
        if total == 0:
            raise HTTPException(400, "empty file")
        try:
            return svc.save_upload(name, b"".join(chunks)).model_dump()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/files/{path:path}", dependencies=dep)
    async def get_file(path: str, download: bool = False) -> Response:
        try:
            target = svc.resolve_workspace_path(path)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        if not target.is_file():
            raise HTTPException(404, "no such file")
        media, _ = mimetypes.guess_type(str(target))
        if media is None or target.suffix.lower() in (
            ".md",
            ".txt",
            ".log",
            ".csv",
            ".json",
            ".py",
        ):
            media = (
                "text/plain; charset=utf-8"
                if target.suffix.lower() != ".json"
                else "application/json"
            )
        headers = (
            {"Content-Disposition": f'attachment; filename="{target.name}"'} if download else {}
        )
        if media.startswith("text/html") or media == "image/svg+xml":
            # Files the agent wrote never run with the app's origin: no token, no API.
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups"
        return FileResponse(target, media_type=media, headers=headers)

    # ------------------------------------------------------------------ websocket
    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        try:
            _check_token(ws.query_params.get("token"))
        except HTTPException:
            await ws.close(code=4401)
            return
        await ws.accept()
        queue = svc.bus.subscribe()
        await ws.send_json({"kind": "hello", "state": svc.state()})

        async def pump() -> None:
            while True:
                msg = await queue.get()
                await ws.send_json(msg)

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                data = await ws.receive_json()
                await _handle_ws_message(svc, ws, data)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("websocket closed: {}", exc)
        finally:
            pump_task.cancel()
            svc.bus.unsubscribe(queue)

    # ------------------------------------------------------------------ static SPA
    if STATIC_DIR.is_dir():
        from fastapi.staticfiles import StaticFiles

        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Response:
            candidate = (STATIC_DIR / full_path).resolve() if full_path else None
            if candidate and STATIC_DIR.resolve() in candidate.parents and candidate.is_file():
                if candidate.name == "sw.js":
                    # the service worker: always revalidated, so a new build reaches phones
                    return FileResponse(
                        candidate,
                        media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"},
                    )
                return FileResponse(candidate)
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
            raise HTTPException(404)

    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend() -> Response:
            return JSONResponse(
                {
                    "message": "OpenMuse API is running, but the web app is not built. "
                    "Run `cd web && npm install && npm run build` or use the CLI (`openmuse chat`).",
                }
            )

    return app


async def _handle_ws_message(svc: MuseService, ws: WebSocket, data: dict[str, Any]) -> None:
    kind = data.get("kind") or data.get("type")
    try:
        if kind == "send":
            files = data.get("files")
            svc.send(
                str(data.get("thread") or MAIN_THREAD),
                str(data.get("text", "")),
                files=[str(f) for f in files][:10] if isinstance(files, list) else None,
            )
        elif kind == "approval":
            ok = svc.decide(
                str(data.get("id", "")),
                bool(data.get("approved")),
                str(data.get("scope", "once")),
                str(data.get("reason", "")),
            )
            if not ok:
                await ws.send_json({"kind": "error", "error": "no pending approval with that id"})
        elif kind == "ping":
            await ws.send_json({"kind": "pong", "status": svc.ui.overall_status()})
        else:
            await ws.send_json({"kind": "error", "error": f"unknown message kind: {kind}"})
    except (ValueError, PermissionError) as exc:
        await ws.send_json({"kind": "error", "error": str(exc)})


__all__ = ["STATIC_DIR", "create_app"]
