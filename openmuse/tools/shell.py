"""Shell and Python execution inside the workspace.

Both run as subprocesses with a scrubbed environment: anything that looks like a
credential (``*_KEY``, ``*TOKEN*``, ``*SECRET*``, ``*PASSWORD*``, ``OPENMUSE_*`` …) is
removed before the child starts, so a script the model wrote cannot read the model's
own API key, the vault key or the app token out of ``os.environ``. Secrets a command
really needs go in as ``{{vault:NAME}}`` arguments instead, which Sentinel fills in
after approval.

With a working sandbox (``openmuse.sandbox``, bubblewrap on Linux) each call also gets
its own namespace: the workspace is the only writable place, the home directory is not
there, and there is no network unless the call was assessed as needing it.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from openmuse.sandbox import Sandbox, needs_network
from openmuse.schema import RiskLevel, ToolResult
from openmuse.tools.base import BaseTool, CallAssessment

_SECRET_ENV = re.compile(
    r"(KEY|TOKEN|SECRET|PASSW|PASSPHRASE|CREDENTIAL|_AUTH|AUTH_|COOKIE|SESSION)", re.IGNORECASE
)
_SECRET_ENV_PREFIXES = ("OPENMUSE_", "AWS_", "AZURE_", "GOOGLE_", "GH_", "GITHUB_", "NPM_")
# the user's ssh agent is a credential too, even though the name does not say so
_ALWAYS_DROP = {"SSH_AUTH_SOCK", "GPG_AGENT_INFO"}


def scrubbed_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """The parent's environment minus anything that looks like a credential."""
    env: dict[str, str] = {}
    for name, value in (source if source is not None else os.environ).items():
        upper = name.upper()
        if (
            name in _ALWAYS_DROP
            or _SECRET_ENV.search(upper)
            or upper.startswith(_SECRET_ENV_PREFIXES)
        ):
            continue
        env[name] = value
    env["OPENMUSE_SANDBOX"] = "1"
    return env


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


_SKIP_PROGRAMS = {"cd", "export", "set", "true", "time", "env", "nohup", "exec"}

# What a Python script can reach beyond plain computation and the workspace. Each hit
# makes the call sensitive and puts its reason on the approval card.
_REACH: list[tuple[str, re.Pattern[str]]] = [
    (
        "network",
        re.compile(
            r"\b(import\s+(socket|urllib|http\.client|httpx|requests|aiohttp|ftplib|smtplib|"
            r"imaplib|telnetlib|websocket|paramiko)|from\s+(urllib|http|httpx|requests|aiohttp|"
            r"socket)\b)"
        ),
    ),
    (
        "processes",
        re.compile(
            r"\b(import\s+(subprocess|pty|multiprocessing)|from\s+subprocess|os\.(system|popen|"
            r"exec[lv]p?e?|spawn[lv]p?e?|fork|kill)|ctypes)\b"
        ),
    ),
    ("environment", re.compile(r"\bos\.(environ|getenv|putenv)\b")),
    (
        "deletion",
        re.compile(
            r"\b(shutil\.rmtree|os\.(remove|unlink|rmdir|removedirs)|Path\([^)]*\)\.unlink)\b"
        ),
    ),
    (
        "outside the workspace",
        re.compile(
            r"(['\"](/(etc|home|root|usr|var|proc|sys|dev|tmp|opt|Users)/|~/?)|"
            r"Path\.home\(\)|expanduser\()"
        ),
    ),
]
_REACH_LABELS = {
    "network": "reaches the network",
    "processes": "starts other programs",
    "environment": "reads environment variables",
    "deletion": "deletes files",
    "outside the workspace": "touches paths outside the workspace",
}


_ABS_PATH = re.compile(r"['\"](/[^'\"\n]*)")
_HOME = re.compile(r"['\"]~|Path\.home\(\)|expanduser\(")


def code_reach(code: str, workspace: Path | None = None) -> dict[str, str]:
    """``{kind: human label}`` for everything a script reaches beyond the workspace.

    With ``workspace`` given, absolute paths that stay inside it do not count as
    "outside" (a workspace under ``/tmp`` or ``/home`` would otherwise flag every write).
    """
    reach = {kind: _REACH_LABELS[kind] for kind, pattern in _REACH if pattern.search(code)}
    if "outside the workspace" in reach and workspace is not None and not _HOME.search(code):
        root = workspace.resolve().as_posix().rstrip("/") + "/"
        paths = [m.group(1) for m in _ABS_PATH.finditer(code)]
        if paths and all(p.startswith(root) or p + "/" == root for p in paths):
            del reach["outside the workspace"]
    return reach


def programs_of(command: str) -> str | None:
    """The programs a shell command runs (``cd web && npm run build`` → ``npm``).

    This is what an approval for a shell command is bound to: allowing ``git`` for the
    session does not allow ``curl``. Returns ``None`` when nothing recognisable is found.
    """
    names: list[str] = []
    for segment in re.split(r"\|\||&&|;|\||\n", command):
        tokens = segment.strip().split()
        while tokens and (
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]) or tokens[0] in ("env", "time")
        ):
            tokens.pop(0)
        if not tokens:
            continue
        program = tokens[0].rsplit("/", 1)[-1]
        if program in _SKIP_PROGRAMS or not re.fullmatch(r"[A-Za-z0-9_.+-]+", program):
            continue
        if program not in names:
            names.append(program)
    return ",".join(sorted(names)) if names else None


