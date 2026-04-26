"""The browser tool over its backends: the same summary, frames and Sentinel view whether the
page renders in Playwright or in the phone's WebView; the device protocol; the profiles."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import pytest

from nanomuse.phone import PhoneLink
from nanomuse.phone.link import DeviceError
from nanomuse.schema import RiskLevel
from nanomuse.tools.browser import _ANNOTATE_JS, Browser, BrowserFrame
from nanomuse.tools.browser_backends import (
    PROFILES,
    BrowserBackend,
    BrowserProfile,
    DeviceBackend,
    profile_named,
)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"

ELEMENTS = [
    {"i": 0, "tag": "a", "type": "", "text": "Sign in", "href": "/login"},
    {"i": 1, "tag": "input", "type": "search", "text": "Search", "href": ""},
    {"i": 2, "tag": "button", "type": "submit", "text": "Go", "href": ""},
]


# ----------------------------------------------------------------------------- a page in memory
class FakeBackend(BrowserBackend):
    """A backend that keeps a tiny page in memory and records what was asked of it."""

    kind = "fake"

    def __init__(self) -> None:
        self.profile = PROFILES["desktop"]
        self._open = False
        self.page_url = "about:blank"
        self.page_title = ""
        self.calls: list[tuple[str, Any]] = []
        self.history: list[str] = []
        self.fields: dict[int, str] = {}

    @property
    def open(self) -> bool:
        return self._open

    async def ensure(self) -> None:
        self._open = True

    async def goto(self, url: str) -> None:
        self.calls.append(("goto", url))
        self.history.append(self.page_url)
        self.page_url, self.page_title = url, "Example Domain"

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        self.calls.append(("evaluate", arg))
        if js is _ANNOTATE_JS or "data-om-idx" in js and "maxElements" in js:
            return ELEMENTS[: int(arg)]
        if "getBoundingClientRect" in js and "scrollIntoView" in js and "index" not in js:
            # the centre of an element
            return (
                {"x": 100.0 + 10 * int(arg), "y": 200.0, "w": 80, "h": 20} if int(arg) < 3 else None
            )
        if "setter.call" in js:
            self.fields[int(arg["index"])] = arg["text"]
            return arg["index"] != 2  # the button is not a field
        if "innerText" in js and "body" in js:
            return "Example Domain  This domain is for use in illustrative examples."
        if "innerText" in js:
            return ELEMENTS[int(arg)]["text"] if int(arg) < 3 else ""
        return None

    async def click_at(self, x: float, y: float) -> None:
        self.calls.append(("click_at", (x, y)))

    async def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    async def press(self, key: str) -> None:
        self.calls.append(("press", key))

    async def scroll(self, dy: float) -> None:
        self.calls.append(("scroll", dy))

    async def back(self) -> None:
        self.calls.append(("back", None))
        if self.history:
            self.page_url = self.history.pop()

    async def screenshot(self, quality: int = 55) -> bytes:
        self.calls.append(("screenshot", quality))
        return JPEG

    async def url(self) -> str:
        return self.page_url

    async def title(self) -> str:
        return self.page_title

    async def settle(self, timeout_ms: int) -> None:
        self.calls.append(("settle", timeout_ms))

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("fetch", (url, method, body)))
        return {
            "status": 200,
            "headers": {"content-type": "application/json; charset=utf-8"},
            "body": json.dumps({"orders": [1, 2, 3]}),
            "url": url,
        }

    async def set_profile(self, profile: BrowserProfile) -> None:
        self.calls.append(("set_profile", profile))
        self.profile = profile

    async def close(self) -> None:
        self._open = False


def tool_with(backend: BrowserBackend, tmp_path: Path) -> tuple[Browser, list[BrowserFrame]]:
    frames: list[BrowserFrame] = []
    tool = Browser(workspace=tmp_path, backend_mode="auto")
    # the backend under test, already open so the tool keeps it; picking one is tested separately
    tool._backend = backend
    backend._open = True  # type: ignore[attr-defined]
    tool.on_frame = frames.append
    return tool, frames


# ----------------------------------------------------------------------------- the tool
async def test_actions_produce_the_same_summary_and_frames_on_any_backend(tmp_path: Path):
    backend = FakeBackend()
    tool, frames = tool_with(backend, tmp_path)

    res = await tool.execute(action="navigate", url="example.com")
    assert res.ok
    assert ("goto", "https://example.com") in backend.calls
    assert "URL: https://example.com" in res.output and "Title: Example Domain" in res.output
    assert "[0] <a> Sign in → /login" in res.output
    assert "[1] <input type=search> Search" in res.output
    assert frames and frames[-1].action == "Opened example.com" and frames[-1].jpeg == JPEG
    assert frames[-1].backend == "fake" and frames[-1].width == 1280

    # click by number: scrolled into view, then a click at the centre, then a settle
    res = await tool.execute(action="click", index=0)
    assert res.ok
    assert ("click_at", (100.0, 200.0)) in backend.calls
    assert frames[-1].action == "Clicked 'Sign in'"

    # type: the framework-friendly fill, then Enter when asked
    res = await tool.execute(action="type", index=1, text="red panda", submit=True)
    assert res.ok and backend.fields[1] == "red panda"
    assert ("press", "Enter") in backend.calls
    assert frames[-1].action == "Typed into 'Search' and submitted"

    # a "field" that is not one falls back to click + type
    before = len(backend.calls)
    await tool.execute(action="type", index=2, text="x")
    tail = backend.calls[before:]
    assert ("click_at", (120.0, 200.0)) in tail and ("type_text", "x") in tail

    # scroll is a viewport's worth, back returns
    before = len(backend.calls)
    await tool.execute(action="scroll", direction="up")
    scrolls = [c for c in backend.calls[before:] if c[0] == "scroll"]
    assert scrolls and scrolls[0][1] == -900 * 0.85
    res = await tool.execute(action="back")
    assert res.ok and ("back", None) in backend.calls

    # a screenshot lands in the workspace
    res = await tool.execute(action="screenshot")
    assert res.ok and res.system and Path(res.system).exists()
    assert Path(res.system).read_bytes() == JPEG

    # an element that vanished is an error, not a crash
    res = await tool.execute(action="click", index=7)
    assert not res.ok and "no longer on the page" in (res.error or "")


async def test_fetch_and_profile_actions(tmp_path: Path):
    backend = FakeBackend()
    tool, _ = tool_with(backend, tmp_path)
    res = await tool.execute(action="fetch", url="https://shop.example/api/orders")
    assert res.ok
    assert res.output.startswith("HTTP 200 https://shop.example/api/orders (application/json)")
    assert '"orders"' in res.output
    assert ("fetch", ("https://shop.example/api/orders", "GET", None)) in backend.calls

    res = await tool.execute(action="fetch", url="shop.example/api/pay", method="post", body="a=1")
    assert res.ok and ("fetch", ("https://shop.example/api/pay", "POST", "a=1")) in backend.calls

    res = await tool.execute(action="profile", profile="mobile")
    assert res.ok and backend.profile.name == "mobile" and backend.profile.mobile
    assert "412×915" in res.output

    res = await tool.execute(action="profile", user_agent="Bot/1.0", width=800)
    assert res.ok and backend.profile.name == "custom"
    assert backend.profile.user_agent == "Bot/1.0" and backend.profile.width == 800
    # height kept from the mobile preset
    assert backend.profile.height == 915


def test_sentinel_view_of_actions(tmp_path: Path):
    tool = Browser(workspace=tmp_path)
    nav = tool.assess({"action": "navigate", "url": "https://mail.example.com/inbox"})
    assert nav.risk is RiskLevel.MODERATE and nav.egress and nav.egress_target == "mail.example.com"
    fetch = tool.assess({"action": "fetch", "url": "https://api.example.com/x"})
    assert fetch.egress and fetch.egress_target == "api.example.com"
    for quiet in ("extract", "screenshot", "scroll", "profile", "close"):
        assert not tool.assess({"action": quiet}).egress
    assert (
        tool.assess({"action": "type", "index": 1, "text": "hello"}).summary == "browser.type hello"
    )


async def test_user_actions_are_reported_to_the_model_once(tmp_path: Path):
    backend = FakeBackend()
    tool, frames = tool_with(backend, tmp_path)
    await tool.execute(action="navigate", url="https://example.com")
    await tool.user_action("click", "main", x=0.5, y=0.25)
    assert ("click_at", (640.0, 225.0)) in backend.calls
    assert frames[-1].by_user and frames[-1].thread == "main"
    await tool.user_action("type", "main", text="secret")
    await tool.user_action("handed_back", "main")
    res = await tool.execute(action="extract")
    assert "the user took over the browser" in res.output
    assert "clicked at (640, 225); typed 6 characters; used the page in the app" in res.output
    # said once
    res = await tool.execute(action="extract")
    assert "took over" not in res.output


def test_backend_choice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import nanomuse.tools.browser as mod

    link = PhoneLink()

    async def nop(msg: dict[str, Any]) -> None:
        return None

    # nothing anywhere
    monkeypatch.setattr(mod, "playwright_available", lambda: False)
    tool = Browser(workspace=tmp_path, link=link)
    assert tool.backend_kind == ""
    with pytest.raises(RuntimeError, match="no browser is available"):
        tool._pick_backend()

    # a phone with a browser: auto takes it when playwright is absent
    link.attach("p", {"name": "Pixel", "browser": True}, nop)
    assert tool.backend_kind == "device"
    backend = tool._pick_backend()
    assert isinstance(backend, DeviceBackend) and backend.profile.mobile
    assert backend.profile.user_agent == ""  # the WebView's own

    # playwright present: auto prefers it, "device" still forces the phone
    monkeypatch.setattr(mod, "playwright_available", lambda: True)
    tool2 = Browser(workspace=tmp_path, link=link)
    assert tool2.backend_kind == "playwright"
    tool3 = Browser(workspace=tmp_path, link=link, backend_mode="device")
    assert tool3.backend_kind == "device"
    assert tool2.profile_dir == tmp_path / "browser-profile"

    # the device gone: "device" mode has nowhere to render
    link.detach("p")
    assert tool3.backend_kind == ""
    with pytest.raises(RuntimeError, match="no phone"):
        tool3._pick_backend()


# ----------------------------------------------------------------------------- the device protocol
class FakeAppBrowser:
    """The Android app's side of the protocol: answers ``browser`` requests."""

    def __init__(self, link: PhoneLink):
        self.link = link
        self.requests: list[dict[str, Any]] = []
        self.url = "about:blank"
        self.device = link.attach("app", {"name": "Pixel 8", "browser": True}, self.receive)

    async def receive(self, msg: dict[str, Any]) -> None:
        assert msg["kind"] == "device_request" and msg["op"] == "browser"
        params = msg["params"]
        self.requests.append(params)
        op = params["op"]
        result: dict[str, Any] = {}
        if op == "open":
            result = {
                "url": self.url,
                "title": "",
                "width": params["width"],
                "height": params["height"],
            }
        elif op == "navigate":
            self.url = params["url"]
            result = {"url": self.url, "title": "Example Domain"}
        elif op == "evaluate":
            result = {"value": json.dumps(ELEMENTS[: int(params["arg"])]), "encoded": "json"}
        elif op == "screenshot":
            result = {"jpeg": base64.b64encode(JPEG).decode(), "width": 412, "height": 915}
        elif op == "state":
            result = {"url": self.url, "title": "Example Domain", "width": 412, "height": 915}
        elif op == "fetch":
            result = {
                "status": 200,
                "headers": {"content-type": "text/html"},
                "body": "<b>hi</b>",
                "url": params["url"],
            }
        elif op == "tap" and params["x"] > 1000:
            asyncio.get_running_loop().call_soon(
                self.link.resolve,
                {"kind": "device_result", "id": msg["id"], "ok": False, "error": "off screen"},
            )
            return
        asyncio.get_running_loop().call_soon(
            self.link.resolve,
            {"kind": "device_result", "id": msg["id"], "ok": True, "result": result},
        )


