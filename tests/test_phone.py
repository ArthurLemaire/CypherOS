"""The phone: screens, the link, the tools' risk, the operator loop, traces, and the server side."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import time
import zlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nanomuse.config import GUISettings, Settings
from nanomuse.llm import MockLLM
from nanomuse.phone import PhoneLink, Screen
from nanomuse.phone.link import STOP_MARKER, DeviceError, DeviceStopped
from nanomuse.phone.operator import (
    PhoneOperator,
    Step,
    parse_step,
    parse_tagged_text,
    to_device_action,
)
from nanomuse.phone.screen import image_size
from nanomuse.phone.trace import list_traces, read_trace, render_html
from nanomuse.schema import LLMResponse, RiskLevel
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.sentinel.audit import channel_of
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from nanomuse.tools.phone import PhoneAct, PhoneScreen, PhoneTask
from nanomuse.ui import ApprovalDecision, ApprovalRequest


def png(width: int, height: int) -> str:
    """A real (tiny) PNG of the given size, base64 — one grey row, repeated."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return base64.b64encode(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    ).decode()


PAY_SCREEN = {
    "app": "alipay",
    "app_name": "支付宝",
    "route": "/transfer/confirm",
    "width": 390,
    "height": 844,
    "keyboard": False,
    "screenshot": png(39, 84),
}

HOME_SCREEN = {
    "app": "launcher",
    "app_name": "Home",
    "width": 390,
    "height": 844,
    "screenshot": png(39, 84),
}


def reply(action: str, thought: str = "look", **arguments: Any) -> LLMResponse:
    """A model turn in the mobile_use dialect."""
    call = {"name": "mobile_use", "arguments": {"action": action, **arguments}}
    return LLMResponse(
        content=f"Thought: {thought}\nAction: {arguments.pop('_label', action)}\n"
        f"<tool_call>\n{json.dumps(call, ensure_ascii=False)}\n</tool_call>"
    )


def labelled(label: str, action: str, **arguments: Any) -> LLMResponse:
    call = {"name": "mobile_use", "arguments": {"action": action, **arguments}}
    return LLMResponse(
        content=f"Thought: I see it.\nAction: {label}\n<tool_call>\n{json.dumps(call, ensure_ascii=False)}\n</tool_call>"
    )


class FakePhone:
    """A device on the other end of the link: answers `screen` and `act` from a script."""

    def __init__(self, link: PhoneLink, screens: list[dict[str, Any]]):
        self.link = link
        self.screens = list(screens)
        self.acts: list[dict[str, Any]] = []
        self.device = link.attach(
            "conn-1",
            {
                "name": "Test phone",
                "platform": "mobilegym",
                "gui": True,
                "apps": [{"id": "wechat", "name": "微信"}, {"id": "alipay", "name": "支付宝"}],
                "screen": {"width": 390, "height": 844},
            },
            self.send,
        )

    def current(self) -> dict[str, Any]:
        return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)

    async def send(self, msg: dict[str, Any]) -> None:
        assert msg["kind"] == "device_request"
        if msg["op"] == "screen":
            result = self.current()
        else:
            self.acts.append(msg["params"])
            result = {"note": "ok", "screen": self.current()}
        # answer on the next tick, like a socket would
        asyncio.get_running_loop().call_soon(
            self.link.resolve,
            {"kind": "device_result", "id": msg["id"], "ok": True, "result": result},
        )


LOGIN_SCREEN = {
    "app": "com.tencent.mm",
    "app_name": "微信",
    "width": 1080,
    "height": 2400,
    "screenshot": png(36, 80),
    "nodes": [
        {"id": "0.1", "class": "TextView", "text": "手机号登录", "cx": 540, "cy": 300},
        {
            "id": "0.2.0",
            "class": "EditText",
            "hint": "密码",
            "cx": 540,
            "cy": 900,
            "editable": True,
            "password": True,
        },
        {"id": "0.3", "class": "Button", "text": "登录", "cx": 540, "cy": 1200, "clickable": True},
        {"id": "0.4", "class": "View", "cx": 10, "cy": 10, "clickable": True},
        {
            "id": "0.5",
            "class": "CheckBox",
            "text": "记住我",
            "cx": 100,
            "cy": 1000,
            "checked": False,
        },
        "not a node",
    ],
}


