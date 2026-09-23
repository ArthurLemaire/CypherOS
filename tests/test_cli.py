import re

from typer.testing import CliRunner

from openmuse import __version__
from openmuse import config as config_module
from openmuse.cli import app

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain(output: str) -> str:
    """CI terminals get colour codes from rich; compare on the text."""
    return _ANSI.sub("", output)


def test_version_flag_and_command_agree():
    for args in (["--version"], ["-V"], ["version"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert plain(result.output).strip() == f"openmuse {__version__}"


def test_help_lists_the_version_flag():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in plain(result.output)


def test_doctor_reports_the_setup_without_calling_the_model(tmp_path, monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENMUSE_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no ./config/config.toml here…
    monkeypatch.setattr(config_module, "DEFAULT_DATA_DIR", tmp_path / "home")  # …nor ~/.openmuse/
    monkeypatch.setenv("OPENMUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENMUSE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("OPENMUSE_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("OPENMUSE_LLM_MODEL", "qwen3:8b")
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
    monkeypatch.setenv("OPENMUSE_SEARCH_PROVIDER", "brave")
    out = plain(runner.invoke(app, ["doctor", "--no-model"]).output)
    assert "web search: Brave Search (no key) · searches fall back to DuckDuckGo" in out
    assert "connectors.search.provider = brave, but it is not configured" in out
    monkeypatch.delenv("OPENMUSE_SEARCH_PROVIDER")

    # a hosted endpoint without a key is a problem worth exit code 1
    monkeypatch.setenv("OPENMUSE_LLM_BASE_URL", "https://api.deepseek.com")
    result = runner.invoke(app, ["doctor", "--no-model"])
    out = plain(result.output)
    assert result.exit_code == 1, out
    assert "no usable API key" in out


def test_triggers_commands(tmp_path, monkeypatch):
    for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENMUSE_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_module, "DEFAULT_DATA_DIR", tmp_path / "home")
    monkeypatch.setenv("OPENMUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENMUSE_WORKSPACE", str(tmp_path / "ws"))
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
