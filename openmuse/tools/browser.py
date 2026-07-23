"""Browser tool (Playwright). Optional: ``pip install "openmuse[browser]" && playwright install chromium``.

The page is summarised for the model as readable text plus a numbered list of
interactive elements; actions refer to those numbers.

What the browser shows is also shown to the user: after every action a JPEG frame of
the viewport goes to ``on_frame`` (the app turns that into a live browser card), and
the user can take over — click, type, open a URL — through :meth:`Browser.user_action`.
That is how a login happens: the agent stops at the form, the user signs in, the agent
carries on with the page as the user left it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr

from openmuse.logger import logger
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment
from openmuse.tools.web import host_of

VIEWPORT = {"width": 1280, "height": 900}


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


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


class Browser(BaseTool):
    name: str = "browser"
    description: str = (
        "Control a real web browser to complete tasks on websites (search, read, fill forms, click). "
        "Actions: `navigate` (url), `extract` (read current page + numbered interactive elements), "
        "`click` (index), `type` (index, text, submit=true to press Enter), `press` (key, e.g. 'Enter'), "
        "`scroll` (direction up|down), `back`, `screenshot`, `close`. After navigate/click/type the "
        "tool returns the new page state. The user watches the browser live in the app and can take "
        "over it: never enter passwords, one-time codes or payment details yourself — when a page "
        "needs a sign-in or a human decision, stop and `ask_user` to do it in the browser view, then "
        "continue. Leave the browser open when you finish (no `close` unless asked) so the user can "
        "look at or take over the page."
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
                    "close",
                ],
            },
            "url": {"type": "string"},
            "index": {"type": "integer", "description": "Element number from the last page state."},
            "text": {"type": "string"},
            "submit": {"type": "boolean"},
            "key": {"type": "string"},
            "direction": {"type": "string", "enum": ["up", "down"]},
        },
        "required": ["action"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True

    headless: bool = True
    timeout_ms: int = 30_000
    workspace: Path = Path("./workspace")
    # receives a BrowserFrame after every action; set by the app
    on_frame: Callable[[BrowserFrame], None] | None = None
    frame_quality: int = 55

    _pw: Any = None
    _browser: Any = None
    _page: Any = None
    _lock: Any = None
    # what the user did since the model last looked at the page
    _user_actions: list[str] = PrivateAttr(default_factory=list)

    # ------------------------------------------------------------------ lifecycle
    async def _ensure_page(self) -> Any:
        if self._page is not None and not self._page.is_closed():
            return self._page
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._browser is None:
            self._browser = await self._pw.chromium.launch(headless=self.headless)
        context = await self._browser.new_context(viewport=VIEWPORT)
        self._page = await context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self._page

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def open(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    async def _frame(
        self, page: Any, action: str, by_user: bool = False, thread: str | None = None
    ) -> None:
        if self.on_frame is None:
            return
        try:
            jpeg = await page.screenshot(type="jpeg", quality=self.frame_quality, scale="css")
            title = await page.title()
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser frame: {}", exc)
            return
        try:
            self.on_frame(BrowserFrame(page.url, title, action, jpeg, by_user, thread))
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser frame listener failed: {}", exc)

    async def _label(self, page: Any, index: int) -> str:
        try:
            text = await page.eval_on_selector(
                f'[data-om-idx="{index}"]',
                "e => (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || '').trim()",
            )
        except Exception:  # noqa: BLE001
            return f"[{index}]"
        text = " ".join(str(text).split())
        return f"'{text[:40]}'" if text else f"[{index}]"

    async def cleanup(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("browser cleanup: {}", exc)
        finally:
            self._browser = self._page = self._pw = None

    # ------------------------------------------------------------------ sentinel
    def assess(self, args: dict[str, Any]) -> CallAssessment:
        action = args.get("action", "")
        target = host_of(str(args.get("url", ""))) if action == "navigate" else self._current_host()
        detail = args.get("url") or args.get("text") or args.get("index") or args.get("key") or ""
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            egress=action not in ("extract", "screenshot", "close", "scroll"),
            egress_target=target,
            summary=f"browser.{action} {str(detail)[:120]}".strip(),
        )

    def _current_host(self) -> str | None:
        try:
            return host_of(self._page.url) if self._page is not None else None
        except Exception:  # noqa: BLE001
            return None

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
        **_: Any,
    ) -> ToolResult:
        if not playwright_available():
            return ToolResult.fail(
                "playwright is not installed. Run: pip install 'openmuse[browser]' && playwright install chromium"
            )
        if action == "close":
            await self.cleanup()
            return ToolResult(output="Browser closed.")
        async with self.lock:
            try:
                return await self._act(action, url, index, text, submit, key, direction)
            except Exception as exc:  # noqa: BLE001 – playwright raises many error types
                return ToolResult.fail(
                    f"browser error: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
                )

    async def _act(
        self,
        action: str,
        url: str | None,
        index: int | None,
        text: str | None,
        submit: bool,
        key: str | None,
        direction: str,
    ) -> ToolResult:
        page = await self._ensure_page()
        if action == "navigate":
            if not url:
                return ToolResult.fail("`url` is required")
            if not url.lower().startswith(("http://", "https://")):
                url = "https://" + url
            await page.goto(url, wait_until="domcontentloaded")
            await self._frame(page, f"Opened {host_of(url) or url}")
            return await self._state(page, brief=True)
        if action == "extract":
            await self._frame(page, "Read the page")
            return await self._state(page, brief=False)
        if action == "click":
            if index is None:
                return ToolResult.fail("`index` is required")
            label = await self._label(page, int(index))
            await page.click(f'[data-om-idx="{int(index)}"]')
            await self._settle(page)
            await self._frame(page, f"Clicked {label}")
            return await self._state(page, brief=True)
        if action == "type":
            if index is None or text is None:
                return ToolResult.fail("`index` and `text` are required")
            selector = f'[data-om-idx="{int(index)}"]'
            label = await self._label(page, int(index))
            await page.fill(selector, text)
            if submit:
                await page.press(selector, "Enter")
                await self._settle(page)
            await self._frame(page, f"Typed into {label}" + (" and submitted" if submit else ""))
            return await self._state(page, brief=True)
        if action == "press":
            await page.keyboard.press(key or "Enter")
            await self._settle(page)
            await self._frame(page, f"Pressed {key or 'Enter'}")
            return await self._state(page, brief=True)
        if action == "scroll":
            await page.mouse.wheel(0, -800 if direction == "up" else 800)
            await page.wait_for_timeout(300)
            await self._frame(page, f"Scrolled {direction}")
            return await self._state(page, brief=True)
        if action == "back":
            await page.go_back(wait_until="domcontentloaded")
            await self._frame(page, "Went back")
            return await self._state(page, brief=True)
        if action == "screenshot":
            shots = self.workspace / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            path = shots / f"{time.strftime('%Y%m%d-%H%M%S')}.png"
            await page.screenshot(path=str(path), full_page=False)
            await self._frame(page, "Took a screenshot")
            return ToolResult(output=f"Screenshot saved to {path}", system=str(path))
        return ToolResult.fail(f"unknown action '{action}'")

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
            page = await self._ensure_page()
            if action == "click":
                if x is None or y is None:
                    raise ValueError("click needs x and y")
                px = min(max(float(x), 0.0), 1.0) * VIEWPORT["width"]
                py = min(max(float(y), 0.0), 1.0) * VIEWPORT["height"]
                await page.mouse.click(px, py)
                await self._settle(page)
                caption, note = "You tapped the page", f"clicked at ({int(px)}, {int(py)})"
            elif action == "type":
                if text is None:
                    raise ValueError("type needs text")
                await page.keyboard.type(text, delay=20)
                caption, note = "You typed", f"typed {len(text)} characters"
            elif action == "key":
                await page.keyboard.press(key or "Enter")
                await self._settle(page)
                caption, note = f"You pressed {key or 'Enter'}", f"pressed {key or 'Enter'}"
            elif action == "scroll":
                await page.mouse.wheel(0, float(dy if dy is not None else 600))
                await page.wait_for_timeout(200)
                caption, note = "You scrolled", "scrolled"
            elif action == "navigate":
                if not url:
                    raise ValueError("navigate needs a url")
                if not url.lower().startswith(("http://", "https://")):
                    url = "https://" + url
                await page.goto(url, wait_until="domcontentloaded")
                caption, note = f"You opened {host_of(url) or url}", f"opened {url}"
            elif action == "look":
                caption, note = "Live view", ""
            else:
                raise ValueError(f"unknown action '{action}'")
            if note:
                self._user_actions.append(note)
                logger.info("browser: user {}", note)
            await self._frame(page, caption, by_user=True, thread=thread)
            return {"url": page.url, "title": await page.title()}

    async def _settle(self, page: Any) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(400)

    async def _state(self, page: Any, brief: bool) -> ToolResult:
        max_text = 3000 if brief else 9000
        max_elements = 60 if brief else 150
        elements = await page.evaluate(_ANNOTATE_JS, max_elements)
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        text = " ".join(text.split()) if text else ""
        if len(text) > max_text:
            text = text[:max_text] + f" ... [truncated, {len(text)} chars]"
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
            f"URL: {page.url}",
            f"Title: {await page.title()}",
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
