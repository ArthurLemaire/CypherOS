"""Browser tool (Playwright). Optional: ``pip install "openmuse[browser]" && playwright install chromium``.

The page is summarised for the model as readable text plus a numbered list of
interactive elements; actions refer to those numbers.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from openmuse.logger import logger
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment
from openmuse.tools.web import host_of

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
        "tool returns the new page state. Never enter passwords or payment details yourself — ask the user."
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

    _pw: Any = None
    _browser: Any = None
    _page: Any = None

    # ------------------------------------------------------------------ lifecycle
    async def _ensure_page(self) -> Any:
        if self._page is not None and not self._page.is_closed():
            return self._page
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._browser is None:
            self._browser = await self._pw.chromium.launch(headless=self.headless)
        context = await self._browser.new_context(viewport={"width": 1280, "height": 900})
        self._page = await context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self._page

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
        try:
            page = await self._ensure_page()
            if action == "navigate":
                if not url:
                    return ToolResult.fail("`url` is required")
                if not url.lower().startswith(("http://", "https://")):
                    url = "https://" + url
                await page.goto(url, wait_until="domcontentloaded")
                return await self._state(page, brief=True)
            if action == "extract":
                return await self._state(page, brief=False)
            if action == "click":
                if index is None:
                    return ToolResult.fail("`index` is required")
                await page.click(f'[data-om-idx="{int(index)}"]')
                await self._settle(page)
                return await self._state(page, brief=True)
            if action == "type":
                if index is None or text is None:
                    return ToolResult.fail("`index` and `text` are required")
                selector = f'[data-om-idx="{int(index)}"]'
                await page.fill(selector, text)
                if submit:
                    await page.press(selector, "Enter")
                    await self._settle(page)
                return await self._state(page, brief=True)
            if action == "press":
                await page.keyboard.press(key or "Enter")
                await self._settle(page)
                return await self._state(page, brief=True)
            if action == "scroll":
                await page.mouse.wheel(0, -800 if direction == "up" else 800)
                await page.wait_for_timeout(300)
                return await self._state(page, brief=True)
            if action == "back":
                await page.go_back(wait_until="domcontentloaded")
                return await self._state(page, brief=True)
            if action == "screenshot":
                shots = self.workspace / "screenshots"
                shots.mkdir(parents=True, exist_ok=True)
                path = shots / f"{time.strftime('%Y%m%d-%H%M%S')}.png"
                await page.screenshot(path=str(path), full_page=False)
                return ToolResult(output=f"Screenshot saved to {path}", system=str(path))
            return ToolResult.fail(f"unknown action '{action}'")
        except Exception as exc:  # noqa: BLE001 – playwright raises many error types
            return ToolResult.fail(
                f"browser error: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
            )

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
        lines = [
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


__all__ = ["Browser", "playwright_available"]
