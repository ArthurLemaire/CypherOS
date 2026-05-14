"""Sessions: one private nanoMuse per visitor, for a while, within a budget."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import secrets
import socket
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from .config import Lane, Settings
from .runner import Runner, RunnerError

log = logging.getLogger("showcase.sessions")

CST = timezone(timedelta(hours=8))


class Refused(Exception):
    """A request the policy says no to. ``status`` is the HTTP status to answer with."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Provider:
    """A visitor's own model: their key, their bill, no budget of ours."""

    base_url: str
    api_key: str
    model: str


@dataclass
class Session:
    id: str
    token: str  # the nanoMuse access token, what the phone pastes
    llm_key: str  # what the container presents to the model proxy
    ip: str
    created_at: float
    expires_at: float
    container: str
    address: str = ""  # where the gateway reaches the container
    port: int = 8787
    byok: Provider | None = None
    last_seen: float = field(default=0.0)
    requests: int = 0
    tokens: int = 0
    ended: bool = False

    @property
    def http_base(self) -> str:
        return f"http://{self.address}:{self.port}"

    @property
    def ws_base(self) -> str:
        return f"ws://{self.address}:{self.port}"

    def public(self, settings: Settings, now: float) -> dict:
        return {
            "id": self.id,
            "server_url": settings.session_origin(self.id),
            "token": self.token,
            "expires_at": int(self.expires_at),
            "ttl_s": max(0, int(self.expires_at - now)),
            "byok": self.byok is not None,
            "quota": {
                "requests": None if self.byok else settings.session_requests,
                "tokens": None if self.byok else settings.session_tokens,
                "requests_used": self.requests,
                "tokens_used": self.tokens,
            },
        }


def _new_id() -> str:
    # 13 lowercase letters and digits: a DNS label, which is what a session id becomes
    return base64.b32encode(secrets.token_bytes(8)).decode().rstrip("=").lower()


def _day_key(now: float) -> str:
    return datetime.fromtimestamp(now, CST).strftime("%Y-%m-%d")


