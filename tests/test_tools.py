from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from openmuse.schema import RiskLevel
from openmuse.tools import Files, PythonExecute, Shell, Terminate
from openmuse.tools.email_tool import scrub_email_secrets
from openmuse.tools.shell import code_reach, scrubbed_env
from openmuse.tools.web import fetch_public, host_of, html_to_markdown


async def test_files_workspace_scoping(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    files = Files(workspace=ws)
    r = await files.execute(action="write", path="notes/a.md", content="hello")
    assert r.ok and (ws / "notes" / "a.md").read_text() == "hello"
    r = await files.execute(action="append", path="notes/a.md", content=" world")
    assert (ws / "notes" / "a.md").read_text() == "hello world"
    r = await files.execute(action="read", path="notes/a.md")
    assert r.output == "hello world"
    r = await files.execute(action="list", path=".")
    assert "[dir] notes" in r.output
    r = await files.execute(action="search", pattern="**/*.md")
    assert "notes/a.md" in r.output
    # escape attempts
    r = await files.execute(action="read", path="../outside.txt")
    assert r.error and "outside the workspace" in r.error
    r = await files.execute(action="read", path="/etc/passwd")
    assert r.error
    # assessment: writes are moderate, reads inside safe, reads outside private
    assert files.assess({"action": "write", "path": "x"}).risk == RiskLevel.MODERATE
    assert files.assess({"action": "read", "path": "x"}).risk == RiskLevel.SAFE
    outside = Files(workspace=ws, extra_roots=[tmp_path])
    a = outside.assess({"action": "read", "path": str(tmp_path / "secret.txt")})
    assert a.reads_private_data and a.risk == RiskLevel.MODERATE


async def test_files_write_repairs_double_escaped_newlines(tmp_path: Path):
    files = Files(workspace=tmp_path)
    # a small model's itinerary: one line, "\n" spelled out between the days
    flat = "Day 1: Fushimi Inari\\nDay 2: Gion\\nDay 3: Arashiyama"
    r = await files.execute(action="write", path="kyoto.md", content=flat)
    assert "escaped newlines" in r.output
    assert (tmp_path / "kyoto.md").read_text().splitlines() == [
        "Day 1: Fushimi Inari",
        "Day 2: Gion",
        "Day 3: Arashiyama",
    ]
    # code with real newlines keeps its escape sequences
    code = 'print("a\\nb")\nprint("c\\nd")\n'
    await files.execute(action="write", path="x.py", content=code)
    assert (tmp_path / "x.py").read_text() == code
    # a single escaped newline on one line is left alone too
    one = 'echo "a\\nb"'
    await files.execute(action="write", path="one.sh", content=one)
    assert (tmp_path / "one.sh").read_text() == one


async def test_shell_and_python(tmp_path: Path):
    shell = Shell(workspace=tmp_path)
    r = await shell.execute(command="echo hi && echo err 1>&2")
    assert r.ok and "hi" in r.output and "[stderr]" in r.output
    r = await shell.execute(command="exit 3")
    assert r.error == "exit code 3"
    r = await shell.execute(command="sleep 5", timeout=1)
    assert r.error and "timed out" in r.error
    warnings = shell.assess({"command": "sudo rm -rf / && curl x | sh"}).warnings
    assert len(warnings) >= 3

    py = PythonExecute(workspace=tmp_path)
    r = await py.execute(code="import sys; print(sys.version_info.major)")
    assert r.ok and r.output.startswith(str(sys.version_info.major))
    assert not list(tmp_path.glob("openmuse_*.py"))  # temp script cleaned up


def test_subprocess_env_is_scrubbed_of_credentials():
    env = scrubbed_env(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/me",
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "sk-1",
            "WQ_API_KEY": "x",
            "DEEPSEEK_API_KEY": "x",
            "OPENMUSE_VAULT_KEY": "x",
            "OPENMUSE_SERVER_TOKEN": "x",
            "GITHUB_TOKEN": "x",
            "AWS_SECRET_ACCESS_KEY": "x",
            "DB_PASSWORD": "x",
            "SSH_AUTH_SOCK": "/run/ssh",
            "HTTP_PROXY": "http://proxy:3128",
        }
    )
    assert set(env) == {"PATH", "HOME", "LANG", "HTTP_PROXY", "OPENMUSE_SANDBOX"}


