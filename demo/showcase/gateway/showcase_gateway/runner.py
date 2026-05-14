"""Starting and stopping the per-session containers, through the ``docker`` CLI.

One container per session, on a network with no way out (``docker network create --internal``):
the only thing a session can talk to is this gateway, which is also where its model calls go.
The container is as locked down as the project's own compose file makes it — no capabilities,
no new privileges, a read-only image with tmpfs for the three places nanoMuse writes — plus a
memory, CPU and process ceiling so one visitor cannot crowd out the others.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from .config import Settings

log = logging.getLogger("showcase.runner")

LABEL = "io.github.nanomuse.showcase"


class RunnerError(RuntimeError):
    pass


class Runner(Protocol):
    async def start(self, name: str, env: dict[str, str]) -> str:
        """Start a container; return the address the gateway reaches it at."""
        ...

    async def stop(self, name: str) -> None: ...

    async def leftovers(self) -> list[str]:
        """Names of containers from an earlier life of this gateway."""
        ...

    async def gateway_address(self) -> str | None:
        """The address of this host on the sessions network, for the containers."""
        ...


class DockerRunner:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    async def _docker(self, *args: str, timeout: float = 60) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError as exc:
            proc.kill()
            raise RunnerError(f"docker {args[0]} timed out") from exc
        if proc.returncode != 0:
            raise RunnerError(f"docker {args[0]} failed: {err.decode(errors='replace').strip()}")
        return out.decode().strip()

    async def start(self, name: str, env: dict[str, str]) -> str:
        s = self.s
        cmd = [
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--hostname",
            "nanomuse",
            "--network",
            s.sessions_network,
            "--label",
            f"{LABEL}=1",
            "--memory",
            s.memory,
            "--cpus",
            s.cpus,
            "--pids-limit",
            str(s.pids),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--tmpfs",
            "/data:size=256m,uid=1000,gid=1000,mode=0750",
            "--tmpfs",
            "/workspace:size=256m,uid=1000,gid=1000,mode=0750",
            "--tmpfs",
            "/home/muse:size=64m,uid=1000,gid=1000,mode=0750",
            "--tmpfs",
            "/tmp:size=64m,mode=1777",
        ]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        cmd.append(s.image)
        await self._docker(*cmd, timeout=120)
        try:
            address = await self._docker(
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                name,
            )
        except RunnerError:
            await self.stop(name)
            raise
        if not address:
            await self.stop(name)
            raise RunnerError(f"{name} got no address on {s.sessions_network}")
        return address

    async def stop(self, name: str) -> None:
        try:
            await self._docker("rm", "-f", name, timeout=60)
        except RunnerError as exc:
            if "No such container" not in str(exc):
                log.warning("stopping %s: %s", name, exc)

    async def leftovers(self) -> list[str]:
        out = await self._docker(
            "ps", "-aq", "--filter", f"label={LABEL}", "--format", "{{.Names}}"
        )
        return [line for line in out.splitlines() if line]

    async def gateway_address(self) -> str | None:
        try:
            out = await self._docker(
                "network",
                "inspect",
                "-f",
                "{{(index .IPAM.Config 0).Gateway}}",
                self.s.sessions_network,
            )
        except RunnerError as exc:
            log.warning("cannot inspect network %s: %s", self.s.sessions_network, exc)
            return None
        return out or None
