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

    # a hosted endpoint without a key is a problem worth exit code 1
    monkeypatch.setenv("OPENMUSE_LLM_BASE_URL", "https://api.deepseek.com")
    result = runner.invoke(app, ["doctor", "--no-model"])
    out = plain(result.output)
    assert result.exit_code == 1, out
    assert "no usable API key" in out
