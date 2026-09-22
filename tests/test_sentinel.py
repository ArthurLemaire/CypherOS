from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from openmuse.config import SentinelRule, SentinelSettings
from openmuse.schema import Function, RiskLevel, ToolCall, ToolResult
from openmuse.sentinel import AuditLog, Decision, Policy, Sentinel, host_allowed
from openmuse.sentinel import grants as grants_module
from openmuse.sentinel.grants import GrantStore
from openmuse.tools.base import BaseTool, CallAssessment
from openmuse.tools.shell import programs_of
from openmuse.ui import ApprovalDecision, ApprovalRequest, HeadlessUI
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


class ScopedUI(HeadlessUI):
    """Approves with a chosen scope and keeps the requests for inspection."""

    def __init__(self, scope: str = "once", approve: bool = True):
        super().__init__(approve=approve)
        self.scope = scope
        self.requests: list[ApprovalRequest] = []

    async def ask_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        self._log("approval", request.summary)
        return ApprovalDecision(approved=self.approve, scope=self.scope)  # type: ignore[arg-type]


def asks(ui: HeadlessUI) -> int:
    return len([e for e in ui.events if e[0] == "approval"])


async def test_gate_session_grant_covers_later_calls(tmp_path: Path):
    ui = ScopedUI(scope="session")
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), AuditLog(tmp_path / "a.jsonl"), ui)
    await gate.guard(call("echo", text="1"), Echo())
    assert asks(ui) == 1
    await gate.guard(call("echo", text="2"), Echo())
    assert asks(ui) == 1, "the session grant covers the second call"
    assert [g.key for g in gate.active_grants()] == ["echo"]
    assert gate.revoke("echo")
    await gate.guard(call("echo", text="3"), Echo())
    assert asks(ui) == 2, "revoked: asks again"


async def test_gate_grant_is_bound_to_target(tmp_path: Path):
    ui = ScopedUI(scope="always")
    gate = Sentinel(
        SentinelSettings(always_ask_tools=["sender"]),
        AuditLog(tmp_path / "a.jsonl"),
        ui,
        persistent_approvals_file=tmp_path / "approvals.json",
    )
    await gate.guard(call("sender", host="a.example"), Sender())
    assert ui.requests[-1].grant_key == "sender:a.example"
    assert "always" in ui.requests[-1].grant_options
    await gate.guard(call("sender", host="a.example"), Sender())
    assert asks(ui) == 1
    await gate.guard(call("sender", host="b.example"), Sender())
    assert asks(ui) == 2, "a different destination is a different capability"
    # "always" survives a restart
    again = Sentinel(
        SentinelSettings(always_ask_tools=["sender"]),
        AuditLog(tmp_path / "a.jsonl"),
        ScopedUI(),
        persistent_approvals_file=tmp_path / "approvals.json",
    )
    assert {g.key for g in again.active_grants()} == {"sender:a.example", "sender:b.example"}


async def test_gate_task_grant_ends_with_the_task(tmp_path: Path):
    ui = ScopedUI(scope="task")
    gate = Sentinel(SentinelSettings(always_ask_tools=["echo"]), AuditLog(tmp_path / "a.jsonl"), ui)
    token = gate.begin_task("book the tickets")
    await gate.guard(call("echo", text="1"), Echo())
    assert ui.requests[-1].purpose == "book the tickets"
    await gate.guard(call("echo", text="2"), Echo())
    assert asks(ui) == 1
    gate.end_task(token)
    token = gate.begin_task("something else")
    await gate.guard(call("echo", text="3"), Echo())
    assert asks(ui) == 2, "task grants do not leak into the next task"
    gate.end_task(token)


async def test_gate_warnings_are_never_covered_by_grants(tmp_path: Path):
    class Risky(Echo):
        def assess(self, args: dict[str, Any]) -> CallAssessment:
            return CallAssessment(
                risk=RiskLevel.SENSITIVE, summary="risky", warnings=["looks dangerous"]
            )

    ui = ScopedUI(scope="always")
    gate = Sentinel(SentinelSettings(), AuditLog(tmp_path / "a.jsonl"), ui)
    gate.grants.add("echo", None, "session")
    await gate.guard(call("echo", text="1"), Risky())
    assert asks(ui) == 1, "a standing grant does not cover a call with warnings"
    assert ui.requests[-1].grant_options == ["once"]
    # the UI answered "always" although only "once" was offered: downgraded, asks again
    await gate.guard(call("echo", text="2"), Risky())
    assert asks(ui) == 2


def test_grant_options_follow_muse_rules():
    sensitive_known = CallAssessment(risk=RiskLevel.SENSITIVE, egress=True, egress_target="x")
    assert Sentinel.grant_options(sensitive_known, "x") == [
        "once",
        "task",
        "session",
        "24h",
        "always",
    ]
    sensitive_unknown = CallAssessment(risk=RiskLevel.SENSITIVE, egress=True)
    assert Sentinel.grant_options(sensitive_unknown, None) == ["once", "task"]
    safe_toolwide = CallAssessment(risk=RiskLevel.SAFE)
    assert "always" in Sentinel.grant_options(safe_toolwide, None)
    with_warning = CallAssessment(risk=RiskLevel.SAFE, warnings=["w"])
    assert Sentinel.grant_options(with_warning, "x") == ["once"]


def test_grant_store_expiry_and_legacy_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    legacy = tmp_path / "approvals.json"
    legacy.write_text('["shell"]', "utf-8")
    store = GrantStore(legacy)
    assert store.match("shell") is not None and store.match("shell").scope == "always"
    # a 24h grant given two days ago
    real_time = time.time
    monkeypatch.setattr(grants_module.time, "time", lambda: real_time() - 2 * grants_module.DAY)
    day = store.add("web_fetch", "example.com", "24h")
    monkeypatch.undo()
    assert day is not None and day.expires_at is not None
    assert store.match("web_fetch:example.com") is None
    assert store.add("echo", None, "once") is None, "once is never stored"
    assert store.add("echo", None, "task", task_id=None) is None, "task needs a task"
    reloaded = GrantStore(legacy)
    assert [g.key for g in reloaded.active()] == ["shell"], "expired grants are dropped on load"


def test_grants_compose_over_several_targets():
    store = GrantStore()
    store.add("shell", "git,head", "session")
    assert {g.key for g in store.active()} == {"shell:git", "shell:head"}
    assert store.match("shell:git") is not None, "approving a pipeline covers its programs"
    assert store.match("shell:head,git") is not None
    assert store.match("shell:git,curl") is None, "every program needs a grant"
    store.add("shell", None, "session")
    assert store.match("shell:curl") is not None, "a tool-wide grant covers every target"


def test_shell_programs_are_the_grant_target():
    assert programs_of("git status") == "git"
    assert programs_of("cd web && npm run build") == "npm"
    assert programs_of("FOO=1 env python3 x.py | grep y") == "grep,python3"
    assert programs_of("/usr/bin/curl https://x") == "curl"
    assert programs_of("echo hi") == "echo"
    assert programs_of("cd /tmp") is None


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
