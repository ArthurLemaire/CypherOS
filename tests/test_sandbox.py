"""The sandbox: what the box is built from, and — where bubblewrap works — what a
command can and cannot reach from inside it."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

from openmuse.config import SandboxSettings, Settings
from openmuse.sandbox import Sandbox, interpreter_roots, needs_network
from openmuse.schema import RiskLevel
from openmuse.tools.shell import PythonExecute, Shell, programs_of


def test_needs_network_by_program_or_url():
    assert needs_network("curl https://example.com", programs_of("curl https://example.com"))
    assert needs_network("git pull", programs_of("git pull"))
    assert needs_network("pip install httpx", programs_of("pip install httpx"))
    assert needs_network("python3 fetch.py https://x.io/data", "python3")
    assert not needs_network("ls -la && wc -l notes.md", programs_of("ls -la && wc -l notes.md"))
    assert not needs_network("python3 sum.py", "python3")
    # a bare hostname counts too — a script can take it as an argument
    assert needs_network("python3 fetch.py api.example.com", "python3")


def test_off_and_missing_are_not_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    box = Sandbox(SandboxSettings(mode="off"), workspace=tmp_path)
    assert not box.active and box.reason == "sandbox.mode = off"
    assert "no sandbox" in box.describe()
    monkeypatch.setattr("openmuse.sandbox.shutil.which", lambda _name: None)
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Linux")
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    assert not box.active and "not installed" in box.reason
    assert box.status.startswith("off — ")
    monkeypatch.setenv("OPENMUSE_IN_CONTAINER", "1")
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    assert not box.active and box.reason == "in a container, which is the box"
    monkeypatch.delenv("OPENMUSE_IN_CONTAINER")
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Darwin")
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    assert not box.active and "Linux-only" in box.reason
    with pytest.raises(ValueError):
        Sandbox(SandboxSettings(mode="jail"), workspace=tmp_path)


def test_wrap_builds_the_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The argv, without running it: what is writable, what is hidden, what is masked."""
    monkeypatch.setattr("openmuse.sandbox.shutil.which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Linux")
    ws = tmp_path / "ws"
    extra = tmp_path / "extra"
    data = ws / ".openmuse"  # a data dir inside the workspace must be masked
    box = Sandbox(SandboxSettings(), workspace=ws, extra_roots=[extra], data_dir=data, probe=False)
    assert box.active
    argv = box.wrap(["/bin/sh", "-c", "echo hi"], network=False, cwd=ws)
    assert argv[0] == "/usr/bin/bwrap" and argv[-3:] == ["/bin/sh", "-c", "echo hi"]
    joined = " ".join(argv)
    assert "--unshare-net" in argv and "--unshare-pid" in argv and "--die-with-parent" in argv
    assert f"--bind-try {ws} {ws}" in joined and f"--bind-try {extra} {extra}" in joined
    assert f"--tmpfs {data}" in joined  # the vault and sessions are not readable from inside
    assert "--ro-bind-try /usr /usr" in joined and "--ro-bind-try /etc /etc" in joined
    assert "--tmpfs /tmp" in joined and "--setenv HOME /tmp/home" in joined
    assert "--setenv OPENMUSE_SANDBOX bwrap" in joined and f"--chdir {ws}" in joined
    # the home directory is not bound (only interpreter directories may reach into it)
    home = str(Path.home())
    bound = [argv[i + 1] for i, a in enumerate(argv) if a in ("--bind-try", "--ro-bind-try")]
    assert home not in bound and all(
        r in map(str, interpreter_roots()) for r in bound if r.startswith(home + "/")
    )
    for root in interpreter_roots():
        assert f"--ro-bind-try {root} {root}" in joined
    # with the network, no --unshare-net; everything else the same
    with_net = box.wrap(["/bin/true"], network=True, cwd=ws)
    assert "--unshare-net" not in with_net
    assert len(with_net) == len(argv) - 1 - 2  # minus the flag and the two extra argv words
    # a relative workspace (the config default is "./workspace") is made absolute: bwrap
    # changes directory after pivoting to the new root, where "workspace" does not exist
    monkeypatch.chdir(tmp_path)
    relative = box.wrap(["/bin/true"], network=True, cwd=Path("ws"))
    assert relative[relative.index("--chdir") + 1] == str(ws)


