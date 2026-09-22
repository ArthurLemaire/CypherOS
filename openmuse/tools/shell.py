"""Shell and Python execution inside the workspace."""

from __future__ import annotations

import asyncio
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment

_DANGEROUS = [
    (
        re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f|\brm\s+-[a-zA-Z]*f[a-zA-Z]*r"),
        "recursive force delete",
    ),
    (re.compile(r"\bsudo\b"), "privilege escalation (sudo)"),
    (re.compile(r"\bmkfs\b|\bdd\s+if="), "disk-level operation"),
    (re.compile(r"curl[^|]*\|\s*(ba)?sh|wget[^|]*\|\s*(ba)?sh"), "pipes a download into a shell"),
    (re.compile(r"\bchmod\s+-R\s+777\b"), "world-writable permissions"),
    (re.compile(r">\s*/dev/sd|\bshutdown\b|\breboot\b"), "system-level command"),
    (re.compile(r"\bgit\s+push\b.*--force"), "force push"),
]


async def _run(cmd: list[str] | str, cwd: Path, timeout: float, shell: bool) -> ToolResult:
    try:
        if shell:
            proc = await asyncio.create_subprocess_shell(
                cmd if isinstance(cmd, str) else " ".join(cmd),
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,  # type: ignore[misc]
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult.fail(f"timed out after {timeout:.0f}s")
    except FileNotFoundError as exc:
        return ToolResult.fail(str(exc))
    stdout = out.decode("utf-8", errors="replace")
    stderr = err.decode("utf-8", errors="replace")
    text = stdout
    if stderr.strip():
        text += ("\n" if text else "") + f"[stderr]\n{stderr}"
    text += f"\n[exit code {proc.returncode}]"
    if proc.returncode != 0:
        return ToolResult(output=text.strip(), error=f"exit code {proc.returncode}")
    return ToolResult(output=text.strip())


class Shell(BaseTool):
    name: str = "shell"
    description: str = (
        "Run a shell command in the workspace directory (bash). Use for git, package managers, "
        "file conversions, quick data processing. Long-running or interactive commands are not "
        "supported. Output is truncated."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number", "description": "Seconds (default 60, max 600)."},
        },
        "required": ["command"],
    }
    risk: RiskLevel = RiskLevel.SENSITIVE
    egress: bool = True  # a shell can reach the network
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        command = str(args.get("command", ""))
        warnings = [label for pattern, label in _DANGEROUS if pattern.search(command)]
        return CallAssessment(
            risk=RiskLevel.SENSITIVE,
            egress=True,
            egress_target=None,
            summary=f"shell: {command[:160]}",
            warnings=[f"command looks dangerous: {w}" for w in warnings],
        )

    async def execute(self, command: str = "", timeout: float = 60, **_: Any) -> ToolResult:
        if not command.strip():
            return ToolResult.fail("empty command")
        timeout = max(1.0, min(float(timeout or 60), 600.0))
        self.workspace.mkdir(parents=True, exist_ok=True)
        return await _run(command, self.workspace, timeout, shell=True)


class PythonExecute(BaseTool):
    name: str = "python_execute"
    description: str = (
        "Execute a Python script in a subprocess (cwd = workspace) and return stdout/stderr. "
        "Use print() to output results. Good for calculations, data wrangling, and small automations."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "timeout": {"type": "number", "description": "Seconds (default 60, max 600)."},
        },
        "required": ["code"],
    }
    risk: RiskLevel = RiskLevel.MODERATE
    egress: bool = True
    workspace: Path

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        code = str(args.get("code", ""))
        first = code.strip().splitlines()[0][:100] if code.strip() else ""
        warnings = []
        if re.search(r"\b(os\.system|subprocess|shutil\.rmtree|os\.remove)\b", code):
            warnings.append("code performs shell/file-deletion operations")
        return CallAssessment(
            risk=RiskLevel.MODERATE,
            egress=True,
            summary=f"python_execute: {first} ({len(code)} chars)",
            warnings=warnings,
        )

    async def execute(self, code: str = "", timeout: float = 60, **_: Any) -> ToolResult:
        if not code.strip():
            return ToolResult.fail("empty code")
        timeout = max(1.0, min(float(timeout or 60), 600.0))
        self.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".py",
            prefix="openmuse_",
            dir=self.workspace,
            delete=False,
            encoding="utf-8",
        ) as fh:
            fh.write(code)
            script = Path(fh.name)
        try:
            return await _run([sys.executable, str(script)], self.workspace, timeout, shell=False)
        finally:
            script.unlink(missing_ok=True)


__all__ = ["PythonExecute", "Shell"]
