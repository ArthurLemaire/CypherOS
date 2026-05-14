"""Relaying the phone's traffic to its session's container: HTTP and the WebSocket."""

from __future__ import annotations

import asyncio
import logging

import httpx
import websockets
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

log = logging.getLogger("showcase.proxy")

_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


async def proxy_http(request: Request, client: httpx.AsyncClient, base: str) -> Response:
    url = f"{base}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP | {"host"}}
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme
    body = await request.body()
    try:
        req = client.build_request(request.method, url, headers=headers, content=body)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        log.info("upstream %s: %s", url, exc)
        return Response("the session is not reachable", status_code=502)
    out = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP}
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers=out,
        background=BackgroundTask(resp.aclose),
    )


def _clean_code(code: int | None) -> int:
    # 1005/1006 are never sent on the wire; anything outside the range is not a code
    if code is None or code in (1005, 1006) or not 1000 <= code < 5000:
        return 1000
    return code


async def proxy_ws(ws: WebSocket, url: str, on_activity) -> None:
    try:
        upstream = await websockets.connect(url, open_timeout=10, max_size=16 * 2**20)
    except websockets.InvalidStatus as exc:
        log.info("upstream refused %s: %s", url, exc.response.status_code)
        await ws.close(code=1008)
        return
    except (OSError, TimeoutError, websockets.WebSocketException) as exc:
        log.info("upstream %s: %s", url, exc)
        await ws.close(code=1011)
        return

    await ws.accept()

    async def to_upstream() -> int:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return message.get("code", 1000)
            on_activity()
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    async def to_client() -> int:
        try:
            async for data in upstream:
                on_activity()
                if isinstance(data, str):
                    await ws.send_text(data)
                else:
                    await ws.send_bytes(data)
        except websockets.ConnectionClosed as exc:
            return exc.rcvd.code if exc.rcvd else 1000
        return _clean_code(upstream.close_code)

    down = asyncio.ensure_future(to_upstream())
    up = asyncio.ensure_future(to_client())
    try:
        done, pending = await asyncio.wait({down, up}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if up in done:
            code = up.result() if not up.cancelled() and up.exception() is None else 1011
            try:
                await ws.close(code=_clean_code(code))
            except RuntimeError:
                pass  # the client went first
        else:
            code = down.result() if down.exception() is None else 1000
            await upstream.close(code=_clean_code(code))
    except WebSocketDisconnect:
        pass
    finally:
        for task in (down, up):
            task.cancel()
        await upstream.close()
