from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openmuse.config import SentinelRule, SentinelSettings
from openmuse.schema import Function, RiskLevel, ToolCall, ToolResult
from openmuse.sentinel import AuditLog, Decision, Policy, Sentinel, host_allowed
from openmuse.tools.base import BaseTool, CallAssessment
from openmuse.ui import HeadlessUI
from openmuse.vault import CredentialVault


class Echo(BaseTool):
    name: str = "echo"
    description: str = "echo"
    parameters: dict[str, Any] = {"type": "object", "properties": {"text": {"type": "string"}}}
    risk: RiskLevel = RiskLevel.SAFE

    async def execute(self, text: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"echo: {text}")


class Sender(BaseTool):
    name: str = "sender"
    description: str = "sends data"
    parameters: dict[str, Any] = {"type": "object", "properties": {"host": {"type": "string"}}}
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True
    accepts_secrets: bool = True

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        return CallAssessment(
            risk=self.risk, egress=True, egress_target=args.get("host"), summary="sender"
        )

    async def execute(self, host: str = "", token: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"sent to {host} with {token}")


class Reader(BaseTool):
    name: str = "reader"
    description: str = "reads private data"
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    reads_private_data: bool = True

    async def execute(self, **_: Any) -> ToolResult:
        return ToolResult(output="private stuff")


def call(name: str, **args: Any) -> ToolCall:
    import json

    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


# ----------------------------------------------------------------------------- policy
def test_host_allowed():
    allow = ["duckduckgo.com", "*.wikipedia.org"]
    assert host_allowed("duckduckgo.com", allow)
    assert host_allowed("html.duckduckgo.com", allow)
    assert host_allowed("en.wikipedia.org", allow)
    assert not host_allowed("wikipedia.org", allow)  # pattern requires a subdomain
    assert not host_allowed("evil.com", allow)
    assert not host_allowed(None, allow)
    assert host_allowed("anything", ["*"])


@pytest.mark.parametrize(
    ("mode", "risk", "expected"),
    [
        ("ask", RiskLevel.SAFE, Decision.ALLOW),
        ("ask", RiskLevel.MODERATE, Decision.ALLOW),
        ("ask", RiskLevel.SENSITIVE, Decision.ASK),
        ("strict", RiskLevel.MODERATE, Decision.ASK),
        ("strict", RiskLevel.SAFE, Decision.ALLOW),
        ("auto", RiskLevel.SENSITIVE, Decision.ALLOW),
    ],
)
def test_risk_mode_matrix(mode: str, risk: RiskLevel, expected: Decision):
    policy = Policy(SentinelSettings(mode=mode, always_ask_tools=[]))
    result = policy.evaluate("x", {}, CallAssessment(risk=risk))
    assert result.decision == expected


def test_rules_and_overrides():
    settings = SentinelSettings(
        deny_tools=["nuke"],
        always_allow_tools=["python_*"],
        rules=[
            SentinelRule(tool="shell", match={"command": "*rm -rf*"}, action="deny", reason="no")
        ],
    )
    policy = Policy(settings)
    assert policy.evaluate("nuke", {}, CallAssessment()).decision == Decision.DENY
    assert (
        policy.evaluate(
            "shell", {"command": "rm -rf /"}, CallAssessment(risk=RiskLevel.SENSITIVE)
        ).decision
        == Decision.DENY
    )
    assert (
        policy.evaluate(
            "shell", {"command": "ls"}, CallAssessment(risk=RiskLevel.SENSITIVE)
        ).decision
        == Decision.ASK
    )
    assert (
        policy.evaluate("python_execute", {}, CallAssessment(risk=RiskLevel.SENSITIVE)).decision
        == Decision.ALLOW
    )


def test_taint_escalates_egress():
    policy = Policy(SentinelSettings(egress_allowlist=["*.wikipedia.org"]))
    clean = policy.evaluate(
        "web_fetch", {}, CallAssessment(egress=True, egress_target="evil.com"), tainted=False
    )
    assert clean.decision == Decision.ALLOW
    tainted = policy.evaluate(
        "web_fetch", {}, CallAssessment(egress=True, egress_target="evil.com"), tainted=True
    )
    assert tainted.decision == Decision.ASK
    ok = policy.evaluate(
        "web_fetch", {}, CallAssessment(egress=True, egress_target="en.wikipedia.org"), tainted=True
    )
    assert ok.decision == Decision.ALLOW
    unknown = policy.evaluate(
        "shell", {}, CallAssessment(risk=RiskLevel.SAFE, egress=True), tainted=True
    )
    assert unknown.decision == Decision.ASK


# ----------------------------------------------------------------------------- gate
async def test_gate_allows_safe_and_audits(tmp_path: Path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    gate = Sentinel(SentinelSettings(), audit, HeadlessUI())
    result = await gate.guard(call("echo", text="hi"), Echo())
    assert result.output == "echo: hi"
    entries = audit.tail()
    assert entries[-1]["event"] == "tool_call" and entries[-1]["decision"] == "allow"


async def test_gate_denies_when_user_declines(tmp_path: Path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), audit, HeadlessUI(approve=False))
    result = await gate.guard(call("echo", text="hi"), Echo())
    assert result.error and "Sentinel blocked" in result.error
    assert audit.tail()[-1]["decision"] == "deny"


async def test_gate_session_approval_is_cached(tmp_path: Path):
    ui = HeadlessUI(approve=True)
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), AuditLog(tmp_path / "a.jsonl"), ui)
    await gate.guard(call("echo", text="1"), Echo())
    approvals = [e for e in ui.events if e[0] == "approval"]
    assert len(approvals) == 1
    gate.session_allow.add("echo")
    await gate.guard(call("echo", text="2"), Echo())
    assert len([e for e in ui.events if e[0] == "approval"]) == 1


async def test_gate_taint_then_egress_asks(tmp_path: Path):
    ui = HeadlessUI(approve=False)
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), ui)
    assert not gate.tainted
    await gate.guard(call("reader"), Reader())
    assert gate.tainted
    blocked = await gate.guard(call("sender", host="evil.com"), Sender())
    assert blocked.error and "not on sentinel.egress_allowlist" in blocked.error
    allowed = await gate.guard(call("sender", host="api.github.com"), Sender())
    assert allowed.ok


async def test_gate_resolves_secrets_and_redacts(tmp_path: Path):
    vault = CredentialVault(tmp_path / "v.enc", tmp_path / "v.key")
    vault.set("API_TOKEN", "super-secret-token")
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), HeadlessUI(), vault=vault)
    result = await gate.guard(
        call("sender", host="github.com", token="{{vault:API_TOKEN}}"), Sender()
    )
    # the tool received the real secret, but the model sees a redacted output
    assert result.output == "sent to github.com with [REDACTED:API_TOKEN]"
    # a tool that does not accept secrets receives the literal placeholder
    result2 = await gate.guard(call("echo", text="{{vault:API_TOKEN}}"), Echo())
    assert result2.output == "echo: {{vault:API_TOKEN}}"
