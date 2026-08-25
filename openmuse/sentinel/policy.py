"""Sentinel policy engine – decides *allow / ask / deny* for a tool call.

Evaluation order (first hit wins for 1–4, 5 can only escalate):

1. ``deny_tools``
2. explicit ``[[sentinel.rules]]`` (tool glob + argument globs)
3. ``always_allow_tools`` / ``always_ask_tools``
4. risk level × mode  (``ask`` / ``strict`` / ``auto``)
5. taint tracking: after private data has been read, network egress to a
   destination that is not on ``egress_allowlist`` requires approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from typing import Any

from openmuse.config import SentinelSettings
from openmuse.schema import RiskLevel
from openmuse.tools.base import CallAssessment


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PolicyResult:
    decision: Decision
    reasons: list[str] = field(default_factory=list)


def _match_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch(name, p) for p in patterns)


def host_allowed(host: str | None, allowlist: list[str]) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    for pattern in allowlist:
        pattern = pattern.lower()
        if pattern == "*" or fnmatch(host, pattern):
            return True
        # "example.com" should also cover "www.example.com"
        if not pattern.startswith("*") and host.endswith("." + pattern):
            return True
    return False


class Policy:
    def __init__(self, settings: SentinelSettings):
        self.settings = settings

    def _rule_matches(
        self, rule_tool: str, match: dict[str, str], tool: str, args: dict[str, Any]
    ) -> bool:
        if not fnmatch(tool, rule_tool):
            return False
        for key, pattern in match.items():
            value = args.get(key, "")
            if isinstance(value, (dict, list)):
                value = str(value)
            if not fnmatch(str(value), pattern):
                return False
        return True

    def evaluate(
        self,
        tool: str,
        args: dict[str, Any],
        assessment: CallAssessment,
        tainted: bool = False,
    ) -> PolicyResult:
        s = self.settings
        reasons: list[str] = []

        # 1. hard deny
        if _match_any(tool, s.deny_tools):
            return PolicyResult(Decision.DENY, [f"'{tool}' is in sentinel.deny_tools"])

        decision: Decision | None = None

        # 2. explicit rules
        for rule in s.rules:
            if self._rule_matches(rule.tool, rule.match, tool, args):
                reason = rule.reason or f"matched rule tool='{rule.tool}' match={rule.match}"
                if rule.action == "deny":
                    return PolicyResult(Decision.DENY, [reason])
                decision = Decision(rule.action)
                reasons.append(reason)
                break

        # 3. per-tool overrides
        if decision is None:
            if _match_any(tool, s.always_allow_tools):
                decision, reasons = Decision.ALLOW, [f"'{tool}' is in always_allow_tools"]
            elif _match_any(tool, s.always_ask_tools):
                decision, reasons = Decision.ASK, [f"'{tool}' is in always_ask_tools"]

        # 4. risk × mode
        if decision is None:
            risk = assessment.risk
            if s.mode == "auto":
                decision = Decision.ALLOW
            elif s.mode == "strict":
                decision = Decision.ASK if risk.rank >= RiskLevel.MODERATE.rank else Decision.ALLOW
            else:  # ask
                decision = Decision.ASK if risk == RiskLevel.SENSITIVE else Decision.ALLOW
            if decision == Decision.ASK:
                reasons.append(f"risk level is '{risk.value}' (mode={s.mode})")

        # 5. taint tracking – can only escalate ALLOW → ASK
        if (
            decision == Decision.ALLOW
            and s.taint_tracking
            and tainted
            and assessment.egress
            and not host_allowed(assessment.egress_target, s.egress_allowlist)
        ):
            target = assessment.egress_target or "an unknown destination"
            decision = Decision.ASK
            reasons.append(
                f"private data was read earlier in this session and '{tool}' can send data to "
                f"{target}, which is not on sentinel.egress_allowlist"
            )

        if assessment.warnings:
            reasons.extend(assessment.warnings)
        return PolicyResult(decision, reasons)


__all__ = ["Decision", "Policy", "PolicyResult", "host_allowed"]
