"""HTTP + WebSocket API for the OpenMuse app (and anything else that wants to talk to your Muse).

    GET  /api/state                      snapshot: profile, status, threads, goals, settings
    GET  /api/threads                    list threads          POST /api/threads {title}
    GET  /api/threads/{id}/events        timeline (?limit&before)
    POST /api/threads/{id}/send {text}   queue a message (non-blocking)
    POST /api/approvals/{id} {approved, scope, reason}
    GET  /api/goals  POST /api/goals  GET|PATCH|DELETE /api/goals/{id}  POST /api/goals/{id}/advance|steps
    GET  /api/memory  POST /api/memory  DELETE /api/memory/{id}
    GET  /api/ideas (?refresh=1)
    GET  /api/activity                   audit tail + approvals granted
    GET  /api/files  GET /api/files/{path}
    GET|PUT /api/settings
    WS   /ws?token=…                     live events

All endpoints require ``Authorization: Bearer <token>`` (or ``?token=``) unless
``server.auth = false``. The token is printed (with a QR code) by ``openmuse serve``.
"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
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
    text: str = Field(min_length=1, max_length=20_000)


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


class GoalPatch(BaseModel):
    status: str | None = None
    note: str | None = None
    step_index: int | None = None
    step_status: str | None = None
    step_note: str | None = None


class StepBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class MemoryBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = "profile"


class SettingsBody(BaseModel):
    profile: dict[str, Any] | None = None
    sentinel_mode: str | None = None
    show_thinking: bool | None = None
    language: str | None = None


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
        if token != svc.token:
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
            event = svc.send(thread.id, body.text)
        except ValueError as exc:
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

    # ------------------------------------------------------------------ goals
    @app.get("/api/goals", dependencies=dep)
    async def list_goals(status: str | None = None) -> list[dict[str, Any]]:
        return [goal_to_dict(g) for g in svc.app.goals.list(status)]

    @app.post("/api/goals", dependencies=dep)
    async def create_goal(body: GoalBody) -> dict[str, Any]:
        goal = svc.app.goals.create(
            body.title, body.description, [s for s in body.steps if s.strip()]
        )
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
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
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
    @app.get("/api/files", dependencies=dep)
    async def list_files(limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
        return svc.list_files(limit)

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
            svc.send(str(data.get("thread") or MAIN_THREAD), str(data.get("text", "")))
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
    except ValueError as exc:
        await ws.send_json({"kind": "error", "error": str(exc)})


__all__ = ["STATIC_DIR", "create_app"]
