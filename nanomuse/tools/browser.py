"""Browser tool. The page is summarised for the model as readable text plus a numbered list of
interactive elements; actions refer to those numbers.

Where the page renders is a :class:`~nanomuse.tools.browser_backends.BrowserBackend`: a
Playwright Chromium on the computer (``pip install "nanomuse[browser]" && playwright install
chromium``), with a profile kept under the workspace so logins survive a restart; or the
nanoMuse app's own WebView on the phone, signed in to whatever the user is signed in to.
``backend="auto"`` takes Playwright when it is installed and the phone otherwise.

What the browser shows is also shown to the user: after every action a JPEG frame of the
viewport goes to ``on_frame`` (the app turns that into a live browser card), and the user can
take over — click, type, open a URL — through :meth:`Browser.user_action`, or, on the phone,
by pulling the very same WebView into view. That is how a login happens: the agent stops at
the form, the user signs in, the agent carries on with the page as the user left it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr

from nanomuse.logger import logger
from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool, CallAssessment
from nanomuse.tools.browser_backends import (
    PROFILES,
    BrowserBackend,
    BrowserProfile,
    DeviceBackend,
    PlaywrightBackend,
    profile_named,
)
from nanomuse.tools.web import host_of

# the default (desktop) viewport; the frame the user sees is whatever the backend's profile is
VIEWPORT = PROFILES["desktop"].viewport

# what a fetch hands back to the model at most
FETCH_MAX_CHARS = 20_000


@dataclass
class BrowserFrame:
    """One picture of the browser, right after something happened."""

    url: str
    title: str
    # a caption for people: "Opened example.com", "Clicked 'Sign in'", "You typed"
    action: str
    jpeg: bytes
    by_user: bool = False
    # the chat this belongs to when known (user actions come from the app, not an agent run)
    thread: str | None = None
    # "playwright" or "device": the app offers the phone's own take-over for the second
    backend: str = ""
    width: int = 0
    height: int = 0


_ANNOTATE_JS = """
(maxElements) => {
  const sel = 'a[href], button, input, textarea, select, summary, [role=button], [role=link], [role=tab], [role=menuitem], [onclick], [contenteditable=true]';
  document.querySelectorAll('[data-om-idx]').forEach(e => e.removeAttribute('data-om-idx'));
  const visible = (e) => {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const els = Array.from(document.querySelectorAll(sel)).filter(visible).slice(0, maxElements);
  return els.map((e, i) => {
    e.setAttribute('data-om-idx', String(i));
    const text = (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.getAttribute('title') || e.getAttribute('name') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    return { i, tag: e.tagName.toLowerCase(), type: e.getAttribute('type') || '', text, href: (e.getAttribute('href') || '').slice(0, 120) };
  });
}
"""

_TEXT_JS = "() => document.body ? document.body.innerText : ''"

_LABEL_JS = """
(i) => {
  const e = document.querySelector('[data-om-idx="' + i + '"]');
  return e ? (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || '').trim() : '';
}
"""


def playwright_available() -> bool:
    return PlaywrightBackend.available()


class Browser(BaseTool):
    name: str = "browser"
    description: str = (
        "Control a real web browser to complete tasks on websites (search, read, fill forms, click). "
        "Actions: `navigate` (url), `extract` (read current page + numbered interactive elements), "
        "`click` (index), `type` (index, text, submit=true to press Enter), `press` (key, e.g. 'Enter'), "
        "`scroll` (direction up|down), `back`, `screenshot`, `fetch` (url: GET a URL with the browser's "
        "cookies and return the raw body — a signed-in request without driving the page; method/body "
        "for POST), `profile` (profile: mobile|desktop, or user_agent/width/height: how the browser "
        "presents itself), `close`. After navigate/click/type the tool returns the new page state. "
        "The user watches the browser live in the app and can take over it: never enter passwords, "
        "one-time codes or payment details yourself — when a page needs a sign-in or a human "
        "decision, stop and `ask_user` to do it in the browser view, then continue. Leave the browser "
        "open when you finish (no `close` unless asked) so the user can look at or take over the page."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "navigate",
                    "extract",
                    "click",
                    "type",
                    "press",
                    "scroll",
                    "back",
                    "screenshot",
                    "fetch",
                    "profile",
                    "close",
                ],
            },
            "url": {"type": "string"},
            "index": {"type": "integer", "description": "Element number from the last page state."},
            "text": {"type": "string"},
            "submit": {"type": "boolean"},
            "key": {"type": "string"},
            "direction": {"type": "string", "enum": ["up", "down"]},
            "method": {"type": "string", "description": "For fetch: GET (default) or POST."},
            "body": {"type": "string", "description": "For fetch with POST: the request body."},
            "profile": {"type": "string", "enum": ["mobile", "desktop"]},
            "user_agent": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True

    headless: bool = True
    timeout_ms: int = 30_000
    workspace: Path = Path("./workspace")
    # "auto" | "playwright" | "device"
    backend_mode: str = "auto"
    # the phone link, for the device backend; set by the app
    link: Any = None
    # the starting profile: "desktop" for Playwright, the phone's own for the device
    default_profile: str = ""
    # receives a BrowserFrame after every action; set by the app
    on_frame: Callable[[BrowserFrame], None] | None = None
    frame_quality: int = 55

    _backend: Any = PrivateAttr(default=None)
    _lock: Any = PrivateAttr(default=None)
    # what the user did since the model last looked at the page
    _user_actions: list[str] = PrivateAttr(default_factory=list)
    # the host of the page last summarised, for the Sentinel's view of the next action
    _last_host: str | None = PrivateAttr(default=None)

    # ------------------------------------------------------------------ lifecycle
    @property
    def profile_dir(self) -> Path:
        """Playwright's persistent profile: cookies and logins, kept under the workspace."""
        return self.workspace / "browser-profile"

    def _pick_backend(self) -> BrowserBackend:
        """The backend for a new session. A running one is kept until it is closed."""
        current = self._backend
        if current is not None and current.open:
            return current
        mode = self.backend_mode
        device_ready = self.link is not None and self.link.browser_device is not None
        if mode == "device" or (mode == "auto" and not playwright_available()):
            if not device_ready:
                raise RuntimeError(
                    "no browser is available: playwright is not installed here and no phone "
                    "with the nanoMuse app is connected"
                    if mode == "auto"
                    else "no phone with the nanoMuse app is connected to lend its browser"
                )
            backend: BrowserBackend = DeviceBackend(
                self.link,
                timeout_s=self.timeout_ms / 1000,
                profile=profile_named(self.default_profile) if self.default_profile else None,
            )
        else:
            if not playwright_available():
                raise RuntimeError(
                    "playwright is not installed. Run: pip install 'nanomuse[browser]' && playwright install chromium"
                )
            backend = PlaywrightBackend(
                self.profile_dir,
                headless=self.headless,
                timeout_ms=self.timeout_ms,
                profile=profile_named(self.default_profile or "desktop"),
            )
        self._backend = backend
        return backend

    @property
    def backend(self) -> BrowserBackend | None:
        return self._backend

    @property
    def backend_kind(self) -> str:
        """Which backend a session would use now: "playwright", "device" or ""."""
        if self._backend is not None and self._backend.open:
            return str(self._backend.kind)
        if self.backend_mode == "device":
            return "device" if self.link is not None and self.link.browser_device else ""
        if playwright_available():
            return "playwright"
        return "device" if self.link is not None and self.link.browser_device else ""

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def open(self) -> bool:
        return self._backend is not None and self._backend.open

    @property
    def viewport(self) -> dict[str, int]:
        return self._backend.profile.viewport if self._backend is not None else VIEWPORT

    async def _frame(
        self, backend: BrowserBackend, action: str, by_user: bool = False, thread: str | None = None
    ) -> None:
        if self.on_frame is None:
            return
        try:
            jpeg = await backend.screenshot(self.frame_quality)
            url = await backend.url()
            title = await backend.title()
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser frame: {}", exc)
            return
        if not jpeg:
            return
        try:
            self.on_frame(
                BrowserFrame(
                    url,
                    title,
                    action,
                    jpeg,
                    by_user,
                    thread,
                    backend=backend.kind,
                    width=backend.profile.width,
                    height=backend.profile.height,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser frame listener failed: {}", exc)

    async def _label(self, backend: BrowserBackend, index: int) -> str:
        try:
            text = await backend.evaluate(_LABEL_JS, int(index))
        except Exception:  # noqa: BLE001
            return f"[{index}]"
        text = " ".join(str(text or "").split())
        return f"'{text[:40]}'" if text else f"[{index}]"

    async def cleanup(self) -> None:
        backend = self._backend
        self._backend = None
        if backend is not None:
            await backend.close()

    # ------------------------------------------------------------------ sentinel
    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = args.get("action", "")
        target = (
            host_of(str(args.get("url", "")))
            if action in ("navigate", "fetch")
            else self._current_host()
        )
        detail = (
            args.get("url")
            or args.get("text")
            or args.get("index")
            or args.get("key")
            or args.get("profile")
            or ""
        )
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            egress=action not in ("extract", "screenshot", "close", "scroll", "profile"),
            egress_target=target,
            summary=f"browser.{action} {str(detail)[:120]}".strip(),
        )

    def _current_host(self) -> str | None:
        return self._last_host

    # ------------------------------------------------------------------ execution
    async def execute(
        self,
        action: str = "",
        url: str | None = None,
        index: int | None = None,
        text: str | None = None,
        submit: bool = False,
        key: str | None = None,
        direction: str = "down",
        method: str | None = None,
        body: str | None = None,
        profile: str | None = None,
        user_agent: str | None = None,
        width: int | None = None,
        height: int | None = None,
        **_: Any,
    ) -> ToolResult:
        if action == "close":
            await self.cleanup()
            return ToolResult(output="Browser closed.")
        async with self.lock:
            try:
                backend = self._pick_backend()
            except RuntimeError as exc:
                return ToolResult.fail(str(exc))
            try:
                if action == "fetch":
                    return await self._fetch(backend, url, method, body)
                if action == "profile":
                    return await self._profile(backend, profile, user_agent, width, height)
                return await self._act(backend, action, url, index, text, submit, key, direction)
            except Exception as exc:  # noqa: BLE001 – playwright raises many error types
                return ToolResult.fail(
                    f"browser error: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
                )

    async def _act(
        self,
        backend: BrowserBackend,
        action: str,
        url: str | None,
        index: int | None,
        text: str | None,
        submit: bool,
        key: str | None,
        direction: str,
    ) -> ToolResult:
        await backend.ensure()
        if action == "navigate":
            if not url:
                return ToolResult.fail("`url` is required")
            if not url.lower().startswith(("http://", "https://")):
                url = "https://" + url
            await backend.goto(url)
            await self._frame(backend, f"Opened {host_of(url) or url}")
            return await self._state(backend, brief=True)
        if action == "extract":
            await self._frame(backend, "Read the page")
            return await self._state(backend, brief=False)
        if action == "click":
            if index is None:
                return ToolResult.fail("`index` is required")
            label = await self._label(backend, int(index))
            await backend.click_element(int(index))
            await backend.settle(self.timeout_ms)
            await self._frame(backend, f"Clicked {label}")
            return await self._state(backend, brief=True)
        if action == "type":
            if index is None or text is None:
                return ToolResult.fail("`index` and `text` are required")
            label = await self._label(backend, int(index))
            await backend.fill_element(int(index), text)
            if submit:
                await backend.press("Enter")
                await backend.settle(self.timeout_ms)
            await self._frame(backend, f"Typed into {label}" + (" and submitted" if submit else ""))
            return await self._state(backend, brief=True)
        if action == "press":
            await backend.press(key or "Enter")
            await backend.settle(self.timeout_ms)
            await self._frame(backend, f"Pressed {key or 'Enter'}")
            return await self._state(backend, brief=True)
        if action == "scroll":
            step = backend.profile.height * 0.85
            await backend.scroll(-step if direction == "up" else step)
            await self._frame(backend, f"Scrolled {direction}")
            return await self._state(backend, brief=True)
        if action == "back":
            await backend.back()
            await backend.settle(self.timeout_ms)
            await self._frame(backend, "Went back")
            return await self._state(backend, brief=True)
        if action == "screenshot":
            shots = self.workspace / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            path = shots / f"{time.strftime('%Y%m%d-%H%M%S')}.jpg"
            path.write_bytes(await backend.screenshot(85))
            await self._frame(backend, "Took a screenshot")
            return ToolResult(output=f"Screenshot saved to {path}", system=str(path))
        return ToolResult.fail(f"unknown action '{action}'")

    async def _fetch(
        self, backend: BrowserBackend, url: str | None, method: str | None, body: str | None
    ) -> ToolResult:
        if not url:
            return ToolResult.fail("`url` is required")
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        result = await backend.fetch(url, method=(method or "GET").upper(), body=body)
        text = str(result.get("body") or "")
        ctype = str((result.get("headers") or {}).get("content-type", ""))
        note = ""
        if len(text) > FETCH_MAX_CHARS:
            note = f"\n... [truncated, {len(text)} chars]"
            text = text[:FETCH_MAX_CHARS]
        head = f"HTTP {result.get('status')} {result.get('url') or url}"
        if ctype:
            head += f" ({ctype.split(';')[0].strip()})"
        return ToolResult(output=f"{head}\n\n{text}{note}")

    async def _profile(
        self,
        backend: BrowserBackend,
        profile: str | None,
        user_agent: str | None,
        width: int | None,
        height: int | None,
    ) -> ToolResult:
        prof: BrowserProfile = profile_named(
            profile or "", user_agent, width, height, base=backend.profile
        )
        await backend.set_profile(prof)
        ua = prof.user_agent or "the browser's own"
        return ToolResult(
            output=f"Profile: {prof.name}, {prof.width}×{prof.height}, user agent {ua}."
        )

    # ------------------------------------------------------------------ the user takes over
    async def user_action(
        self,
        action: str,
        thread: str | None = None,
        *,
        x: float | None = None,
        y: float | None = None,
        text: str | None = None,
        key: str | None = None,
        dy: float | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        """An action by the user from the app. ``x``/``y`` are fractions of the frame.

        Not reviewed by the Sentinel: it is the user acting, on their own browser, with
        their own hands. What they did is reported to the model the next time it looks.
        """
        async with self.lock:
            backend = self._pick_backend()
            await backend.ensure()
            vp = backend.profile.viewport
            if action == "click":
                if x is None or y is None:
                    raise ValueError("click needs x and y")
                px = min(max(float(x), 0.0), 1.0) * vp["width"]
                py = min(max(float(y), 0.0), 1.0) * vp["height"]
                await backend.click_at(px, py)
                await backend.settle(self.timeout_ms)
                caption, note = "You tapped the page", f"clicked at ({int(px)}, {int(py)})"
            elif action == "type":
                if text is None:
                    raise ValueError("type needs text")
                await backend.type_text(text)
                caption, note = "You typed", f"typed {len(text)} characters"
            elif action == "key":
                await backend.press(key or "Enter")
                await backend.settle(self.timeout_ms)
                caption, note = f"You pressed {key or 'Enter'}", f"pressed {key or 'Enter'}"
            elif action == "scroll":
                await backend.scroll(float(dy if dy is not None else 600))
                caption, note = "You scrolled", "scrolled"
            elif action == "navigate":
                if not url:
                    raise ValueError("navigate needs a url")
                if not url.lower().startswith(("http://", "https://")):
                    url = "https://" + url
                await backend.goto(url)
                caption, note = f"You opened {host_of(url) or url}", f"opened {url}"
            elif action == "look":
                caption, note = "Live view", ""
            elif action == "handed_back":
                # the phone's take-over sheet closed: the user drove the real WebView
                caption, note = "You handed the page back", "used the page in the app"
            else:
                raise ValueError(f"unknown action '{action}'")
            if note:
                self._user_actions.append(note)
                logger.info("browser: user {}", note)
            await self._frame(backend, caption, by_user=True, thread=thread)
            return {"url": await backend.url(), "title": await backend.title()}

    async def _state(self, backend: BrowserBackend, brief: bool) -> ToolResult:
        max_text = 3000 if brief else 9000
        max_elements = 60 if brief else 150
        elements = await backend.evaluate(_ANNOTATE_JS, max_elements) or []
        text = await backend.evaluate(_TEXT_JS)
        text = " ".join(str(text).split()) if text else ""
        if len(text) > max_text:
            text = text[:max_text] + f" ... [truncated, {len(text)} chars]"
        url = await backend.url()
        self._last_host = host_of(url) if url else None
        lines = []
        if self._user_actions:
            done = "; ".join(self._user_actions[-8:])
            self._user_actions.clear()
            lines += [
                f"Note: the user took over the browser in the app and {done}. "
                "Continue from the page as it is now; do not redo what they did.",
                "",
            ]
        lines += [
            f"URL: {url}",
            f"Title: {await backend.title()}",
            "",
            "## Page text",
            text,
            "",
            "## Interactive elements",
        ]
        for e in elements:
            desc = (
                f"[{e['i']}] <{e['tag']}{(' type=' + e['type']) if e['type'] else ''}> {e['text']}"
            )
            if e.get("href"):
                desc += f" → {e['href']}"
            lines.append(desc)
        if not elements:
            lines.append("(none)")
        return ToolResult(output="\n".join(lines))


__all__ = ["VIEWPORT", "Browser", "BrowserFrame", "playwright_available"]
