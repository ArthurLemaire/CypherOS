"""Where the browser tool's pages actually render: a Playwright Chromium on the computer, or
the app's own WebView on the phone.

The tool (:mod:`nanomuse.tools.browser`) speaks to one :class:`BrowserBackend` and never to
Playwright or the phone directly, so the page summary, the numbered elements, the frames the
user watches and the Sentinel's view of an action are the same on both.

Two backends:

* :class:`PlaywrightBackend` — Chromium through Playwright, with a **persistent profile**
  under the workspace, so a login made once (by the user taking over) is still there after
  a restart.
* :class:`DeviceBackend` — the Android app's offscreen WebView, reached through the phone
  link (``browser`` requests over the app's WebSocket). Its cookies are the phone's: what
  the user is signed in to on the phone, the agent is too.

Both take a :class:`BrowserProfile` — user agent and viewport — with ``mobile`` and
``desktop`` presets, and can ``fetch`` a URL with the page's cookies (rung two of the ladder:
a signed-in request without driving the screen).
"""

from __future__ import annotations

import asyncio
import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanomuse.logger import logger

if TYPE_CHECKING:
    from nanomuse.phone.link import PhoneLink


# ---------------------------------------------------------------------- profiles
@dataclass(frozen=True)
class BrowserProfile:
    """How the browser presents itself: user agent and viewport."""

    name: str
    width: int
    height: int
    user_agent: str = ""  # empty: the backend's own default
    mobile: bool = False
    scale: float = 1.0

    @property
    def viewport(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height}


DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Mobile Safari/537.36"
)

PROFILES: dict[str, BrowserProfile] = {
    "desktop": BrowserProfile("desktop", 1280, 900, DESKTOP_UA, mobile=False),
    "mobile": BrowserProfile("mobile", 412, 915, MOBILE_UA, mobile=True, scale=2.0),
}


def profile_named(
    name: str = "",
    user_agent: str | None = None,
    width: int | None = None,
    height: int | None = None,
    base: BrowserProfile | None = None,
) -> BrowserProfile:
    """A preset by name, optionally with fields overridden (that makes it ``custom``)."""
    prof = PROFILES.get(name) or base or PROFILES["desktop"]
    changes: dict[str, Any] = {}
    if user_agent:
        changes["user_agent"] = user_agent
    if width:
        changes["width"] = max(320, min(int(width), 3840))
    if height:
        changes["height"] = max(320, min(int(height), 4320))
    if changes:
        prof = replace(prof, name="custom", **changes)
    return prof


# ---------------------------------------------------------------------- the interface
class BrowserBackend(ABC):
    """One browser page, wherever it renders. All coordinates are CSS pixels of the viewport."""

    kind: str = ""
    profile: BrowserProfile = PROFILES["desktop"]

    @property
    @abstractmethod
    def open(self) -> bool:
        """A page exists right now."""

    @abstractmethod
    async def ensure(self) -> None:
        """Open the browser and a page if there is none."""

    @abstractmethod
    async def goto(self, url: str) -> None: ...

    @abstractmethod
    async def evaluate(self, js: str, arg: Any = None) -> Any:
        """Run ``(js)(arg)`` in the page and return its JSON-able result."""

    @abstractmethod
    async def click_at(self, x: float, y: float) -> None: ...

    @abstractmethod
    async def type_text(self, text: str) -> None:
        """Type into whatever has the focus."""

    @abstractmethod
    async def press(self, key: str) -> None: ...

    @abstractmethod
    async def scroll(self, dy: float) -> None: ...

    @abstractmethod
    async def back(self) -> None: ...

    @abstractmethod
    async def screenshot(self, quality: int = 55) -> bytes:
        """The viewport as JPEG."""

    @abstractmethod
    async def url(self) -> str: ...

    @abstractmethod
    async def title(self) -> str: ...

    @abstractmethod
    async def settle(self, timeout_ms: int) -> None:
        """Wait for a navigation that an action may have started."""

    @abstractmethod
    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        """A request with the page's cookies. ``{"status", "headers", "body", "url"}``."""

    @abstractmethod
    async def set_profile(self, profile: BrowserProfile) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    # ------------------------------------------------------------------ shared behaviour
    async def click_element(self, index: int) -> None:
        """Click a numbered element: scroll it into view, then click its centre."""
        rect = await self.evaluate(_CENTER_JS, int(index))
        if not rect:
            raise LookupError(f"element [{index}] is no longer on the page")
        await self.click_at(float(rect["x"]), float(rect["y"]))

    async def fill_element(self, index: int, text: str) -> None:
        """Put ``text`` into a numbered field the way a framework notices (native setter +
        input events); falls back to typing when the element is not a plain field."""
        ok = await self.evaluate(_FILL_JS, {"index": int(index), "text": text})
        if not ok:
            await self.click_element(index)
            await self.type_text(text)