async def _run(
    cmd: list[str] | str,
    cwd: Path,
    timeout: float,
    shell: bool,
    sandbox: Sandbox | None = None,
    network: bool = True,
) -> ToolResult:
    env = scrubbed_env()
    boxed = sandbox is not None and sandbox.active
    # a box that cannot take the network away never ran the command without it
    without_network = boxed and sandbox is not None and sandbox.blocks_network and not network
    if boxed:
        assert sandbox is not None
        argv = ["/bin/sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)
        cmd = sandbox.wrap(argv, network=network, cwd=cwd)
        shell = False
    try:
        if shell:
            proc = await asyncio.create_subprocess_shell(
                cmd if isinstance(cmd, str) else " ".join(cmd),
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,  # type: ignore[misc]
                cwd=str(cwd),
                env=env,
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
        if without_network and _NO_NETWORK.search(stderr + stdout):
            text += (
                "\n[sandbox: this command ran without network access. Commands that reach the "
                "network say so by what they run (curl, pip, git …) or by a URL in them; if this "
                "one needs the network, run it again with network=true.]"
            )
        return ToolResult(output=text.strip(), error=f"exit code {proc.returncode}")
    return ToolResult(output=text.strip())


# what a command says when it wanted the network and the box had none
_NO_NETWORK = re.compile(
    r"Could not resolve|Name or service not known|Temporary failure in name resolution|"
    r"Network is unreachable|getaddrinfo|nodename nor servname|No address associated|"
    r"NameResolutionError|ConnectError|Failed to connect",
    re.IGNORECASE,
)


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
            "network": {
                "type": "boolean",
                "description": (
                    "Set when the command needs the network and that is not obvious from "
                    "what it runs (curl, pip, git … and URLs are recognised on their own)."
                ),
            },
        },
        "required": ["command"],
    }
    risk: RiskLevel = RiskLevel.SENSITIVE
    egress: bool = True  # a shell can reach the network
    workspace: Path
    # With a working sandbox the command gets the network only when it says so, and
    # only then does the Sentinel treat it as egress. Without one, every shell command
    # may reach the network and is treated that way.
    sandbox: Sandbox | None = None

    def _network(self, args: dict[str, Any]) -> bool:
        command = str(args.get("command", ""))
        return bool(args.get("network")) or needs_network(command, programs_of(command))

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        command = str(args.get("command", ""))
        warnings = [label for pattern, label in _DANGEROUS if pattern.search(command)]
        # a box that takes the network away decides which commands get it; one that
        # cannot (see Sandbox.blocks_network), like no box, leaves every command able to
        boxed = self.sandbox is not None and self.sandbox.active and self.sandbox.blocks_network
        network = self._network(args)
        return CallAssessment(
            risk=RiskLevel.SENSITIVE,
            egress=network if boxed else True,
            egress_target=None,
            target=programs_of(command),
            # in the box the card says when a command gets the network; unboxed, all do
            summary=f"shell{' (network)' if boxed and network else ''}: {command[:160]}",
            warnings=[f"command looks dangerous: {w}" for w in warnings],
        )

    async def execute(
        self, command: str = "", timeout: float = 60, network: bool = False, **_: Any
    ) -> ToolResult:
        if not command.strip():
            return ToolResult.fail("empty command")
        timeout = max(1.0, min(float(timeout or 60), 600.0))
        self.workspace.mkdir(parents=True, exist_ok=True)
        return await _run(
            command,
            self.workspace,
            timeout,
            shell=True,
            sandbox=self.sandbox,
            network=self._network({"command": command, "network": network}),
        )


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
    # In the sandbox a script gets the network only when it imports something that uses
    # it (or starts programs, which could); see ``code_reach``.
    sandbox: Sandbox | None = None

    def assess(self, args: dict[str, Any]) -> CallAssessment:
        """Plain computation and files in the workspace are moderate (auto-allowed in the
        default mode). Anything that reaches further — the network, other processes, the
        environment, paths outside the workspace, deletions — is sensitive and stops for
        approval, with the reason on the card."""
        code = str(args.get("code", ""))
        first = code.strip().splitlines()[0][:100] if code.strip() else ""
        reach = code_reach(code, self.workspace)
        return CallAssessment(
            risk=RiskLevel.SENSITIVE if reach else RiskLevel.MODERATE,
            egress=bool(reach.get("network")) or bool(reach.get("processes")),
            target=None,
            summary=f"python_execute: {first} ({len(code)} chars)",
            warnings=[f"code {what}" for what in reach.values()],
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
        reach = code_reach(code, self.workspace)
        try:
            return await _run(
                [sys.executable, str(script)],
                self.workspace,
                timeout,
                shell=False,
                sandbox=self.sandbox,
                network=bool(reach.get("network")) or bool(reach.get("processes")),
            )
        finally:
            script.unlink(missing_ok=True)


__all__ = ["PythonExecute", "Shell", "code_reach", "needs_network", "programs_of", "scrubbed_env"]