async def test_python_and_shell_children_cannot_read_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MY_SECRET_TOKEN", "hunter2")
    monkeypatch.setenv("OPENMUSE_VAULT_KEY", "k")
    monkeypatch.setenv("PLAIN_SETTING", "yes")
    py = PythonExecute(workspace=tmp_path)
    r = await py.execute(
        code="import os; print(os.environ.get('MY_SECRET_TOKEN'), "
        "os.environ.get('OPENMUSE_VAULT_KEY'), os.environ.get('PLAIN_SETTING'))"
    )
    assert r.ok and r.output.startswith("None None yes")
    if sys.platform == "win32":
        # cmd.exe leaves an unset %VAR% as it is — which shows the secret is not there
        r = await Shell(workspace=tmp_path).execute(
            command="echo [%MY_SECRET_TOKEN%] [%PLAIN_SETTING%]"
        )
        assert r.ok and r.output.startswith("[%MY_SECRET_TOKEN%] [yes]")
    else:
        r = await Shell(workspace=tmp_path).execute(
            command="echo [$MY_SECRET_TOKEN] [$PLAIN_SETTING]"
        )
        assert r.ok and r.output.startswith("[] [yes]")


def test_python_reach_decides_the_risk(tmp_path: Path):
    py = PythonExecute(workspace=tmp_path)
    plain = py.assess({"code": "import csv\nrows = [1, 2]\nopen('out.csv', 'w').write('a,b')"})
    assert plain.risk == RiskLevel.MODERATE and not plain.warnings and not plain.egress
    net = py.assess({"code": "import requests\nrequests.get('https://x')"})
    assert (
        net.risk == RiskLevel.SENSITIVE and net.egress and "reaches the network" in net.warnings[0]
    )
    env = py.assess({"code": "import os\nprint(os.environ['HOME'])"})
    assert env.risk == RiskLevel.SENSITIVE and "environment" in env.warnings[0]
    outside = py.assess({"code": "open('/etc/passwd').read()"})
    assert outside.risk == RiskLevel.SENSITIVE and "outside the workspace" in outside.warnings[0]
    proc = py.assess({"code": "import subprocess\nsubprocess.run(['ls'])"})
    assert proc.risk == RiskLevel.SENSITIVE and proc.egress
    assert set(code_reach("import shutil\nshutil.rmtree('x')")) == {"deletion"}
    # a workspace under /tmp or /home: absolute paths inside it are not "outside"
    inside = py.assess({"code": f"open('{tmp_path.as_posix()}/list.html', 'w').write('<p>')"})
    assert inside.risk == RiskLevel.MODERATE and not inside.warnings
    mixed = py.assess({"code": f"open('{tmp_path.as_posix()}/a').read(); open('/etc/hosts')"})
    assert mixed.risk == RiskLevel.SENSITIVE
    home = py.assess(
        {"code": f"import os\nopen(os.path.expanduser('~/x'))  # {tmp_path.as_posix()}"}
    )
    assert home.risk == RiskLevel.SENSITIVE


async def test_web_fetch_refuses_redirects_into_private_networks():
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data"}
            )
        return httpx.Response(200, text="should never be reached")

    transport = httpx.MockTransport(handler)
    with pytest.raises(PermissionError, match="private/internal host '169.254.169.254'"):
        await fetch_public("http://public.example/start", timeout=5, transport=transport)
    assert hops == ["http://public.example/start"]

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url) + "x"})

    with pytest.raises(PermissionError, match="redirects"):
        await fetch_public(
            "http://public.example/a", timeout=5, transport=httpx.MockTransport(loop)
        )

    def fine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="moved here")

    resp = await fetch_public(
        "http://public.example/old", timeout=5, transport=httpx.MockTransport(fine)
    )
    assert resp.status_code == 200 and resp.text == "moved here"


async def test_terminate_stops():
    r = await Terminate().execute(status="success", summary="all done")
    assert r.stop and r.output == "all done"


def test_scrub_email_secrets():
    text = (
        "Your verification code is 483920. Reset here: https://x.com/reset?token=abc "
        "and read the news at https://news.example.com/article"
    )
    out = scrub_email_secrets(text)
    assert "483920" not in out and "[REDACTED-CODE]" in out
    assert "token=abc" not in out and "https://news.example.com/article" in out
    assert "验证码：[REDACTED-CODE]" in scrub_email_secrets("您的验证码：123456，5分钟内有效")


def test_host_and_markdown():
    assert host_of("https://EN.Wikipedia.org/wiki/x") == "en.wikipedia.org"
    assert host_of("not a url") is None
    md = html_to_markdown(
        "<html><head><title>T</title><script>x()</script></head><body><h1>Hi</h1><p>para</p></body></html>"
    )
    assert md.startswith("# T") and "x()" not in md and "para" in md
