from __future__ import annotations

import sys
from pathlib import Path

from openmuse.config import MCPServerSettings
from openmuse.schema import RiskLevel
from openmuse.tools import MCPManager, ToolCollection

SERVER = Path(__file__).with_name("mcp_echo_server.py")


async def test_mcp_tools_are_exposed_and_callable():
    manager = MCPManager(
        [
            MCPServerSettings(
                name="echo", command=sys.executable, args=[str(SERVER)], risk=RiskLevel.SAFE
            )
        ]
    )
    try:
        tools = await manager.connect()
        names = sorted(t.name for t in tools)
        assert names == ["echo__add", "echo__echo"]
        collection = ToolCollection(*tools)
        params = collection.to_params()
        assert params[0]["function"]["parameters"]["type"] == "object"
        result = await collection.execute("echo__echo", {"text": "hi"})
        assert result.ok and "echo: hi" in result.output
        result = await collection.execute("echo__add", {"a": 2, "b": 40})
        assert "42" in result.output
        assert tools[0].assess({"text": "x"}).summary.startswith("mcp:echo.")
    finally:
        await manager.close()


async def test_unavailable_server_is_skipped():
    manager = MCPManager([MCPServerSettings(name="nope", command="definitely-not-a-command-xyz")])
    try:
        assert await manager.connect() == []
    finally:
        await manager.close()