def test_data_dir_outside_the_roots_needs_no_mask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("openmuse.sandbox.shutil.which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Linux")
    box = Sandbox(
        SandboxSettings(), workspace=tmp_path / "ws", data_dir=tmp_path / "data", probe=False
    )
    joined = " ".join(box.wrap(["/bin/true"], network=False, cwd=tmp_path / "ws"))
    assert f"--tmpfs {tmp_path / 'data'}" not in joined and str(tmp_path / "data") not in joined


def test_settings_default_and_shell_assessment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert Settings().sandbox.mode == "auto"
    # without a box every shell command may reach the network: egress, as before
    plain = Shell(workspace=tmp_path, sandbox=None)
    assert plain.assess({"command": "ls"}).egress
    # with one, only commands that say so
    monkeypatch.setattr("openmuse.sandbox.shutil.which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Linux")
    box = Sandbox(SandboxSettings(), workspace=tmp_path, probe=False)
    shell = Shell(workspace=tmp_path, sandbox=box)
    assert not shell.assess({"command": "ls -la"}).egress
    assert shell.assess({"command": "curl https://example.com"}).egress
    assert shell.assess({"command": "python3 fetch.py", "network": True}).egress
    assert shell.assess({"command": "python3 fetch.py", "network": True}).summary.startswith(
        "shell (network): python3"
    )
    assert shell.assess({"command": "ls -la"}).summary == "shell: ls -la"
    assert plain.assess({"command": "curl x"}).summary == "shell: curl x"  # unboxed: no note
    assert shell.assess({"command": "ls -la"}).risk == RiskLevel.SENSITIVE  # still a shell


