from __future__ import annotations

import pytest

from dots.tools.base import ToolRegistry
from dots.tools.builtin import NoteTool
from dots.tools.shell import ShellTool


async def test_note_requires_text() -> None:
    note = NoteTool()
    assert (await note.run(text="hi")).ok
    assert not (await note.run()).ok


def test_registry_rejects_duplicates() -> None:
    reg = ToolRegistry([NoteTool()])
    with pytest.raises(ValueError):
        reg.register(NoteTool())


def test_registry_unknown_tool_message() -> None:
    reg = ToolRegistry([NoteTool()])
    with pytest.raises(KeyError):
        reg.get("nope")
    assert "note" in reg.names()


async def test_shell_blocks_disallowed_command() -> None:
    sh = ShellTool()
    result = await sh.run(command="rm -rf /")
    assert not result.ok
    assert "not allowed" in (result.error or "")


async def test_shell_runs_allowed_command() -> None:
    sh = ShellTool(allow={"echo"})
    result = await sh.run(command="echo hello")
    assert result.ok
    assert "hello" in str(result.output)
