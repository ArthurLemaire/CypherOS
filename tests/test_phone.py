"""The phone: screens, the link, the tools' risk, the operator loop, and the server side."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nanomuse.config import GUISettings, Settings
from nanomuse.llm import MockLLM
from nanomuse.phone import PhoneLink, Screen
from nanomuse.phone.link import DeviceError
from nanomuse.phone.operator import PhoneOperator, parse_step
from nanomuse.schema import LLMResponse, RiskLevel
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.server import create_app
from nanomuse.server.service import MuseService
from nanomuse.tools.phone import PhoneAct, PhoneScreen, PhoneTask
from nanomuse.ui import ApprovalDecision, ApprovalRequest

PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
).decode()  # a header is enough to be saved as .png

PAY_SCREEN = {
    "app": "alipay",
    "app_name": "支付宝",
    "route": "/transfer/confirm",
    "width": 390,
    "height": 844,
    "elements": [
        {"id": 1, "role": "text", "text": "转账给 张三", "bounds": [20, 100, 370, 140]},
        {"id": 2, "role": "text", "text": "¥ 500.00", "bounds": [20, 160, 370, 220]},
        {
            "id": 3,
            "role": "input",
            "text": "",
            "desc": "备注",
            "bounds": [20, 240, 370, 290],
            "editable": True,
        },
        {
            "id": 4,
            "role": "button",
            "text": "确认付款",
            "bounds": [40, 760, 350, 808],
            "clickable": True,
        },
    ],
    "screenshot": PNG,
}

HOME_SCREEN = {
    "app": "launcher",
    "app_name": "Home",
    "elements": [
        {"id": 1, "role": "icon", "text": "微信", "bounds": [10, 10, 90, 90], "clickable": True},
        {
            "id": 2,
            "role": "icon",
            "text": "支付宝",
            "bounds": [100, 10, 190, 90],
            "clickable": True,
        },
    ],
}


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


# ----------------------------------------------------------------------------- screens
def test_screen_renders_elements_and_saves_the_picture(tmp_path: Path):
    screen = Screen.from_device(PAY_SCREEN, shots_dir=tmp_path / "shots")
    text = screen.render()
    assert text.startswith("支付宝 (alipay) · /transfer/confirm · 390×844 · keyboard hidden")
    assert '[4] button "确认付款" {clickable} @(195,784)' in text
    assert "[3] input (备注) {editable}" in text
    assert screen.element(4).center == (195, 784)
    assert screen.find_words(["付款", "pay", "删除"]) == ["付款"]
    assert screen.image_path and screen.image_path.endswith(".png")
    assert Path(screen.image_path).exists()
    assert screen.to_dict(brief=True)["elements"] == 4


def test_screen_without_elements_says_so():
    screen = Screen.from_device({"app": "x"})
    assert "(no elements reported" in screen.render()


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
async def test_phone_act_risk_follows_what_is_under_the_finger(tmp_path: Path):
    link = PhoneLink()
    FakePhone(link, [PAY_SCREEN])
    await link.screen()
    act = PhoneAct(link=link, gui=GUISettings())

    pay = act.assess({"action": "tap", "element": 4})
    assert pay.risk == RiskLevel.SENSITIVE and pay.warnings and pay.egress
    assert pay.target == "alipay" and "确认付款" in pay.summary

    note = act.assess({"action": "tap", "element": 3})
    assert note.risk == RiskLevel.MODERATE and not note.warnings

    blind = act.assess({"action": "tap", "x": 195, "y": 784})
    assert (
        blind.risk == RiskLevel.SENSITIVE
    )  # the screen talks about paying; we cannot see the target

    typing = act.assess({"action": "type", "element": 3, "text": "房租"})
    assert typing.risk == RiskLevel.MODERATE and 'type "房租"' in typing.summary

    swipe = act.assess({"action": "swipe", "direction": "up"})
    assert (
        swipe.risk == RiskLevel.MODERATE
        and swipe.summary == "phone_act: swipe up in 支付宝 (alipay)"
    )


async def test_phone_act_resolves_elements_and_returns_the_next_screen(tmp_path: Path):
    link = PhoneLink(shots_dir=tmp_path / "shots")
    phone = FakePhone(link, [HOME_SCREEN, PAY_SCREEN])
    screen_tool = PhoneScreen(link=link)
    first = await screen_tool.execute()
    assert first.ok and '[2] icon "支付宝"' in first.output

    act = PhoneAct(link=link, gui=GUISettings())
    missing = await act.execute(action="tap", element=9)
    assert not missing.ok and "no element [9]" in missing.error

    result = await act.execute(action="tap", element=2)
    assert result.ok and result.output.startswith("Done: ok. Screen now:")
    assert phone.acts[-1] == {"action": "tap", "element": 2, "x": 145, "y": 50, "label": "支付宝"}
    assert (
        "确认付款" in result.output and result.images
    )  # the new screen came back with its picture

    opened = await act.execute(action="open_app", app="微信")
    assert opened.ok and phone.acts[-1]["app"] == "wechat"

    bad = await act.execute(action="type")
    assert not bad.ok and "`type` needs `text`" in bad.error
    assert not (await act.execute(action="fly")).ok


# ----------------------------------------------------------------------------- the operator
def test_parse_step_is_tolerant():
    assert (
        parse_step('{"thought": "t", "action": {"action": "tap", "element": 1}}')["action"][
            "element"
        ]
        == 1
    )
    fenced = '```json\n{"thought": "x", "action": {"action": "back"}}\n```'
    assert parse_step(fenced)["action"]["action"] == "back"
    prose = 'I will tap it. {"action": "tap", "element": 3}'
    assert parse_step(prose) == {"thought": "", "action": {"action": "tap", "element": 3}}
    assert parse_step("no json here") is None
    assert parse_step(None) is None


async def test_operator_runs_until_done_and_asks_before_paying(settings: Settings):
    link = PhoneLink(shots_dir=settings.agent.workspace / "screenshots")
    phone = FakePhone(link, [HOME_SCREEN, PAY_SCREEN, PAY_SCREEN])
    ui = AutoApproveUI(approve=True)
    sentinel = make_sentinel(settings, ui)
    gui = GUISettings(max_steps=6)
    act = PhoneAct(link=link, gui=gui)
    llm = MockLLM(
        [
            LLMResponse(
                content='{"thought": "open alipay", "action": {"action": "tap", "element": 2}}'
            ),
            LLMResponse(content='{"thought": "pay", "action": {"action": "tap", "element": 4}}'),
            LLMResponse(
                content='{"thought": "paid", "action": {"action": "done", "message": "已向张三转账 ¥500.00"}}'
            ),
        ]
    )
    operator = PhoneOperator(link, gui, sentinel, act, ui, make_llm=lambda: llm)
    outcome = await operator.run("给张三转 500 元", context="he is a friend")
    assert outcome.status == "done" and outcome.steps == 3
    assert outcome.message == "已向张三转账 ¥500.00"
    assert [a["action"] for a in phone.acts] == ["tap", "tap"]
    # the payment tap went through the Sentinel and was asked about
    assert len(ui.requests) == 1 and ui.requests[0].risk == RiskLevel.SENSITIVE
    assert "确认付款" in ui.requests[0].summary
    report = outcome.report()
    assert report.startswith("The phone operator finished. (3 steps)")
    assert "- tap [4]" in report
    # the operator's prompt carried the goal, the context and the apps
    system = llm.calls[0]["messages"][0].content
    assert "给张三转 500 元" in system and "he is a friend" in system and "微信 (wechat)" in system


async def test_operator_stops_when_the_user_refuses(settings: Settings):
    link = PhoneLink()
    FakePhone(link, [PAY_SCREEN])
    ui = AutoApproveUI(approve=False)
    sentinel = make_sentinel(settings, ui)
    gui = GUISettings(max_steps=6)
    act = PhoneAct(link=link, gui=gui)
    llm = MockLLM(
        [
            LLMResponse(content='{"thought": "pay", "action": {"action": "tap", "element": 4}}'),
            LLMResponse(
                content='{"thought": "try again", "action": {"action": "tap", "element": 4}}'
            ),
        ]
    )
    operator = PhoneOperator(link, gui, sentinel, act, ui, make_llm=lambda: llm)
    outcome = await operator.run("pay")
    assert outcome.status == "blocked" and "Sentinel blocked" in outcome.message
    assert len(ui.requests) == 2


async def test_operator_handles_bad_replies_and_step_limits(settings: Settings):
    link = PhoneLink()
    FakePhone(link, [HOME_SCREEN])
    ui = AutoApproveUI()
    sentinel = make_sentinel(settings, ui)
    gui = GUISettings(max_steps=2)
    act = PhoneAct(link=link, gui=gui)
    llm = MockLLM(
        [
            LLMResponse(content="I am not sure what to do"),
            LLMResponse(content='{"thought": "back", "action": {"action": "back"}}'),
            LLMResponse(content='{"thought": "back", "action": {"action": "back"}}'),
        ]
    )
    operator = PhoneOperator(link, gui, sentinel, act, ui, make_llm=lambda: llm)
    outcome = await operator.run("look around")
    assert outcome.status == "max_steps" and outcome.steps == 2
    # the nudge after the unparseable reply reached the model
    assert any("not one JSON object" in (m.content or "") for m in llm.calls[1]["messages"])

    ask = MockLLM([LLMResponse(content='{"action": "ask", "message": "请输入支付密码"}')])
    operator = PhoneOperator(link, gui, sentinel, act, ui, make_llm=lambda: ask)
    outcome = await operator.run("pay")
    assert outcome.status == "ask" and outcome.message == "请输入支付密码"
    assert "needs the user" in outcome.report()


async def test_phone_task_tool_reports_the_outcome(settings: Settings):
    link = PhoneLink()
    FakePhone(link, [HOME_SCREEN])
    ui = AutoApproveUI()
    gui = GUISettings()
    act = PhoneAct(link=link, gui=gui)
    llm = MockLLM([LLMResponse(content='{"action": "done", "message": "nothing to do"}')])
    operator = PhoneOperator(link, gui, make_sentinel(settings, ui), act, ui, make_llm=lambda: llm)
    task = PhoneTask(link=link, operator=operator)
    assert task.assess({"goal": "check", "app": "wechat"}).target == "wechat"
    result = await task.execute(goal="check the chat")
    assert result.ok and "nothing to do" in result.output
    assert not (await task.execute()).ok
    link.detach("conn-1")
    assert "no phone is connected" in (await task.execute(goal="x")).error


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