async def test_device_backend_speaks_the_protocol():
    link = PhoneLink(timeout_s=1)
    app = FakeAppBrowser(link)
    backend = DeviceBackend(link, timeout_s=1)
    assert not backend.open
    await backend.ensure()
    assert backend.open and app.requests[0]["op"] == "open"
    assert app.requests[0]["mobile"] is True and app.requests[0]["width"] == 412

    await backend.goto("https://example.com")
    assert app.url == "https://example.com"
    elements = await backend.evaluate(_ANNOTATE_JS, 2)
    assert elements == ELEMENTS[:2]  # decoded from the app's JSON string
    assert await backend.screenshot() == JPEG
    assert (
        await backend.url() == "https://example.com" and await backend.title() == "Example Domain"
    )
    await backend.click_at(10, 20)
    await backend.type_text("hi")
    await backend.press("Enter")
    await backend.scroll(300)
    await backend.settle(30_000)
    ops = [r["op"] for r in app.requests]
    assert ops[-5:] == ["tap", "type", "key", "scroll", "settle"]
    assert app.requests[-1]["timeout_ms"] == 8_000  # capped
    fetched = await backend.fetch("https://example.com/me")
    assert fetched["status"] == 200 and fetched["body"] == "<b>hi</b>"

    # a rejected request surfaces as an error, and the tool reports it
    with pytest.raises(DeviceError, match="off screen"):
        await backend.click_at(5000, 0)

    await backend.set_profile(profile_named("desktop"))
    assert app.requests[-1]["op"] == "profile" and app.requests[-1]["mobile"] is False
    await backend.close()
    assert not backend.open and app.requests[-1]["op"] == "close"

    # the phone leaving closes the session
    await backend.ensure()
    link.detach("app")
    assert not backend.open
    with pytest.raises(DeviceError, match="no phone with a browser"):
        await backend.url()


def test_browser_device_is_separate_from_the_gui_device():
    link = PhoneLink()

    async def nop(msg: dict[str, Any]) -> None:
        return None

    link.attach("web", {"name": "web tab"}, nop)
    assert link.browser_device is None and link.device is None
    link.attach("app", {"name": "Pixel", "browser": True, "gui": False}, nop)
    assert link.browser_device.name == "Pixel" and link.device is None
    assert link.status()["device"] is None
    link.attach("sim", {"name": "MobileGym", "gui": True}, nop)
    assert link.device.name == "MobileGym" and link.browser_device.name == "Pixel"
    assert link.devices["app"].to_dict()["browser"] is True


# ----------------------------------------------------------------------------- profiles
def test_profiles():
    assert PROFILES["desktop"].viewport == {"width": 1280, "height": 900}
    mobile = profile_named("mobile")
    assert mobile.mobile and mobile.scale == 2.0 and "Mobile" in mobile.user_agent
    custom = profile_named("", width=100, height=99999, base=mobile)
    assert custom.name == "custom" and custom.width == 320 and custom.height == 4320
    assert custom.user_agent == mobile.user_agent  # kept from the base
    assert profile_named("nonsense").name == "desktop"
