from typer.testing import CliRunner

from openmuse import __version__
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
