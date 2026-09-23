import json
import re

from typer.testing import CliRunner

from nanomuse import __version__
from nanomuse import config as config_module
from nanomuse.cli import app

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain(output: str) -> str:
    """CI terminals get colour codes from rich; compare on the text."""
    return _ANSI.sub("", output)


def test_version_flag_and_command_agree():
    for args in (["--version"], ["-V"], ["version"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert plain(result.output).strip() == f"nanomuse {__version__}"


def test_help_lists_the_version_flag():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in plain(result.output)


def test_doctor_reports_the_setup_without_calling_the_model(tmp_path, monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "NANOMUSE_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no ./config/config.toml here…
    monkeypatch.setattr(config_module, "DEFAULT_DATA_DIR", tmp_path / "home")  # …nor ~/.nanomuse/
    monkeypatch.setenv("NANOMUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NANOMUSE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("NANOMUSE_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("NANOMUSE_LLM_MODEL", "qwen3:8b")
    (tmp_path / "ws").mkdir()

    # a local model needs no key: everything checks out
    result = runner.invoke(app, ["doctor", "--no-model"])
    out = plain(result.output)
    assert result.exit_code == 0, out
    assert "qwen3:8b" in out and "all good" in out
    assert "reminders" in out and "shell" in out  # the tool list
    assert "skipped" in out
    assert "web search: DuckDuckGo (no key needed)" in out

    # a search provider without what it needs is a problem, said plainly
    monkeypatch.setenv("NANOMUSE_SEARCH_PROVIDER", "brave")
    out = plain(runner.invoke(app, ["doctor", "--no-model"]).output)
    assert "web search: Brave Search (no key) · searches fall back to DuckDuckGo" in out
    assert "connectors.search.provider = brave, but it is not configured" in out
    monkeypatch.delenv("NANOMUSE_SEARCH_PROVIDER")

    # a hosted endpoint without a key is a problem worth exit code 1
    monkeypatch.setenv("NANOMUSE_LLM_BASE_URL", "https://api.deepseek.com")
    result = runner.invoke(app, ["doctor", "--no-model"])
    out = plain(result.output)
    assert result.exit_code == 1, out
    assert "no usable API key" in out


def test_triggers_commands(tmp_path, monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "NANOMUSE_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "DEFAULT_DATA_DIR", tmp_path / "home")
    monkeypatch.setenv("NANOMUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NANOMUSE_WORKSPACE", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()

    assert "no triggers" in plain(runner.invoke(app, ["triggers", "list"]).output)
    # mail and event triggers need their connector
    result = runner.invoke(app, ["triggers", "add", "mail", "summarise it", "--match", "landlord"])
    assert result.exit_code == 1 and "email connector" in plain(result.output)
    result = runner.invoke(app, ["triggers", "add", "event", "brief me", "--match", "review"])
    assert result.exit_code == 1 and "calendar" in plain(result.output)
    result = runner.invoke(app, ["triggers", "add", "sms", "x"])
    assert result.exit_code == 1 and "kind must be" in plain(result.output)

    result = runner.invoke(
        app, ["triggers", "add", "hook", "check that the site is up", "--match", "deploy"]
    )
    out = plain(result.output)
    assert result.exit_code == 0, out
    assert "when webhook “deploy” → check that the site is up" in out
    assert "POST http://" in out and "/api/hooks/t_" in out and "?key=" in out
    trigger_id = re.search(r"\[(t_[0-9a-f]+)\]", out).group(1)

    out = plain(runner.invoke(app, ["triggers", "list"]).output)
    assert (
        trigger_id in out and "webhook “deploy”" in out and f"/api/hooks/{trigger_id}?key=" in out
    )
    out = plain(runner.invoke(app, ["doctor", "--no-model"]).output)
    assert "triggers: 1 active · hook: 1" in out

    result = runner.invoke(app, ["triggers", "cancel", trigger_id])
    assert result.exit_code == 0 and "(cancelled" in plain(result.output)
    assert runner.invoke(app, ["triggers", "cancel", trigger_id]).exit_code == 1
    assert "no triggers" in plain(runner.invoke(app, ["triggers", "list"]).output)
    assert trigger_id in plain(runner.invoke(app, ["triggers", "list", "--all"]).output)


def test_phone_trace_commands(tmp_path, monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "NANOMUSE_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "DEFAULT_DATA_DIR", tmp_path / "home")
    monkeypatch.setenv("NANOMUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NANOMUSE_WORKSPACE", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()

    assert "No phone traces yet" in plain(runner.invoke(app, ["phone", "traces"]).output)
    assert runner.invoke(app, ["phone", "trace", "pt-nope"]).exit_code == 1

    traces = tmp_path / "data" / "phone-traces"
    traces.mkdir(parents=True)
    records = [
        {
            "kind": "task",
            "id": "pt-1",
            "goal": "查明天的高铁",
            "app": "铁路12306",
            "t": 1758600000.0,
        },
        {
            "kind": "step",
            "step": 1,
            "t": 1758600002.0,
            "latency_ms": 1200,
            "screen": {"app": "railway12306", "app_name": "铁路12306", "width": 360, "height": 800},
            "thought": "先点出发地",
            "action": "点击「上海」。",
            "tool_call": {
                "name": "mobile_use",
                "arguments": {"action": "click", "coordinate": [0.1, 0.2]},
            },
            "params": {"action": "tap", "x": 36, "y": 160, "label": "点击「上海」。"},
        },
        {
            "kind": "end",
            "status": "done",
            "message": "G1 06:30",
            "steps": 1,
            "seconds": 3.1,
            "t": 1758600004.0,
        },
    ]
    (traces / "pt-1.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )

    out = plain(runner.invoke(app, ["phone", "traces"]).output)
    assert "pt-1" in out and "done" in out and "查明天的高铁" in out

    out = plain(runner.invoke(app, ["phone", "trace", "pt-1"]).output)
    assert "点击「上海」。" in out and '"x": 36' in out and "G1 06:30" in out

    page = tmp_path / "trace.html"
    assert runner.invoke(app, ["phone", "trace", "pt-1", "-o", str(page)]).exit_code == 0
    html = page.read_text(encoding="utf-8")
    assert "查明天的高铁" in html and "点击「上海」。" in html and "G1 06:30" in html
