"""The HTTP surface.

Two kinds of host reach this process:

- ``<session-id>.<SESSION_DOMAIN>`` — the phone talking to its Muse. Everything on such a host
  is relayed to that session's container (HTTP and ``/ws``).
- everything else — the showcase itself: ``/api/demo/*`` to start and inspect sessions,
  ``/llm/*`` for the containers' model calls (they reach us over the sessions network), and,
  in development, the built MobileGym as static files.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.routing import Host, Route, Router, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket

from . import __version__, llm
from .config import Settings
from .proxy import proxy_http, proxy_ws
from .runner import DockerRunner
from .sessions import Provider, Refused, SessionManager, check_provider

log = logging.getLogger("showcase")

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

# what a browser sees at the address of a session that is over
ENDED_PAGE = """<!doctype html><meta charset="utf-8"><title>nanoMuse</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font:15px/1.5 system-ui,sans-serif;color:#1b1730;background:#f4f3fa;text-align:center;padding:24px">
<div><div style="font-size:40px">🧸</div><p style="margin:12px 0 4px;font-weight:600">This Muse has ended.</p>
<p style="margin:0;color:#6b6880">Demo sessions last a while, then go — with everything in them.<br>
Open nanoMuse on the phone for a new one.</p></div></body>"""


class ProviderIn(BaseModel):
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)


class SessionIn(BaseModel):
    provider: ProviderIn | None = None


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _refused(exc: Refused) -> JSONResponse:
    return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)


class Spa(StaticFiles):
    """Static files, and the app's ``index.html`` for any path that is not a file."""

    async def get_response(self, path: str, scope) -> Response:  # noqa: ANN001
        try:
            return await super().get_response(path, scope)
        except Exception:  # noqa: BLE001 — StaticFiles raises HTTPException(404)
            if "." in path.rsplit("/", 1)[-1]:
                raise
            return FileResponse(os.path.join(self.directory or ".", "index.html"))


def create_app(
    settings: Settings,
    manager: SessionManager,
    client: httpx.AsyncClient | None = None,
) -> FastAPI:
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(300, connect=10), follow_redirects=False
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.startup()
        reaper = asyncio.create_task(manager.reap_forever())
        try:
            yield
        finally:
            reaper.cancel()
            await manager.shutdown()
            await http.aclose()

    app = FastAPI(title="nanoMuse showcase gateway", version=__version__, lifespan=lifespan)

    # ------------------------------------------------------------- the phone → its Muse
    async def session_http(request: Request) -> Response:
        sess = manager.get(request.path_params["sid"])
        if sess is None:
            if "text/html" in request.headers.get("accept", ""):
                return HTMLResponse(ENDED_PAGE, status_code=404)
            return JSONResponse(
                {"error": "no_session", "message": "This demo session has ended."}, status_code=404
            )
        manager.touch(sess)
        return await proxy_http(request, http, sess.http_base)

    async def session_ws(ws: WebSocket) -> None:
        sess = manager.get(ws.path_params["sid"])
        if sess is None:
            # accept first: a close before the handshake reaches the browser as a bare failure,
            # the code only travels on an open socket (the phone module reads 4404 as "gone")
            await ws.accept()
            await ws.close(code=4404, reason="this session has ended")
            return
        manager.touch(sess)
        url = f"{sess.ws_base}{ws.url.path}"
        if ws.url.query:
            url += f"?{ws.url.query}"
        await proxy_ws(ws, url, lambda: manager.touch(sess))

    session_router = Router(
        routes=[
            WebSocketRoute("/ws", session_ws),
            Route("/{path:path}", session_http, methods=_METHODS),
        ]
    )
    app.router.routes.insert(0, Host(f"{{sid}}.{settings.session_domain}", app=session_router))

    # ------------------------------------------------------------- the showcase API
    @app.get("/api/demo/info")
    async def info() -> dict[str, Any]:
        return {
            "version": __version__,
            "session_ttl_s": settings.session_ttl_s,
            "idle_ttl_s": settings.idle_ttl_s,
            "demo_model": settings.main.model if settings.main.configured else None,
            "gui_model": settings.gui.model if settings.gui.configured else None,
            "byok": settings.byok_enabled,
            "byok_hosts": list(settings.byok_hosts) if settings.byok_enabled else [],
            "quota": {"requests": settings.session_requests, "tokens": settings.session_tokens},
            **manager.stats(),
        }

    @app.post("/api/demo/session", status_code=201)
    async def start(body: SessionIn, request: Request) -> Response:
        byok = None
        try:
            if body.provider is not None:
                base_url = check_provider(
                    body.provider.base_url, settings.byok_hosts, manager.resolve
                )
                byok = Provider(
                    base_url, body.provider.api_key.strip(), body.provider.model.strip()
                )
            sess = await manager.create(client_ip(request, settings.trust_proxy), byok)
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(sess.public(settings, manager.clock()), status_code=201)

    @app.get("/api/demo/session/{sid}")
    async def show(sid: str, request: Request) -> Response:
        try:
            sess = manager.authenticate(sid, llm.bearer(request))
        except Refused as exc:
            return _refused(exc)
        return JSONResponse(sess.public(settings, manager.clock()))

    @app.delete("/api/demo/session/{sid}", status_code=204)
    async def stop(sid: str, request: Request) -> Response:
        try:
            sess = manager.authenticate(sid, llm.bearer(request))
        except Refused as exc:
            return _refused(exc)
        await manager.end(sess.id, reason="ended by the visitor")
        return Response(status_code=204)

    # ------------------------------------------------------------- the containers' model calls
    @app.api_route("/llm/{sid}/{lane}/{path:path}", methods=["GET", "POST"])
    async def model(sid: str, lane: str, path: str, request: Request) -> Response:
        sess = manager.get(sid)
        if sess is None:
            return llm.refusal(Refused(404, "no_session", "this session has ended"))
        return await llm.forward(request, manager, http, sess, lane, path)

    # ------------------------------------------------------------- the site (development)
    if settings.cdn_dir:
        app.mount("/cdn", StaticFiles(directory=settings.cdn_dir), name="cdn")
    if settings.site_dir:
        app.mount("/", Spa(directory=settings.site_dir, html=True), name="site")

    return app


def build() -> FastAPI:
    """Everything wired from the environment — what ``uvicorn showcase_gateway.app:build``
    and ``python -m showcase_gateway`` run."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    settings = Settings.from_env()
    manager = SessionManager(settings, DockerRunner(settings))
    return create_app(settings, manager)