class CapsulePhone(FakePhone):
    """The Android app: shows the step capsule, and may answer an action with Stop."""

    def __init__(self, link: PhoneLink, screens: list[dict[str, Any]], stop_after: int = 0):
        super().__init__(link, screens)
        self.tasks: list[dict[str, Any]] = []
        self.stop_after = stop_after  # the n-th action comes back "nanomuse:stop"
        self.device = link.attach(
            "conn-1",
            {"name": "Pixel", "platform": "android", "gui": True, "capsule": True},
            self.send,
        )

    async def send(self, msg: dict[str, Any]) -> None:
        if msg["op"] == "task":
            self.tasks.append(msg["params"])
            asyncio.get_running_loop().call_soon(
                self.link.resolve, {"kind": "device_result", "id": msg["id"], "ok": True}
            )
            return
        if msg["op"] == "act" and self.stop_after and len(self.acts) + 1 >= self.stop_after:
            self.acts.append(msg["params"])
            asyncio.get_running_loop().call_soon(
                self.link.resolve,
                {
                    "kind": "device_result",
                    "id": msg["id"],
                    "ok": False,
                    "error": f"the user pressed Stop on the phone ({STOP_MARKER})",
                },
            )
            return
        await super().send(msg)


class AutoApproveUI:
    def __init__(self, approve: bool = True):
        self.approve = approve
        self.requests: list[ApprovalRequest] = []
        self.calls: list[str] = []

    def on_text_delta(self, text: str) -> None: ...
    def on_assistant_message(self, content, reasoning) -> None: ...  # noqa: ANN001
    def on_tool_call(self, call, summary: str) -> None:  # noqa: ANN001
        self.calls.append(summary)

    def on_tool_result(self, call, result) -> None: ...  # noqa: ANN001
    def on_sentinel(self, decision: str, summary: str, reasons: list[str]) -> None: ...
    def info(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision(approved=self.approve, reason="" if self.approve else "no")

    async def ask_user(self, question: str) -> str:
        return ""


def make_sentinel(settings: Settings, ui: AutoApproveUI) -> Sentinel:
    audit = AuditLog(settings.data_dir / "audit.jsonl", session_id="t")
    return Sentinel(settings.sentinel, audit=audit, ui=ui)


def make_operator(
    settings: Settings, link: PhoneLink, llm: MockLLM, ui: AutoApproveUI, **gui_kw: Any
) -> tuple[PhoneOperator, PhoneAct]:
    gui = GUISettings(**gui_kw)
    act = PhoneAct(link=link, gui=gui)
    operator = PhoneOperator(
        link,
        gui,
        make_sentinel(settings, ui),
        act,
        ui,
        make_llm=lambda: llm,
        traces_dir=settings.data_dir / "phone-traces",
    )
    return operator, act


# ----------------------------------------------------------------------------- screens
def test_screen_is_a_picture_with_a_caption(tmp_path: Path):
    screen = Screen.from_device(PAY_SCREEN, shots_dir=tmp_path / "shots")
    assert screen.render() == "支付宝 (alipay) · /transfer/confirm · 390×844 · keyboard hidden"
    assert screen.image_path and screen.image_path.endswith(".png")
    assert Path(screen.image_path).exists()
    assert screen.image_size == (39, 84)  # the picture may be smaller than the screen
    assert screen.to_dict()["image"] == screen.image_path

    # a device that says nothing about its size: the picture's own size stands in
    bare = Screen.from_device({"app": "x", "screenshot": png(36, 80)}, shots_dir=tmp_path / "s")
    assert (bare.width, bare.height) == (36, 80)

    none = Screen.from_device({"app": "x", "note": "screen is locked"})
    assert not none.has_image and "(the device sent no screenshot)" in none.render()
    assert "note: screen is locked" in none.render()


def test_screen_carries_the_node_tree_as_a_second_input(tmp_path: Path):
    screen = Screen.from_device(LOGIN_SCREEN, shots_dir=tmp_path)
    # the string was dropped, the rest kept with clean types; the picture is still the picture
    assert len(screen.nodes) == 5 and screen.nodes[1]["password"] is True
    assert screen.nodes[4]["checked"] is False and screen.nodes[0]["cx"] == 540
    assert screen.image_size == (36, 80) and screen.width == 1080
    text = screen.render()
    assert "Elements the phone reports" in text
    lines = screen.node_lines()
    # fields first (the password rule hinges on them), then what has words, then the rest
    assert lines[0].startswith('- "密码" · EditText [editable, password] @ 540,900')
    assert '"手机号登录"' in lines[1] and "[unchecked]" in lines[2]
    assert '"登录" · Button [clickable] @ 540,1200' in lines[3]
    assert lines[4].startswith("- (no text) · View [clickable]")
    # the operator's grid: centres scaled to 999×999
    scaled = screen.node_lines(scale=(999 / 1080, 999 / 2400))
    assert "@ 500,375" in scaled[0] and "@ 500,500" in scaled[3]
    assert screen.node_lines(limit=2)[-1] == "- … and 3 more"
    assert screen.to_dict()["nodes"] == 5
    # a device may send a lot; the screen keeps the first 120
    many = dict(
        LOGIN_SCREEN, nodes=[{"id": str(i), "text": f"row {i}", "cy": i} for i in range(300)]
    )
    assert len(Screen.from_device(many, shots_dir=tmp_path).nodes) == 120


def test_image_size_reads_png_and_jpeg_headers():
    assert image_size(base64.b64decode(png(12, 7))) == (12, 7)
    jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0\x00\x11\x08"
        + struct.pack(">HH", 800, 360)
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    assert image_size(jpeg) == (360, 800)
    assert image_size(b"GIF89a") is None


# ----------------------------------------------------------------------------- the link
async def test_link_round_trip_and_timeouts():
    link = PhoneLink(timeout_s=0.2)
    assert not link.connected
    with pytest.raises(DeviceError, match="no phone is connected"):
        await link.request("screen")
    phone = FakePhone(link, [HOME_SCREEN])
    assert link.device is phone.device and link.status()["device"]["apps"] == 2
    screen = await link.screen()
    assert screen.app == "launcher" and link.last_screen is screen

    # a device that never answers
    silent = PhoneLink(timeout_s=0.05)

    async def swallow(msg: dict[str, Any]) -> None:
        return None

    silent.attach("c", {"gui": True, "name": "mute"}, swallow)
    with pytest.raises(DeviceError, match="did not answer"):
        await silent.request("screen")

    # disconnecting fails what is still pending
    waiting = PhoneLink(timeout_s=5)
    waiting.attach("c2", {"gui": True}, swallow)
    task = asyncio.create_task(waiting.request("act", {"action": "back"}))
    await asyncio.sleep(0)
    waiting.detach("c2")
    with pytest.raises(DeviceError, match="disconnected"):
        await task
    assert not waiting.connected


def test_the_most_recent_gui_device_is_the_phone():
    link = PhoneLink()

    async def nop(msg: dict[str, Any]) -> None:
        return None

    link.attach("a", {"gui": False, "name": "web tab"}, nop)
    assert link.device is None
    link.attach("b", {"gui": True, "name": "old phone"}, nop)
    link.devices["b"].connected_at = time.time() - 10
    link.attach("c", {"gui": True, "name": "new phone"}, nop)
    assert link.device.name == "new phone"
    link.detach("c")
    assert link.device.name == "old phone"


# ----------------------------------------------------------------------------- tools
async def test_phone_act_risk_follows_the_label_under_the_finger():
    link = PhoneLink()
    FakePhone(link, [PAY_SCREEN])
    await link.screen()
    act = PhoneAct(link=link, gui=GUISettings())

    pay = act.assess({"action": "tap", "x": 195, "y": 784, "label": "确认付款"})
    assert pay.risk == RiskLevel.SENSITIVE and pay.warnings and pay.egress
    assert pay.target == "alipay"
    assert pay.summary == 'phone_act: tap "确认付款" at (195,784) in 支付宝 (alipay)'

    note = act.assess({"action": "tap", "x": 100, "y": 260, "label": "备注"})
    assert note.risk == RiskLevel.MODERATE and not note.warnings

    blind = act.assess({"action": "tap", "x": 195, "y": 784})
    assert blind.risk == RiskLevel.MODERATE and "no `label`" in blind.warnings[0]

    icon = act.assess({"action": "tap", "x": 30, "y": 30, "label": "支付宝"})
    assert icon.risk == RiskLevel.MODERATE  # an app's name is never a payment step

    typing = act.assess({"action": "type", "text": "房租", "label": "备注"})
    assert typing.risk == RiskLevel.MODERATE and 'type "房租" into "备注"' in typing.summary
    blind_send = act.assess({"action": "type", "text": "hi", "submit": True})
    assert blind_send.risk == RiskLevel.SENSITIVE

    swipe = act.assess({"action": "swipe", "direction": "up"})
    assert swipe.risk == RiskLevel.MODERATE
    assert swipe.summary == "phone_act: swipe up in 支付宝 (alipay)"
    pointed = act.assess({"action": "swipe", "x": 200, "y": 600, "x2": 200, "y2": 200})
    assert "(200,600)→(200,200)" in pointed.summary

    send = act.assess({"action": "enter", "label": "发送"})
    assert send.risk == RiskLevel.SENSITIVE


async def test_phone_act_takes_coordinates_and_returns_the_next_screen(tmp_path: Path):
    link = PhoneLink(shots_dir=tmp_path / "shots")
    phone = FakePhone(link, [HOME_SCREEN, PAY_SCREEN])
    screen_tool = PhoneScreen(link=link)
    first = await screen_tool.execute()
    assert first.ok and first.output.startswith("Home (launcher) · 390×844") and first.images

    act = PhoneAct(link=link, gui=GUISettings())
    unlabelled = await act.execute(action="tap", x=145, y=50)
    assert not unlabelled.ok and "needs `label`" in unlabelled.error
    nowhere = await act.execute(action="tap", label="x")
    assert not nowhere.ok and "needs `x` and `y`" in nowhere.error
    outside = await act.execute(action="tap", x=900, y=50, label="x")
    assert not outside.ok and "outside the 390×844 screen" in outside.error

    result = await act.execute(action="tap", x=145, y=50, label="支付宝")
    assert result.ok and result.output.startswith("Done: ok. Screen now:")
    assert phone.acts[-1] == {"action": "tap", "label": "支付宝", "x": 145.0, "y": 50.0}
    assert "支付宝 (alipay)" in result.output and result.images  # the new screen, with its picture

    swiped = await act.execute(action="swipe", x=200, y=600, x2=200, y2=200)
    assert swiped.ok and phone.acts[-1] == {
        "action": "swipe",
        "x": 200.0,
        "y": 600.0,
        "x2": 200.0,
        "y2": 200.0,
    }
    by_direction = await act.execute(action="swipe", direction="up", distance=0.3)
    assert by_direction.ok and phone.acts[-1] == {
        "action": "swipe",
        "direction": "up",
        "distance": 0.3,
    }
    assert not (await act.execute(action="swipe", x=1, y=1)).ok

    opened = await act.execute(action="open_app", app="微信")
    assert opened.ok and phone.acts[-1]["app"] == "wechat"
    typed = await act.execute(action="type", text="房租", clear=True)
    assert typed.ok and phone.acts[-1] == {
        "action": "type",
        "text": "房租",
        "clear": True,
        "submit": False,
    }
    held = await act.execute(action="long_press", x=10, y=10, label="row", seconds=2)
    assert held.ok and phone.acts[-1]["seconds"] == 2.0

    bad = await act.execute(action="type")
    assert not bad.ok and "`type` needs `text`" in bad.error
    assert not (await act.execute(action="fly")).ok


# ----------------------------------------------------------------------------- parsing
def test_parse_tagged_text_and_steps():
    text = (
        "Thought: The search box is at the top.\n"
        "Action: Tap the search box\n"
        '<tool_call>\n{"name": "mobile_use", "arguments": {"action": "click", "coordinate": [500, 120]}}\n</tool_call>'
    )
    parts = parse_tagged_text(text)
    assert parts["thinking"] == "The search box is at the top."
    assert parts["conclusion"] == "Tap the search box"
    assert parts["tool_call"]["arguments"]["action"] == "click"

    step = parse_step(text)
    assert isinstance(step, Step) and step.kind == "click" and step.action == "Tap the search box"
    assert step.arguments["coordinate"] == pytest.approx([500 / 999, 120 / 999])

    # a box instead of a point, a <think> block, no Thought/Action lines, a code fence
    boxed = parse_step(
        '<think>hmm</think>```json\n{"name": "mobile_use", "arguments": {"action": "long_press", "coordinate": [100, 100, 300, 300], "time": 2}}\n```'
    )
    assert boxed.arguments["coordinate"] == pytest.approx([200 / 999, 200 / 999])
    assert boxed.action.startswith("long_press at")
    # the bare arguments object is accepted too
    bare = parse_step('Action: go back\n{"action": "system_button", "button": "Back"}')
    assert bare.kind == "system_button" and bare.action == "go back"
    assert parse_step("Thought: I am not sure what to do.") is None
    assert (
        parse_step('<tool_call>{"name": "mobile_use", "arguments": {"action": 3}}</tool_call>')
        is None
    )
    assert parse_step("<tool_call>{not json}</tool_call>") is None
    assert parse_step(None) is None


def test_to_device_action_maps_the_dialect_onto_the_phone():
    screen = Screen(app="x", width=1000, height=2000)

    def step(action: str, **arguments: Any) -> Step:
        return Step(
            thought="",
            action=f"do {action}",
            name="mobile_use",
            arguments={"action": action, **arguments},
        )

    assert to_device_action(step("click", coordinate=[0.5, 0.25]), screen) == {
        "action": "tap",
        "x": 500.0,
        "y": 500.0,
        "label": "do click",
    }
    held = to_device_action(step("long_press", coordinate=[0.1, 0.1], time=9), screen)
    assert held["action"] == "long_press" and held["seconds"] == 5.0  # capped
    swipe = to_device_action(step("swipe", coordinate=[0.5, 0.8], coordinate2=[0.5, 0.2]), screen)
    assert swipe == {
        "action": "swipe",
        "x": 500.0,
        "y": 1600.0,
        "x2": 500.0,
        "y2": 400.0,
        "label": "do swipe",
    }
    assert to_device_action(step("type", text="hello"), screen)["text"] == "hello"
    assert to_device_action(step("system_button", button="Home"), screen)["action"] == "home"
    assert to_device_action(step("system_button", button="Menu"), screen)["action"] == "recents"
    assert to_device_action(step("wait", time=30), screen) == {"action": "wait", "seconds": 10.0}
    assert to_device_action(step("open", text="12306"), screen)["app"] == "12306"
    assert to_device_action(step("answer", text="done"), screen) is None
    assert to_device_action(step("terminate", status="success"), screen) is None
    with pytest.raises(ValueError, match="needs `coordinate`"):
        to_device_action(step("click"), screen)
    with pytest.raises(ValueError, match="unknown system button"):
        to_device_action(step("system_button", button="Volume"), screen)
    with pytest.raises(ValueError, match="unknown action"):
        to_device_action(step("fly"), screen)


# ----------------------------------------------------------------------------- the operator
async def test_operator_runs_until_done_and_asks_before_paying(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    phone = FakePhone(link, [HOME_SCREEN, PAY_SCREEN, PAY_SCREEN])
    ui = AutoApproveUI(approve=True)
    llm = MockLLM(
        [
            labelled("Tap the 支付宝 icon", "click", coordinate=[372, 59]),
            labelled("Tap 确认付款", "click", coordinate=[499, 928]),
            labelled("Report the result", "answer", text="已向张三转账 ¥500.00"),
        ]
    )
    operator, _ = make_operator(settings, link, llm, ui, max_steps=6)
    outcome = await operator.run("给张三转 500 元", context="he is a friend")
    assert outcome.status == "done" and outcome.steps == 3
    assert outcome.message == "已向张三转账 ¥500.00"
    # 999-space points landed on the 390×844 screen, with the Action sentence as the label
    assert phone.acts[0] == {"action": "tap", "x": 145.2, "y": 49.8, "label": "Tap the 支付宝 icon"}
    assert phone.acts[1]["label"] == "Tap 确认付款"
    # the payment tap went through the Sentinel and was asked about
    assert len(ui.requests) == 1 and ui.requests[0].risk == RiskLevel.SENSITIVE
    assert "确认付款" in ui.requests[0].summary
    report = outcome.report()
    assert report.startswith("The phone operator finished. (3 steps)")
    assert '- tap "Tap 确认付款"' in report and f"Trace: {outcome.trace_id}" in report

    # the model saw the mobile_use tool, the query, the progress and one picture per step
    first = llm.calls[0]["messages"]
    assert '"name": "mobile_use"' in first[0].content and "999x999" in first[0].content
    assert "The user query: 给张三转 500 元" in first[1].content
    assert "(Known already: he is a friend)" in first[1].content
    assert first[1].images and len(first[1].images) == 1
    third = llm.calls[2]["messages"][1].content
    assert "Step 1: Tap the 支付宝 icon; Step 2: Tap 确认付款; " in third

    # and the trace says the same
    records = read_trace(settings.data_dir / "phone-traces" / f"{outcome.trace_id}.jsonl")
    assert [r["kind"] for r in records] == ["task", "step", "step", "step", "end"]
    assert records[1]["params"]["action"] == "tap" and records[1]["screen"]["image"]
    assert records[-1]["status"] == "done"
    listing = list_traces(settings.data_dir / "phone-traces")
    assert listing[0]["id"] == outcome.trace_id and listing[0]["steps"] == 3
    page = render_html(records)
    assert "Tap 确认付款" in page and "<circle" in page and "data:image/png;base64" in page


async def test_operator_reads_nodes_shows_the_capsule_and_obeys_stop(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    phone = CapsulePhone(link, [LOGIN_SCREEN, LOGIN_SCREEN], stop_after=2)
    assert link.device is not None and link.device.capsule
    ui = AutoApproveUI(approve=True)
    llm = MockLLM(
        [
            labelled("Tap 手机号登录", "click", coordinate=[500, 125]),
            labelled("Tap 登录", "click", coordinate=[500, 500]),
            labelled("Report", "answer", text="never reached"),
        ]
    )
    operator, act = make_operator(settings, link, llm, ui, max_steps=6)
    outcome = await operator.run("登录微信")
    # the picture came with the element list, in the operator's 999 grid
    first = llm.calls[0]["messages"][1]
    assert first.images and "Elements the phone reports on this screen" in first.content
    assert '"密码" · EditText [editable, password] @ 500,375' in first.content
    assert '"登录" · Button [clickable] @ 500,500' in first.content
    # the second action came back with Stop: the run ends there, as a question to the user
    assert outcome.status == "stopped" and outcome.steps == 2
    assert "pressed Stop" in outcome.message and STOP_MARKER not in outcome.message
    assert outcome.report().startswith("The user pressed Stop on the phone.")
    # the capsule was told about the task: begin with the goal, end when it was over
    assert [(t["event"], t["text"]) for t in phone.tasks] == [("begin", "登录微信"), ("end", "")]
    # a single phone_act after Stop says so too, without the marker leaking into the chat
    phone.stop_after = 1
    phone.acts.clear()
    result = await act.execute(action="tap", x=1, y=1, label="Back")
    assert result.error and "pressed Stop" in result.error and STOP_MARKER in result.error
    records = read_trace(settings.data_dir / "phone-traces" / f"{outcome.trace_id}.jsonl")
    assert records[-1]["status"] == "stopped"


async def test_operator_tells_the_capsule_when_it_needs_the_user(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    phone = CapsulePhone(link, [PAY_SCREEN])
    llm = MockLLM([labelled("Ask", "ask_user", text="请你自己输入支付密码")])
    operator, _ = make_operator(settings, link, llm, AutoApproveUI(), max_steps=3)
    outcome = await operator.run("付款")
    assert outcome.status == "ask"
    assert [t["event"] for t in phone.tasks] == ["begin", "notice"]
    assert phone.tasks[1]["text"] == "请你自己输入支付密码"


async def test_link_raises_device_stopped_on_the_marker():
    link = PhoneLink()
    sent: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    link.attach("c", {"name": "P", "platform": "android", "gui": True}, send)
    task = asyncio.ensure_future(link.screen())
    await asyncio.sleep(0)
    link.resolve({"id": sent[0]["id"], "ok": False, "error": "stopped (nanomuse:stop)"})
    with pytest.raises(DeviceStopped) as info:
        await task
    assert isinstance(info.value, DeviceError) and "pressed Stop" in str(info.value)
    # a plain device without a capsule is not bothered with task events
    await link.task_event("begin", "x")
    assert len(sent) == 1


def test_channel_of_names_the_rung():
    assert channel_of("phone_task") == channel_of("phone_act") == "gui"
    assert channel_of("browser") == "browser" and channel_of("web_fetch") == "web"
    assert channel_of("shell") == channel_of("python_execute") == "cli"
    assert channel_of("device__clipboard_read") == "device"
    assert channel_of("amap__maps_geo") == "api" and channel_of("send_email") == "api"
    assert channel_of("read_file") == "local"


async def test_operator_stops_when_the_user_refuses(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    FakePhone(link, [PAY_SCREEN])
    ui = AutoApproveUI(approve=False)
    llm = MockLLM(
        [
            labelled("Tap 确认付款", "click", coordinate=[499, 928]),
            labelled("Tap 确认付款 again", "click", coordinate=[499, 928]),
        ]
    )
    operator, _ = make_operator(settings, link, llm, ui, max_steps=6)
    outcome = await operator.run("pay")
    assert outcome.status == "blocked" and "Sentinel blocked" in outcome.message
    assert len(ui.requests) == 2
    # the refusal was told to the model before its second try
    assert "Result: the owner refused this step" in llm.calls[1]["messages"][1].content


async def test_operator_handles_bad_replies_step_limits_and_loops(settings: Settings):
    shots = settings.agent.workspace / "screenshots"
    link = PhoneLink(shots_dir=shots)
    FakePhone(link, [HOME_SCREEN])
    ui = AutoApproveUI()
    llm = MockLLM(
        [
            LLMResponse(content="I am not sure what to do"),
            labelled("Go back", "system_button", button="Back"),
            labelled("Go back", "system_button", button="Back"),
        ]
    )
    operator, _ = make_operator(settings, link, llm, ui, max_steps=2)
    outcome = await operator.run("look around")
    assert outcome.status == "max_steps" and outcome.steps == 2
    # the nudge after the unparseable reply reached the model, in the same step
    assert any("not in the response format" in (m.content or "") for m in llm.calls[1]["messages"])

    never = MockLLM([LLMResponse(content="nope")] * 3)
    operator, _ = make_operator(settings, link, never, ui, max_steps=2)
    outcome = await operator.run("look around")
    assert outcome.status == "failed" and "usable actions" in outcome.message

    ask = MockLLM([labelled("Ask for the password", "ask_user", text="请输入支付密码")])
    operator, _ = make_operator(settings, link, ask, ui)
    outcome = await operator.run("pay")
    assert outcome.status == "ask" and outcome.message == "请输入支付密码"
    assert "needs the user" in outcome.report()

    gave_up = MockLLM([labelled("Stop", "terminate", status="failure", text="no such chat")])
    operator, _ = make_operator(settings, link, gave_up, ui)
    outcome = await operator.run("read the chat")
    assert outcome.status == "abort" and outcome.message == "no such chat"

    # the same tap three times is pointed out, and does not go to the phone a third time
    phone = FakePhone(PhoneLink(shots_dir=shots), [HOME_SCREEN])
    same = [labelled("Tap the icon", "click", coordinate=[100, 100]) for _ in range(3)]
    looping = MockLLM([*same, labelled("Stop", "terminate", status="failure", text="stuck")])
    operator, _ = make_operator(settings, phone.link, looping, ui, max_steps=6)
    outcome = await operator.run("tap")
    assert outcome.status == "abort" and len(phone.acts) == 2
    assert "taken three times" in looping.calls[3]["messages"][1].content


async def test_operator_starts_in_the_app_and_needs_pictures(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    phone = FakePhone(link, [HOME_SCREEN, PAY_SCREEN])
    ui = AutoApproveUI()
    llm = MockLLM([labelled("Done", "terminate", status="success", text="ok")])
    operator, _ = make_operator(settings, link, llm, ui)
    outcome = await operator.run("check", app="支付宝")
    assert outcome.status == "done" and phone.acts[0] == {
        "action": "open_app",
        "app": "alipay",
        "label": "open 支付宝",
    }

    blind = MockLLM([])
    blind.vision_available = False
    operator, _ = make_operator(settings, link, blind, ui)
    outcome = await operator.run("check")
    assert outcome.status == "failed" and "does not take images" in outcome.message

    dark = PhoneLink()
    FakePhone(dark, [{"app": "x", "width": 1, "height": 1}])
    operator, _ = make_operator(settings, dark, MockLLM([]), ui)
    outcome = await operator.run("check")
    assert outcome.status == "failed" and "no screenshot" in outcome.message


async def test_phone_task_tool_reports_the_outcome(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    FakePhone(link, [HOME_SCREEN])
    ui = AutoApproveUI()
    llm = MockLLM([labelled("Report", "answer", text="nothing to do")])
    operator, _ = make_operator(settings, link, llm, ui)
    task = PhoneTask(link=link, operator=operator)
    assert task.assess({"goal": "check", "app": "wechat"}).target == "wechat"
    assert "another tool does exactly" in task.description
    result = await task.execute(goal="check the chat")
    assert result.ok and "nothing to do" in result.output
    assert not (await task.execute()).ok
    link.detach("conn-1")
    assert "no phone is connected" in (await task.execute(goal="x")).error


async def test_prompt_puts_the_screen_on_the_last_rung(settings: Settings):
    from nanomuse.agent.core import MuseAgent
    from nanomuse.tools import Terminate, ToolCollection

    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    CapsulePhone(link, [HOME_SCREEN])
    ui = AutoApproveUI()
    operator, _ = make_operator(settings, link, MockLLM([]), ui)
    tools = ToolCollection(Terminate(), PhoneTask(link=link, operator=operator))
    audit = AuditLog(settings.audit_file)
    agent = MuseAgent(settings, MockLLM([]), tools, make_sentinel(settings, ui), ui, audit)
    system = agent.build_system_prompt("hi")
    assert "The user's phone is connected: Pixel (android)." in system
    assert "Four rungs, lowest first" in system and "(4) the phone's screen" in system
    assert "Before the first step on the screen" in system and "ask_user" in system
    assert "Stop button" in system
    # the whole section goes when GUI operation is off (no phone tools)
    agent.tools = ToolCollection(Terminate())
    assert "Four rungs" not in agent.build_system_prompt("hi")


# ----------------------------------------------------------------------------- server side
def test_gui_switch_and_device_handshake(settings: Settings):
    settings.server.token = "secret-token"
    llm = MockLLM([])
    service = MuseService(settings, llm=llm)
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        # off by default: no phone tools, nothing connected
        names = {t["name"] for t in client.get("/api/settings").json()["tools"]}
        assert "phone_task" not in names
        phone = client.get("/api/phone").json()
        assert phone == {
            "connected": False,
            "device": None,
            "last_screen": None,
            "gui_enabled": False,
        }

        view = client.put(
            "/api/connections/gui",
            json={"enabled": True, "model": "qwen3.8-27b", "api_key": "sk-gui"},
        ).json()
        assert view["enabled"] and view["model"] == "qwen3.8-27b" and view["key_source"] == "vault"
        names = {t["name"] for t in client.get("/api/settings").json()["tools"]}
        assert {"phone_screen", "phone_act", "phone_task"} <= names
        saved = json.loads((settings.data_dir / "app-settings.json").read_text())
        assert (
            saved["gui"]["enabled"] is True and saved["gui"]["api_key"] == "{{vault:GUI_API_KEY}}"
        )
        assert client.get("/api/connections").json()["gui"]["phone"]["connected"] is False

        with client.websocket_connect("/ws?token=secret-token") as ws:
            assert ws.receive_json()["kind"] == "hello"
            ws.send_json(
                {
                    "kind": "device",
                    "name": "MobileGym",
                    "platform": "mobilegym",
                    "gui": True,
                    "apps": [{"id": "wechat", "name": "微信"}],
                    "screen": {"width": 360, "height": 800},
                }
            )
            msg = ws.receive_json()
            while msg["kind"] != "device_ack":
                msg = ws.receive_json()
            assert msg["phone"]["connected"] and msg["phone"]["device"]["name"] == "MobileGym"
            assert client.get("/api/phone").json()["device"]["platform"] == "mobilegym"
            # the system prompt of a new run would mention it
            prompt = service.threads["main"].agent.build_system_prompt("hi")
            assert (
                "The user's phone is connected: MobileGym" in prompt and "微信 (wechat)" in prompt
            )
        assert client.get("/api/phone").json()["connected"] is False  # gone with the socket

        client.put("/api/connections/gui", json={"enabled": False})
        names = {t["name"] for t in client.get("/api/settings").json()["tools"]}
        assert "phone_task" not in names
        assert "The phone" not in service.threads["main"].agent.build_system_prompt("hi")
        assert client.put("/api/connections/gui", json={"provider": "x"}).status_code == 400
