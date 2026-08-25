"""The Sentinel: every tool call passes through here.

    agent  ──►  Sentinel.guard()  ──►  policy  ──►  (approval)  ──►  vault.resolve
                                                                        │
    agent  ◄──  redact(result)  ◄──  taint bookkeeping  ◄──  execute  ◄─┘

Nothing the model asks for reaches the outside world unless the Sentinel lets it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from openmuse.config import SentinelSettings
from openmuse.logger import logger
from openmuse.schema import ToolCall, ToolResult
from openmuse.sentinel.audit import AuditLog
from openmuse.sentinel.policy import Decision, Policy
from openmuse.tools.base import BaseTool, safe_execute
from openmuse.ui import UI, ApprovalRequest
from openmuse.vault import PLACEHOLDER_RE, CredentialVault


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
        self.session_allow: set[str] = set()
        self._persist_file = persistent_approvals_file
        self.persistent_allow: set[str] = self._load_persistent()

    # ------------------------------------------------------------------ persistence
    def _load_persistent(self) -> set[str]:
        if self._persist_file and self._persist_file.exists():
            try:
                return set(json.loads(self._persist_file.read_text("utf-8")))
            except (OSError, json.JSONDecodeError):
                return set()
        return set()

    def _save_persistent(self) -> None:
        if not self._persist_file:
            return
        self._persist_file.parent.mkdir(parents=True, exist_ok=True)
        self._persist_file.write_text(json.dumps(sorted(self.persistent_allow)), "utf-8")

    def forget_approvals(self) -> None:
        self.session_allow.clear()
        self.persistent_allow.clear()
        self._save_persistent()

    # ------------------------------------------------------------------ main entry
    async def guard(self, call: ToolCall, tool: BaseTool) -> ToolResult:
        args = call.arguments
        assessment = tool.assess(args)
        result_policy = self.policy.evaluate(tool.name, args, assessment, tainted=self.tainted)
        decision, reasons = result_policy.decision, list(result_policy.reasons)
        approved: bool | None = None
        scope: str | None = None

        if decision == Decision.ASK:
            if self.settings.mode == "auto":
                decision = Decision.ALLOW
                reasons.append("auto mode: approval skipped")
            elif tool.name in self.session_allow or tool.name in self.persistent_allow:
                decision = Decision.ALLOW
                reasons.append("pre-approved for this tool")
            else:
                request = ApprovalRequest(
                    tool=tool.name,
                    args=args,
                    summary=assessment.summary,
                    risk=assessment.risk,
                    reasons=reasons,
                    warnings=assessment.warnings,
                    egress_target=assessment.egress_target,
                )
                verdict = await self.ui.ask_approval(request)
                approved, scope = verdict.approved, verdict.scope
                if verdict.approved:
                    decision = Decision.ALLOW
                    if verdict.scope == "session":
                        self.session_allow.add(tool.name)
                    elif verdict.scope == "always":
                        self.persistent_allow.add(tool.name)
                        self._save_persistent()
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


__all__ = ["Sentinel"]
