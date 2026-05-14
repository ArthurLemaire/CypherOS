"""The model proxy: ``/llm/<session>/<lane>/...`` → the provider, with the real key.

A session's container is told its model lives at ``http://gateway/llm/<id>/main`` and is given
a per-session key. Calls come here, the budget is checked, the demo key is put on, and the
request goes out unchanged otherwise — streaming included. The reply's ``usage`` (asked for
explicitly on streams) is what the budget counts; when a provider sends none, size stands in.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .sessions import Refused, Session, SessionManager

log = logging.getLogger("showcase.llm")

_SKIP_REQUEST_HEADERS = {
    "host",
    "authorization",
    "content-length",
    "connection",
    "transfer-encoding",
    "accept-encoding",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
}
_SKIP_RESPONSE_HEADERS = {"connection", "transfer-encoding", "content-length", "content-encoding"}
_USAGE = re.compile(rb'"usage"\s*:\s*\{')


def refusal(exc: Refused) -> JSONResponse:
    """An error in the shape OpenAI clients understand, so the agent can tell the user."""
    return JSONResponse(
        {"error": {"message": exc.message, "type": exc.code, "code": exc.code}},
        status_code=exc.status,
    )


def extract_usage(payload: bytes) -> int | None:
    """Total tokens from a JSON reply or an SSE stream (chat completions or Responses API)."""
    if not _USAGE.search(payload):
        return None
    text = payload.decode("utf-8", errors="replace")
    candidates: list[str] = []
    if text.lstrip().startswith("{"):
        candidates.append(text)
    else:
        for line in text.splitlines():
            if line.startswith("data:") and '"usage"' in line:
                candidates.append(line[5:].strip())
    for raw in reversed(candidates):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        usage = obj.get("usage") if isinstance(obj, dict) else None
        if not usage and isinstance(obj, dict):
            usage = (obj.get("response") or {}).get("usage")
        if not isinstance(usage, dict):
            continue
        total = usage.get("total_tokens")
        if total is None:
            total = (usage.get("prompt_tokens") or usage.get("input_tokens") or 0) + (
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )
        if isinstance(total, int | float):
            return int(total)
    return None


def prepare_body(body: bytes, path: str) -> bytes:
    """Ask a streaming chat completion to report usage in its last chunk."""
    if not body or not path.endswith("chat/completions"):
        return body
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, dict) and data.get("stream"):
        opts = data.get("stream_options")
        if not isinstance(opts, dict):
            opts = {}
        if not opts.get("include_usage"):
            opts["include_usage"] = True
            data["stream_options"] = opts
            return json.dumps(data).encode()
    return body


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


async def forward(
    request: Request,
    manager: SessionManager,
    client: httpx.AsyncClient,
    sess: Session,
    lane: str,
    path: str,
) -> Response:
    try:
        upstream = manager.llm_lane(sess, bearer(request), lane)
    except Refused as exc:
        return refusal(exc)
    manager.touch(sess)
    body = prepare_body(await request.body(), path)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQUEST_HEADERS}
    headers["authorization"] = f"Bearer {upstream.api_key}"
    url = f"{upstream.base_url.rstrip('/')}/{path.lstrip('/')}"
    if request.url.query:
        url += f"?{request.url.query}"
    try:
        req = client.build_request(request.method, url, headers=headers, content=body)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        log.warning("upstream %s: %s", url, exc)
        return refusal(Refused(502, "upstream", f"The model provider could not be reached: {exc}"))

    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _SKIP_RESPONSE_HEADERS}
    sent = len(body)

    if "text/event-stream" in resp.headers.get("content-type", ""):

        async def stream() -> AsyncIterator[bytes]:
            chunks: list[bytes] = []
            try:
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    yield chunk
            finally:
                payload = b"".join(chunks)
                manager.record(sess, extract_usage(payload) or (sent + len(payload)) // 4)

        return StreamingResponse(
            stream(),
            status_code=resp.status_code,
            headers=out_headers,
            background=BackgroundTask(resp.aclose),
        )

    payload = await resp.aread()
    await resp.aclose()
    if resp.status_code < 400:
        manager.record(sess, extract_usage(payload) or (sent + len(payload)) // 4)
    return Response(payload, status_code=resp.status_code, headers=out_headers)