def _resolve(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def check_provider(base_url: str, allowed_hosts: tuple[str, ...], resolve=_resolve) -> str:
    """A visitor's provider URL, normalised, or ``Refused``. HTTPS only, to a known provider
    host, and never to an address inside our own network."""
    url = urlparse(base_url.strip())
    if url.scheme != "https" or not url.hostname:
        raise Refused(400, "bad_provider", "The model API address must start with https://")
    host = url.hostname.lower()
    if host not in allowed_hosts and not any(host.endswith("." + h) for h in allowed_hosts):
        raise Refused(400, "provider_not_allowed", f"{host} is not a supported model provider")
    try:
        addresses = resolve(host, url.port or 443)
    except OSError as exc:
        raise Refused(400, "bad_provider", f"{host} does not resolve") from exc
    if not addresses:
        raise Refused(400, "bad_provider", f"{host} does not resolve")
    for raw in addresses:
        if not ipaddress.ip_address(raw).is_global:
            raise Refused(400, "bad_provider", f"{host} points inside a private network")
    return f"{url.scheme}://{url.netloc}{url.path.rstrip('/')}"


class SessionManager:
    def __init__(
        self,
        settings: Settings,
        runner: Runner,
        http: httpx.AsyncClient | None = None,
        clock=time.time,
    ) -> None:
        self.s = settings
        self.runner = runner
        self.http = http or httpx.AsyncClient(timeout=5)
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self._starts: dict[str, deque[float]] = defaultdict(deque)  # per ip, last 24 h
        self._day = _day_key(clock())
        self.day_requests = 0
        self.day_tokens = 0
        self.internal_url = settings.internal_url
        self.resolve = _resolve  # DNS, replaceable in tests
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        for name in await self.runner.leftovers():
            log.info("removing leftover %s", name)
            await self.runner.stop(name)
        if not self.internal_url:
            addr = await self.runner.gateway_address()
            if not addr:
                raise RuntimeError(
                    "INTERNAL_URL is not set and the sessions network has no gateway address"
                )
            self.internal_url = f"http://{addr}:{self.s.listen_port}"
        log.info("containers reach the gateway at %s", self.internal_url)

    async def shutdown(self) -> None:
        for sid in list(self.sessions):
            await self.end(sid, reason="gateway stopping")

    async def reap_forever(self, interval: float = 15) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.reap_once()
            except Exception:  # noqa: BLE001
                log.exception("reaper")

    async def reap_once(self) -> None:
        now = self.clock()
        for sid, sess in list(self.sessions.items()):
            if sess.ended:
                continue
            if now >= sess.expires_at:
                await self.end(sid, reason="time is up")
            elif now - sess.last_seen >= self.s.idle_ttl_s:
                await self.end(sid, reason="idle")

    # ------------------------------------------------------------------ creating
    def _roll_day(self) -> None:
        key = _day_key(self.clock())
        if key != self._day:
            self._day = key
            self.day_requests = 0
            self.day_tokens = 0

    def active(self) -> list[Session]:
        return [s for s in self.sessions.values() if not s.ended]

    def _check_policy(self, ip: str) -> None:
        now = self.clock()
        active = self.active()
        if len(active) >= self.s.max_sessions:
            raise Refused(
                503, "full", "Every demo Muse is taken right now. Try again in a few minutes."
            )
        mine = [s for s in active if s.ip == ip]
        if len(mine) >= self.s.per_ip_active:
            raise Refused(
                429, "already_running", "You already have a demo running. Finish that one first."
            )
        starts = self._starts[ip]
        while starts and now - starts[0] > 86400:
            starts.popleft()
        if len(starts) >= self.s.per_ip_daily:
            raise Refused(429, "daily_limit", "That is all the demo sessions for today from here.")

    def _env_for(self, sess: Session) -> dict[str, str]:
        s = self.s
        base = f"{self.internal_url.rstrip('/')}/llm/{sess.id}"
        if sess.byok:
            main = gui = Lane("openai", sess.byok.model, sess.byok.base_url, sess.byok.api_key)
        else:
            main, gui = s.main, s.gui
        env = {
            "NANOMUSE_SERVER_TOKEN": sess.token,
            "NANOMUSE_LLM_PROVIDER": main.provider,
            "NANOMUSE_LLM_MODEL": main.model,
            "NANOMUSE_LLM_BASE_URL": f"{base}/main",
            "NANOMUSE_LLM_API_KEY": sess.llm_key,
            "NANOMUSE_GUI_ENABLED": "1",
            "NANOMUSE_GUI_PROVIDER": gui.provider,
            "NANOMUSE_GUI_MODEL": gui.model,
            "NANOMUSE_GUI_BASE_URL": f"{base}/gui",
            "NANOMUSE_GUI_API_KEY": sess.llm_key,
            "NANOMUSE_LOG_LEVEL": "warning",
        }
        env.update(s.extra_env)
        return env

    async def create(self, ip: str, byok: Provider | None = None) -> Session:
        if byok and not self.s.byok_enabled:
            raise Refused(400, "byok_off", "Bringing your own key is turned off on this showcase.")
        if not byok and not self.s.main.configured:
            raise Refused(
                503, "no_model", "This showcase has no demo model configured; bring your own key."
            )
        async with self._lock:
            self._roll_day()
            self._check_policy(ip)
            now = self.clock()
            sid = _new_id()
            sess = Session(
                id=sid,
                token=secrets.token_urlsafe(24),
                llm_key=secrets.token_urlsafe(24),
                ip=ip,
                created_at=now,
                expires_at=now + self.s.session_ttl_s,
                container=f"nm-{sid}",
                port=self.s.container_port,
                byok=byok,
                last_seen=now,
            )
            self.sessions[sid] = sess
            self._starts[ip].append(now)
        try:
            sess.address = await self.runner.start(sess.container, self._env_for(sess))
            await self._wait_ready(sess)
        except (RunnerError, Refused):
            await self.end(sid, reason="failed to start")
            raise
        except Exception as exc:  # noqa: BLE001
            await self.end(sid, reason="failed to start")
            raise Refused(503, "start_failed", "Could not start a demo Muse. Try again.") from exc
        log.info("session %s started for %s (byok=%s)", sid, ip, byok is not None)
        return sess

    async def _wait_ready(self, sess: Session) -> None:
        deadline = self.clock() + self.s.start_timeout_s
        while True:
            try:
                r = await self.http.get(f"{sess.http_base}/api/health")
                if r.status_code == 200 and r.json().get("ok"):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            if self.clock() >= deadline:
                raise Refused(503, "start_timeout", "The demo Muse took too long to start.")
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------ using
    def get(self, sid: str) -> Session | None:
        sess = self.sessions.get(sid)
        return None if sess is None or sess.ended else sess

    def authenticate(self, sid: str, token: str | None) -> Session:
        sess = self.get(sid)
        if sess is None or not token or not secrets.compare_digest(token, sess.token):
            raise Refused(404, "no_session", "No such session.")
        return sess

    def touch(self, sess: Session) -> None:
        sess.last_seen = self.clock()

    async def end(self, sid: str, reason: str = "") -> None:
        sess = self.sessions.get(sid)
        if sess is None or sess.ended:
            return
        sess.ended = True
        log.info(
            "session %s ended: %s (%d requests, %d tokens)", sid, reason, sess.requests, sess.tokens
        )
        await self.runner.stop(sess.container)
        # keep the record a little so late requests get a clear "no such session"
        asyncio.get_running_loop().call_later(300, self.sessions.pop, sid, None)

    # ------------------------------------------------------------------ model budget
    def llm_lane(self, sess: Session, key: str | None, lane: str) -> Lane:
        """Which upstream a container's model call goes to — after the budget check."""
        if not key or not secrets.compare_digest(key, sess.llm_key):
            raise Refused(401, "bad_key", "invalid api key")
        if sess.byok:
            return Lane("openai", sess.byok.model, sess.byok.base_url, sess.byok.api_key)
        upstream = self.s.lane(lane)
        if upstream is None or not upstream.configured:
            raise Refused(404, "no_lane", f"no model lane '{lane}'")
        self._roll_day()
        if sess.requests >= self.s.session_requests or sess.tokens >= self.s.session_tokens:
            raise Refused(
                429,
                "session_budget",
                "This demo session has used up its model budget. Start a new one, or bring your own key.",
            )
        if self.day_requests >= self.s.daily_requests or self.day_tokens >= self.s.daily_tokens:
            raise Refused(
                429,
                "daily_budget",
                "The showcase has spent today's model budget. Bring your own key, or come back tomorrow.",
            )
        return upstream

    def record(self, sess: Session, tokens: int) -> None:
        sess.requests += 1
        sess.tokens += tokens
        if not sess.byok:
            self.day_requests += 1
            self.day_tokens += tokens

    def stats(self) -> dict:
        self._roll_day()
        active = self.active()
        return {
            "active_sessions": len(active),
            "max_sessions": self.s.max_sessions,
            "day": self._day,
            "day_requests": self.day_requests,
            "day_tokens": self.day_tokens,
        }
