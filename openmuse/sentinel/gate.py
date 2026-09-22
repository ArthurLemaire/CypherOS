"""The Sentinel: every tool call passes through here.

    agent  ──►  Sentinel.guard()  ──►  policy  ──►  grants / approval  ──►  vault.resolve
                                                                              │
    agent  ◄──  redact(result)  ◄──  taint bookkeeping  ◄──  execute  ◄───────┘

Nothing the model asks for reaches the outside world unless the Sentinel lets it. An
approval the user gives is a capability bound to a tool and a target (host, recipient,
program) with a lifetime — see :mod:`openmuse.sentinel.grants`.
"""

from __future__ import annotations

import json
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openmuse.config import SentinelSettings
from openmuse.logger import logger
from openmuse.schema import RiskLevel, ToolCall, ToolResult
from openmuse.sentinel.audit import AuditLog
from openmuse.sentinel.grants import SCOPES, Grant, GrantStore, grant_key
from openmuse.sentinel.policy import Decision, Policy
from openmuse.tools.base import BaseTool, CallAssessment, safe_execute
from openmuse.ui import UI, ApprovalRequest
from openmuse.vault import PLACEHOLDER_RE, CredentialVault


@dataclass
class TaskContext:
    """The agent run a tool call belongs to: gives approvals a purpose and a task scope."""

    id: str
    purpose: str = ""


_current_task: ContextVar[TaskContext | None] = ContextVar("openmuse_task", default=None)


def current_task() -> TaskContext | None:
    return _current_task.get()


