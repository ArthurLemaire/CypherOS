"""A small box for every command the agent runs.

Muse gives each user's agent a VM of its own. OpenMuse runs on your machine, so the next
best thing is to give each ``shell`` and ``python_execute`` call its own namespace with
`bubblewrap <https://github.com/containers/bubblewrap>`_ (Linux, unprivileged):

- the workspace (and ``agent.extra_roots``) are the only writable places;
- ``/usr``, ``/etc``, ``/opt`` … are read-only; the Python the agent runs with is visible;
- your home directory does not exist inside — and with it the vault, the data
  directory, ssh keys, cloud credentials, browser profiles; ``/tmp`` is private;
- there is no network unless the call was assessed as needing it (``curl``, ``pip``,
  ``git`` …, a script that imports ``requests``), which is also what makes the Sentinel
  treat it as egress.

``sandbox.mode`` is ``auto`` (use bubblewrap when it works here), ``bwrap`` (insist) or
``off``. Without it — macOS, Windows, a Docker container without user namespaces — the
commands run as before: scrubbed environment, workspace as cwd, and the container or the
machine is the box. On a kernel that leaves unprivileged user namespaces without
capabilities (Ubuntu 24.04's ``apparmor_restrict_unprivileged_userns`` when no AppArmor
profile covers ``bwrap``) the box works but cannot take the network away; then every
command is judged as it is without a box: it may reach the network.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from openmuse.config import SandboxSettings
from openmuse.logger import logger

# Programs whose job is the network. A command running one of these gets the network
# and counts as egress for the Sentinel; everything else runs without.
NETWORK_PROGRAMS = frozenset(
    {
        "apt",
        "apt-get",
        "brew",
        "cargo",
        "conda",
        "curl",
        "dig",
        "docker",
        "gem",
        "gh",
        "git",
        "go",
        "host",
        "nc",
        "ncat",
        "nslookup",
        "npm",
        "npx",
        "nmap",
        "ping",
        "pip",
        "pip3",
        "pipx",
        "pnpm",
        "poetry",
        "rsync",
        "scp",
        "sftp",
        "ssh",
        "telnet",
        "traceroute",
        "uv",
        "uvx",
        "wget",
        "yarn",
    }
)
_URL = re.compile(r"https?://|\bwww\.|\b[a-z0-9-]+\.(com|org|net|io|dev|cn|ai)\b", re.IGNORECASE)


def needs_network(command: str, programs: str | None) -> bool:
    """Does this shell command reach the network? By the programs it runs, or a URL in it."""
    names = set(programs.split(",")) if programs else set()
    return bool(names & NETWORK_PROGRAMS) or bool(_URL.search(command))


def userns_restricted() -> bool:
    """Ubuntu's AppArmor restriction on unprivileged user namespaces, which leaves one made
    by a program without a profile with no capabilities."""
    try:
        return (
            Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text().strip()
            == "1"
        )
    except OSError:
        return False


def in_container() -> bool:
    """Inside Docker / Podman? (``/.dockerenv``, ``/run/.containerenv``, or the image's own
    marker.)"""
    return (
        os.environ.get("OPENMUSE_IN_CONTAINER") == "1"
        or Path("/.dockerenv").exists()
        or Path("/run/.containerenv").exists()
    )


def interpreter_roots() -> list[Path]:
    """The directories that hold this Python: ``sys.prefix``, ``sys.base_prefix`` and, for
    an executable that is a chain of symlinks (a venv → a uv install → a patch version),
    the prefix each link points into — as written, since that is the path the next link
    names. Paths under ``/usr`` or ``/opt`` are already read-only in the box."""
    roots: list[Path] = []

    def add(p: Path) -> None:
        if str(p).startswith(("/usr/", "/opt/")) or p in (Path("/usr"), Path("/opt"), Path("/")):
            return
        if p not in roots:
            roots.append(p)

    add(Path(sys.prefix))
    add(Path(sys.base_prefix))
    add(Path(sys.base_prefix).resolve())
    link = Path(sys.executable)
    for _ in range(10):
        if not link.is_symlink():
            break
        target = Path(os.readlink(link))
        if not target.is_absolute():
            target = link.parent / target
        add(target.parent.parent)  # <prefix>/bin/python → <prefix>
        link = target
    return roots


class Sandbox:
    def __init__(
        self,
        settings: SandboxSettings,
        workspace: Path,
        extra_roots: list[Path] | None = None,
        data_dir: Path | None = None,
        probe: bool = True,
        ro_roots: list[Path] | None = None,
    ):
        self.settings = settings
        self.workspace = workspace.resolve()
        self.extra_roots = [p.resolve() for p in (extra_roots or [])]
        # read-only inside the box (skills' scripts and references); bound after the
        # data-dir mask so a folder under the data dir is still there
        self.ro_roots = [p.resolve() for p in (ro_roots or [])]
        self.data_dir = data_dir.resolve() if data_dir else None
        self.bwrap = shutil.which("bwrap")
        self.version = ""
        self.reason = ""
        self.active = False
        # False where the box works but cannot take the network away: a kernel that leaves
        # an unprivileged user namespace without capabilities (Ubuntu 24.04's
        # apparmor_restrict_unprivileged_userns when no AppArmor profile covers bwrap) makes
        # bubblewrap fail at setting up the loopback interface of a new network namespace.
        self.blocks_network = True
        if settings.mode not in ("auto", "bwrap", "off"):
            raise ValueError("sandbox.mode must be auto, bwrap or off")
        if settings.mode == "off":
            self.reason = "sandbox.mode = off"
        elif platform.system() != "Linux":
            self.reason = f"bubblewrap is Linux-only (this is {platform.system()})"
        elif not self.bwrap and in_container():
            # the image does not ship bubblewrap: the container is the box
            self.reason = "in a container, which is the box"
        elif not self.bwrap:
            self.reason = (
                "bubblewrap is not installed (apt install bubblewrap / dnf install bubblewrap)"
            )
        elif probe:
            self.active, self.reason = self._probe()
        else:
            self.active = True
        if not self.active and settings.mode == "bwrap":
            logger.error("sandbox.mode = bwrap but the sandbox does not work: {}", self.reason)
        elif not self.active:
            logger.info("commands run unboxed: {}", self.reason)

    def _probe(self) -> tuple[bool, str]:
        """Can bubblewrap make a namespace here? (Not in most Docker containers.) And can it
        take the network away, or only the file system?"""
        assert self.bwrap
        try:
            version = subprocess.run(
                [self.bwrap, "--version"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            self.version = version.replace("bubblewrap", "").strip()
            run = self._try(network=False)
            err = self._last_line(run)
            if run.returncode != 0 and "loopback" in err:
                # the namespace was made; only configuring its loopback interface was refused
                run = self._try(network=True)
                if run.returncode == 0:
                    self.blocks_network = False
                    return True, ""
                err = self._last_line(run)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"bubblewrap failed to start: {exc}"
        if run.returncode != 0:
            reason = "bubblewrap cannot create a namespace here" + (f" ({err})" if err else "")
            if userns_restricted():
                reason += (
                    " — kernel.apparmor_restrict_unprivileged_userns=1 and no AppArmor profile "
                    "covers bwrap; see docs/sentinel.md → The sandbox"
                )
            return False, reason
        return True, ""

    def _try(self, network: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.wrap(["/bin/true"], network=network, cwd=Path("/")),
            capture_output=True,
            text=True,
            timeout=10,
        )

    @staticmethod
    def _last_line(run: subprocess.CompletedProcess[str]) -> str:
        lines = (run.stderr or run.stdout).strip().splitlines()
        return lines[-1] if lines else ""

    NO_NETWORK_BLOCKING = (
        "the network is not blocked: this kernel leaves unprivileged user namespaces "
        "without capabilities (Ubuntu's apparmor_restrict_unprivileged_userns with no "
        "AppArmor profile for bwrap), so a network namespace cannot be set up"
    )

    @property
    def status(self) -> str:
        if self.active and self.blocks_network:
            return f"bubblewrap {self.version}".strip()
        if self.active:
            return f"bubblewrap {self.version}".strip() + f" — {self.NO_NETWORK_BLOCKING}"
        return f"off — {self.reason}"

    def describe(self) -> str:
        """One line for the model and the app."""
        if not self.active:
            return "Commands run in the workspace with a scrubbed environment (no sandbox)."
        if not self.blocks_network:
            return (
                "Commands run in a sandbox: only the workspace is writable, the home directory "
                "is not there, /tmp is private. The network is reachable (this system cannot "
                "block it), so a command counts as reaching it when it looks like it does."
            )
        return (
            "Commands run in a sandbox: only the workspace is writable, the home directory "
            "is not there, /tmp is private, and there is no network unless the command needs it."
        )

    # ------------------------------------------------------------------ wrapping
    def wrap(self, argv: list[str], network: bool, cwd: Path) -> list[str]:
        """The ``bwrap`` command line that runs ``argv`` boxed. Call only when active
        (the probe uses it too)."""
        assert self.bwrap
        args = [
            self.bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-user-try",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup-try",
        ]
        if not network and self.blocks_network:
            args.append("--unshare-net")
        for path in ("/usr", "/etc", "/opt", "/var", "/snap", "/nix", "/run/systemd/resolve"):
            args += ["--ro-bind-try", path, path]
        # merged-/usr distributions have these as symlinks; the others have real directories
        for path in ("/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32"):
            if Path(path).is_symlink():
                args += ["--symlink", str(Path(path).resolve().relative_to("/")), path]
            elif Path(path).is_dir():
                args += ["--ro-bind", path, path]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        # hardware and device info, as Flatpak exposes it (nproc, psutil, torch read these)
        for path in ("/sys/block", "/sys/bus", "/sys/class", "/sys/dev", "/sys/devices"):
            args += ["--ro-bind-try", path, path]
        # the interpreter the agent runs with (a venv, a uv- or pyenv-managed Python) usually
        # lives outside /usr — often under the hidden home; only those directories come in
        for prefix in interpreter_roots():
            args += ["--ro-bind-try", str(prefix), str(prefix)]
        roots = [self.workspace, *self.extra_roots]
        for root in roots:
            args += ["--bind-try", str(root), str(root)]
        masked = self.data_dir and any(self.data_dir.is_relative_to(r) for r in roots)
        if masked:
            # the data dir (vault, sessions, tokens) inside a bound root: mask it
            args += ["--tmpfs", str(self.data_dir)]
        for root in self.ro_roots:
            under_mask = bool(masked and self.data_dir and root.is_relative_to(self.data_dir))
            if root.is_dir() and (under_mask or not any(root.is_relative_to(r) for r in roots)):
                args += ["--ro-bind-try", str(root), str(root)]
        home = "/tmp/home"
        args += [
            "--dir",
            home,
            "--setenv",
            "HOME",
            home,
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "OPENMUSE_SANDBOX",
            "bwrap",
            # bwrap changes directory after it has pivoted to the new root, so a relative
            # workspace ("./workspace" in the config) has to be made absolute out here
            "--chdir",
            str(Path(cwd).resolve()),
            "--",
            *argv,
        ]
        return args


__all__ = [
    "NETWORK_PROGRAMS",
    "Sandbox",
    "SandboxSettings",
    "in_container",
    "interpreter_roots",
    "needs_network",
    "userns_restricted",
]