# The centre of element [i] in viewport CSS pixels, after scrolling it into view.
_CENTER_JS = """
(i) => {
  const e = document.querySelector('[data-om-idx="' + i + '"]');
  if (!e) return null;
  e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height};
}
"""

# Fill a field so React/Vue/Angular see it: focus, set through the prototype's own setter,
# then fire input + change. Returns false for anything that is not a field (a contenteditable
# gets execCommand, which most editors listen to).
_FILL_JS = """
({index, text}) => {
  const e = document.querySelector('[data-om-idx="' + index + '"]');
  if (!e) return false;
  e.scrollIntoView({block: 'center', inline: 'center'});
  e.focus();
  const tag = e.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea') {
    const proto = tag === 'input' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(e, text);
    e.dispatchEvent(new Event('input', {bubbles: true}));
    e.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (tag === 'select') {
    const opt = Array.from(e.options).find(o => o.value === text || o.text.trim() === text);
    if (!opt) return false;
    e.value = opt.value;
    e.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (e.isContentEditable) {
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
    return true;
  }
  return false;
}
"""


# ---------------------------------------------------------------------- playwright
class PlaywrightBackend(BrowserBackend):
    """Chromium through Playwright, with a persistent profile so logins survive restarts."""

    kind = "playwright"

    def __init__(
        self,
        profile_dir: Path,
        headless: bool = True,
        timeout_ms: int = 30_000,
        profile: BrowserProfile | None = None,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.profile = profile or PROFILES["desktop"]
        # where a file the page offers ends up: <workspace>/downloads next to the profile
        self.downloads_dir = profile_dir.parent / "downloads"
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None

    @staticmethod
    def available() -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def open(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def ensure(self) -> None:
        if self.open:
            return
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._context is None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = await self._pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                viewport=self.profile.viewport,
                user_agent=self.profile.user_agent or None,
                is_mobile=self.profile.mobile,
                has_touch=self.profile.mobile,
                device_scale_factor=self.profile.scale,
                locale=None,
            )
            self._context.set_default_timeout(self.timeout_ms)
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page.on("download", self._on_download)

    def _on_download(self, download: Any) -> None:
        async def save() -> None:
            try:
                self.downloads_dir.mkdir(parents=True, exist_ok=True)
                name = Path(download.suggested_filename or "download").name or "download"
                await download.save_as(str(self.downloads_dir / name))
                logger.info("browser: downloaded {} into the workspace", name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser: download failed: {}", exc)

        asyncio.ensure_future(save())

    async def goto(self, url: str) -> None:
        await self._page.goto(url, wait_until="domcontentloaded")

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        return await self._page.evaluate(js, arg)

    async def click_at(self, x: float, y: float) -> None:
        await self._page.mouse.click(x, y)

    async def type_text(self, text: str) -> None:
        await self._page.keyboard.type(text, delay=20)

    async def press(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def scroll(self, dy: float) -> None:
        await self._page.mouse.wheel(0, dy)
        await self._page.wait_for_timeout(300)

    async def back(self) -> None:
        await self._page.go_back(wait_until="domcontentloaded")

    async def screenshot(self, quality: int = 55) -> bytes:
        return await self._page.screenshot(type="jpeg", quality=quality, scale="css")

    async def url(self) -> str:
        return str(self._page.url)

    async def title(self) -> str:
        return str(await self._page.title())

    async def settle(self, timeout_ms: int) -> None:
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:  # noqa: BLE001
            pass
        await self._page.wait_for_timeout(400)

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure()
        # the context's request API shares its cookie jar: a signed-in request
        resp = await self._context.request.fetch(
            url, method=method.upper(), headers=headers or None, data=body
        )
        text = await resp.text()
        return {"status": resp.status, "headers": dict(resp.headers), "body": text, "url": resp.url}

    async def set_profile(self, profile: BrowserProfile) -> None:
        """A new user agent needs a new context; the profile directory (the logins) stays."""
        if profile == self.profile:
            return
        self.profile = profile
        if self._context is not None:
            url = await self.url() if self.open else ""
            await self._context.close()
            self._context = self._page = None
            await self.ensure()
            if url and url != "about:blank":
                await self.goto(url)

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser cleanup: {}", exc)
        finally:
            self._context = self._page = self._pw = None


# ---------------------------------------------------------------------- the phone's WebView
class DeviceBackend(BrowserBackend):
    """The app's offscreen WebView on the phone, over the phone link.

    Requests (``op`` and its params) and what comes back — the protocol the Android app
    implements in ``DeviceBrowser.kt``::

        open      {}                              → {url, title}
        navigate  {url}                           → {url, title}
        evaluate  {js, arg}                       → {value}          runs (js)(arg), JSON result
        tap       {x, y}                          → {}               CSS px of the viewport
        type      {text}                          → {}               into the focused element
        key       {key}                           → {}               "Enter", "Tab", "Backspace" …
        scroll    {dy}                            → {}
        back      {}                              → {url, title}
        screenshot {quality}                      → {jpeg: base64, width, height}
        state     {}                              → {url, title, width, height}
        fetch     {url, method, headers, body}    → {status, headers, body, url}   with the WebView's cookies
        profile   {user_agent, width, height, mobile} → {}
        close     {}                              → {}
    """

    kind = "device"

    def __init__(
        self, link: PhoneLink, timeout_s: float = 30.0, profile: BrowserProfile | None = None
    ):
        self.link = link
        self.timeout_s = timeout_s
        # the phone's own WebView is mobile by nature; "" leaves its user agent alone
        self.profile = profile or replace(PROFILES["mobile"], user_agent="")
        self._open = False
        self._size: tuple[int, int] | None = None
        self._device: Any = None  # the phone the page was opened on

    @property
    def open(self) -> bool:
        # a phone that reconnected (app restarted) comes back with no page: open again
        device = self.link.browser_device
        return self._open and device is not None and device is self._device

    async def _req(self, op: str, **params: Any) -> dict[str, Any]:
        return await self.link.browser(op, params, timeout=self.timeout_s)

    async def ensure(self) -> None:
        if self.open:
            return
        result = await self._req(
            "open",
            user_agent=self.profile.user_agent,
            width=self.profile.width,
            height=self.profile.height,
            mobile=self.profile.mobile,
        )
        self._open = True
        self._device = self.link.browser_device
        if result.get("width") and result.get("height"):
            self._size = (int(result["width"]), int(result["height"]))

    async def goto(self, url: str) -> None:
        await self._req("navigate", url=url)

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        result = await self._req("evaluate", js=js, arg=arg)
        value = result.get("value")
        if isinstance(value, str) and result.get("encoded") == "json":
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value

    async def click_at(self, x: float, y: float) -> None:
        await self._req("tap", x=x, y=y)

    async def type_text(self, text: str) -> None:
        await self._req("type", text=text)

    async def press(self, key: str) -> None:
        await self._req("key", key=key)

    async def scroll(self, dy: float) -> None:
        await self._req("scroll", dy=dy)

    async def back(self) -> None:
        await self._req("back")

    async def screenshot(self, quality: int = 55) -> bytes:
        result = await self._req("screenshot", quality=quality)
        data = result.get("jpeg") or ""
        return base64.b64decode(data) if data else b""

    async def url(self) -> str:
        return str((await self._req("state")).get("url") or "")

    async def title(self) -> str:
        return str((await self._req("state")).get("title") or "")

    async def settle(self, timeout_ms: int) -> None:
        # the phone waits for its own page-finished callback inside navigate/tap; a short
        # pause covers scripts that navigate after the fact
        await self._req("settle", timeout_ms=min(timeout_ms, 8_000))

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure()
        result = await self._req(
            "fetch", url=url, method=method.upper(), headers=headers or {}, body=body
        )
        return {
            "status": int(result.get("status") or 0),
            "headers": dict(result.get("headers") or {}),
            "body": str(result.get("body") or ""),
            "url": str(result.get("url") or url),
        }

    async def set_profile(self, profile: BrowserProfile) -> None:
        self.profile = profile
        if self.open:
            await self._req(
                "profile",
                user_agent=profile.user_agent,
                width=profile.width,
                height=profile.height,
                mobile=profile.mobile,
            )

    async def close(self) -> None:
        if self._open:
            try:
                await self._req("close")
            except Exception as exc:  # noqa: BLE001
                logger.debug("device browser close: {}", exc)
        self._open = False


__all__ = [
    "DESKTOP_UA",
    "MOBILE_UA",
    "PROFILES",
    "BrowserBackend",
    "BrowserProfile",
    "DeviceBackend",
    "PlaywrightBackend",
    "profile_named",
]