class Sentinel:
    def __init__(
        self,
        settings: SentinelSettings,
        audit: AuditLog,
        ui: UI,
        vault: CredentialVault | None = None,
        persistent_approvals_file: Path | None = None,
    ):
        self.settings = settings
        self.policy = Policy(settings)
        self.audit = audit
        self.ui = ui
        self.vault = vault
        self.tainted = False
        self.grants = GrantStore(persistent_approvals_file)

    # ------------------------------------------------------------------ task scope
    def begin_task(self, purpose: str = "", task_id: str | None = None) -> Any:
        """Mark the start of an agent run. Returns a token for :meth:`end_task`."""
        ctx = TaskContext(id=task_id or uuid.uuid4().hex[:10], purpose=purpose.strip()[:200])
        return _current_task.set(ctx)

    def end_task(self, token: Any) -> None:
        ctx = _current_task.get()
        if ctx is not None:
            self.grants.end_task(ctx.id)
        _current_task.reset(token)

    # ------------------------------------------------------------------ grants
    def forget_approvals(self) -> None:
        self.grants.clear()

    def revoke(self, key: str) -> bool:
        return self.grants.revoke(key)

    def active_grants(self) -> list[Grant]:
        ctx = _current_task.get()
        return self.grants.active(ctx.id if ctx else None)

    @staticmethod
    def grant_options(assessment: CallAssessment, target: str | None) -> list[str]:
        """Which standing permissions to offer. Calls with warnings get none: a
        dangerous-looking command or a purchase is approved every single time."""
        if assessment.warnings:
            return ["once"]
        options = ["once", "task"]
        unknown_destination = target is None and assessment.egress
        if unknown_destination and assessment.risk.rank >= RiskLevel.MODERATE.rank:
            return options  # arbitrary code with network access: never a standing grant
        options += ["session", "24h"]
        if target is not None or assessment.risk != RiskLevel.SENSITIVE:
            options.append("always")
        return options

    # ------------------------------------------------------------------ main entry
    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        args = call.arguments
        if "__raw__" in args:
            # The arguments never parsed (cut off in transit): there is nothing to assess,
            # nothing to approve and nothing to run. The result tells the model what happened.
            return await safe_execute(tool, args)
        assessment = tool.assess(args)
        target = assessment.target if assessment.target is not None else assessment.egress_target
        key = grant_key(tool.name, target)
        task = _current_task.get()
        result_policy = self.policy.evaluate(tool.name, args, assessment, tainted=self.tainted)
        decision, reasons = result_policy.decision, list(result_policy.reasons)
        approved: bool | None = None
        scope: str | None = None

        if decision == Decision.ASK:
            grant = (
                None if assessment.warnings else self.grants.match(key, task.id if task else None)
            )
            if self.settings.mode == "auto":
                decision = Decision.ALLOW
                reasons.append("auto mode: approval skipped")
            elif grant is not None:
                decision = Decision.ALLOW
                scope = grant.scope
                reasons.append(f"covered by your '{grant.scope}' permission for {grant.key}")
            else:
                options = self.grant_options(assessment, target)
                request = ApprovalRequest(
                    tool=tool.name,
                    args=args,
                    summary=assessment.summary,
                    risk=assessment.risk,
                    reasons=reasons,
                    warnings=assessment.warnings,
                    egress_target=assessment.egress_target,
                    purpose=task.purpose if task else "",
                    target=target,
                    grant_key=key,
                    grant_options=options,  # type: ignore[arg-type]
                )
                verdict = await self.ui.ask_approval(request)
                approved, scope = verdict.approved, verdict.scope
                if verdict.approved:
                    decision = Decision.ALLOW
                    if scope not in options or scope not in SCOPES:
                        logger.warning(
                            "scope '{}' was not offered for {}; treating as once", scope, key
                        )
                        scope = "once"
                    bind = target
                    if scope == "task" and assessment.egress_target is None:
                        # "For this task" on a tool whose target is not a destination (shell,
                        # where it is the list of programs) means the tool for the rest of the
                        # run: a job that needs `git` now will need `ls` and `wc` next, and
                        # asking for each new program is noise, not safety. Warnings still stop
                        # every call; destinations (mail recipients, hosts) stay bound.
                        bind = None
                    self.grants.add(tool.name, bind, scope, task.id if task else None)
                else:
                    decision = Decision.DENY
                    reasons.append(
                        f"user declined{': ' + verdict.reason if verdict.reason else ''}"
                    )

        self.ui.on_sentinel(decision.value, assessment.summary, reasons)
        redacted_args = self._redact_obj(args)

        if decision == Decision.DENY:
            why = "; ".join(reasons) or "policy"
            result = ToolResult.fail(
                f"Sentinel blocked '{tool.name}': {why}. Do not retry the same call; "
                "explain the situation to the user or choose a different approach."
            )
            self.audit.record(
                "tool_call",
                tool=tool.name,
                args=redacted_args,
                summary=assessment.summary,
                risk=assessment.risk.value,
                decision="deny",
                approved=approved,
                reasons=reasons,
                tainted=self.tainted,
                egress_target=assessment.egress_target,
                grant_key=key,
                purpose=task.purpose if task else "",
                ok=False,
                error=result.error,
            )
            return result

        # Resolve vault placeholders only for tools that opted in.
        exec_args: dict[str, Any] = args
        if self.vault is not None and self.vault.has_placeholders(args):
            if tool.accepts_secrets:
                try:
                    exec_args = self.vault.resolve(args)
                except Exception as exc:  # noqa: BLE001
                    return ToolResult.fail(str(exc))
            else:
                logger.warning(
                    "tool '{}' received vault placeholders but does not accept secrets", tool.name
                )

        started = time.perf_counter()
        result = await safe_execute(tool, exec_args)
        duration_ms = int((time.perf_counter() - started) * 1000)

        if self.vault is not None:
            result.output = self.vault.redact(result.output)
            if result.error:
                result.error = self.vault.redact(result.error)

        if assessment.reads_private_data and result.ok and self.settings.taint_tracking:
            if not self.tainted:
                logger.debug("session is now tainted (read private data via {})", tool.name)
            self.tainted = True

        self.audit.record(
            "tool_call",
            tool=tool.name,
            args=redacted_args,
            summary=assessment.summary,
            risk=assessment.risk.value,
            decision="allow",
            approved=approved,
            approval_scope=scope,
            reasons=reasons,
            tainted=self.tainted,
            egress_target=assessment.egress_target,
            grant_key=key,
            purpose=task.purpose if task else "",
            ok=result.ok,
            error=result.error,
            duration_ms=duration_ms,
            output_preview=result.output[:300] if result.output else "",
        )
        return result

    # ------------------------------------------------------------------ helpers
    def _redact_obj(self, value: Any) -> Any:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if self.vault is not None:
            text = self.vault.redact(text)
        # placeholders are fine to log as-is; make sure raw values never sneak in
        text = PLACEHOLDER_RE.sub(lambda m: "{{vault:" + m.group(1) + "}}", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:  # pragma: no cover
            return text


__all__ = ["Sentinel", "TaskContext", "current_task"]
