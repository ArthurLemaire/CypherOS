from __future__ import annotations

import sys
from pathlib import Path

from openmuse.schema import RiskLevel
from openmuse.tools import Files, PythonExecute, Shell, Terminate
from openmuse.tools.email_tool import scrub_email_secrets
from openmuse.tools.web import host_of, html_to_markdown


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
