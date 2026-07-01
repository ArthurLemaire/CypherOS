from typer.testing import CliRunner

from openmuse import __version__
from openmuse import config as config_module
from openmuse.cli import app

runner = CliRunner()


def test_version_flag_and_command_agree():
    for args in (["--version"], ["-V"], ["version"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"openmuse {__version__}"


def test_no_arguments_prints_help():
    result = runner.invoke(app, [])
    assert "Usage" in result.output and "--version" in result.output


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
    assert result.exit_code == 0, result.output
    assert "qwen3:8b" in result.output and "all good" in result.output
    assert "reminders" in result.output and "shell" in result.output  # the tool list
    assert "skipped" in result.output

    # a hosted endpoint without a key is a problem worth exit code 1
    monkeypatch.setenv("OPENMUSE_LLM_BASE_URL", "https://api.deepseek.com")
    result = runner.invoke(app, ["doctor", "--no-model"])
    assert result.exit_code == 1, result.output
    assert "no usable API key" in result.output