def test_a_box_that_cannot_take_the_network_away(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ubuntu 24.04 with the userns restriction and no AppArmor profile for bwrap: the
    namespace is made, its loopback cannot be configured. The box stays on for the file
    system; commands are judged as reaching the network, like without a box."""
    import subprocess

    monkeypatch.setattr("openmuse.sandbox.shutil.which", lambda _name: "/usr/bin/bwrap")
    monkeypatch.setattr("openmuse.sandbox.platform.system", lambda: "Linux")
    calls: list[list[str]] = []

    def fake_run(argv, **_kw):
        calls.append(argv)
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout="bubblewrap 0.9.0\n", stderr="")
        if "--unshare-net" in argv:
            err = "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n"
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=err)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("openmuse.sandbox.subprocess.run", fake_run)
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    assert box.active and not box.blocks_network and box.reason == ""
    assert len(calls) == 3  # version, with --unshare-net (refused), without (works)
    assert box.status.startswith("bubblewrap 0.9.0 — the network is not blocked")
    assert "cannot block it" in box.describe()
    # no command asks for --unshare-net any more …
    assert "--unshare-net" not in box.wrap(["/bin/true"], network=False, cwd=tmp_path)
    # … and the shell tool judges commands as it does without a box: all may reach out
    shell = Shell(workspace=tmp_path, sandbox=box)
    assert shell.assess({"command": "ls -la"}).egress
    assert shell.assess({"command": "ls -la"}).summary == "shell: ls -la"

    # any other failure: no box — and, under Ubuntu's restriction, a pointer to the profile
    def fake_run_fail(argv, **_kw):
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout="bubblewrap 0.9.0\n", stderr="")
        err = "bwrap: setting up uid map: Permission denied\n"
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=err)

    monkeypatch.setattr("openmuse.sandbox.subprocess.run", fake_run_fail)
    monkeypatch.setattr("openmuse.sandbox.userns_restricted", lambda: False)
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    assert not box.active and box.reason.endswith("(bwrap: setting up uid map: Permission denied)")
    monkeypatch.setattr("openmuse.sandbox.userns_restricted", lambda: True)
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    assert not box.active and "apparmor_restrict_unprivileged_userns=1" in box.reason
    assert box.reason.endswith("see docs/sentinel.md → The sandbox")


def _probe() -> Sandbox | None:
    if platform.system() != "Linux":
        return None
    box = Sandbox(SandboxSettings(), workspace=Path.cwd())
    return box if box.active else None


_BOX = _probe()
needs_bwrap = pytest.mark.skipif(_BOX is None, reason="bubblewrap does not work here")
needs_net_box = pytest.mark.skipif(
    _BOX is None or not _BOX.blocks_network, reason="bubblewrap cannot block the network here"
)


@needs_bwrap
async def test_boxed_shell_sees_only_the_workspace(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("outside")
    box = Sandbox(SandboxSettings(), workspace=ws, data_dir=tmp_path / "data")
    assert box.active and box.status.startswith("bubblewrap")
    shell = Shell(workspace=ws, sandbox=box)
    r = await shell.execute(command="pwd && echo made > made.txt && cat made.txt")
    assert r.ok and r.output.startswith(f"{ws}\nmade")
    assert (ws / "made.txt").read_text() == "made\n"  # the workspace really is bound
    # the parent (and with it the rest of the machine) is not there
    r = await shell.execute(command=f"cat {tmp_path / 'secret.txt'}")
    assert not r.ok and "outside" not in r.output and "secret.txt" in r.output
    r = await shell.execute(
        command="ls $HOME/.ssh 2>&1; echo HOME=$HOME; echo BOX=$OPENMUSE_SANDBOX"
    )
    assert r.ok and "HOME=/tmp/home" in r.output and "BOX=bwrap" in r.output
    # system paths are read-only
    r = await shell.execute(command="touch /usr/owned 2>&1 || echo READONLY")
    assert r.ok and "READONLY" in r.output
    # /tmp is private: a file made there is gone by the next command
    r = await shell.execute(command="echo x > /tmp/t && cat /tmp/t")
    assert r.ok and r.output.startswith("x")
    r = await shell.execute(command="cat /tmp/t 2>&1 || echo GONE")
    assert r.ok and "GONE" in r.output


@needs_net_box
async def test_boxed_commands_have_no_network_unless_they_say_so(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    box = Sandbox(SandboxSettings(), workspace=ws)
    shell = Shell(workspace=ws, sandbox=box)
    # `ip`/`cat /proc/net/dev` show the interfaces of the namespace: only lo without network
    r = await shell.execute(command="cat /proc/net/dev | tail -n +3 | cut -d: -f1 | tr -d ' '")
    assert r.ok and r.output.split("\n[exit")[0].strip().splitlines() == ["lo"]
    r = await shell.execute(command="cat /proc/net/dev | tail -n +3 | wc -l", network=True)
    assert r.ok and int(r.output.split()[0]) >= 1  # the host's interfaces (at least lo)
    # a python script gets the network only when its code reaches for it
    py = PythonExecute(workspace=ws, sandbox=box)
    probe = "print(sorted(l.split(':')[0].strip() for l in open('/proc/net/dev').readlines()[2:]))"
    r = await py.execute(code=probe)
    assert r.ok and r.output.startswith("['lo']")
    r = await py.execute(code="import socket\n" + probe)
    assert r.ok and r.output.startswith("[") and r.output.split("\n")[0] != "['lo']"
    # and it runs with this interpreter and its packages, from the workspace
    r = await py.execute(code="import httpx, os, sys; print(os.getcwd(), sys.version_info[:2])")
    assert r.ok and r.output.startswith(f"{ws} {tuple(sys.version_info[:2])}")


@needs_net_box
async def test_no_network_failure_is_explained(tmp_path: Path):
    box = Sandbox(SandboxSettings(), workspace=tmp_path)
    py = PythonExecute(workspace=tmp_path, sandbox=box)
    # the code does not import a network module, so the box has no network — a script
    # that then resolves a name fails, and the result says why
    code = (
        "import os\n"
        "os.system('getent hosts example.com >/dev/null 2>&1 || "
        '(echo "Temporary failure in name resolution" >&2; exit 2)\')\n'
        "raise SystemExit(2)"
    )
    r = await py.execute(code=code)
    # os.system starts a process: that is "processes" reach, so this one *does* get the
    # network; a plain resolver failure without it is what the note is for
    assert r.error == "exit code 2"
    shell = Shell(workspace=tmp_path, sandbox=box)
    r = await shell.execute(command='echo "Temporary failure in name resolution" >&2; exit 6')
    assert r.error == "exit code 6" and "ran without network access" in r.output
    r = await shell.execute(
        command='echo "Temporary failure in name resolution" >&2; exit 6', network=True
    )
    assert r.error == "exit code 6" and "ran without network access" not in r.output
