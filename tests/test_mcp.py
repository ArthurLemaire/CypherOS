from __future__ import annotations

import sys
from pathlib import Path

from nanomuse.config import MCPServerSettings
from nanomuse.schema import RiskLevel
from nanomuse.tools import MCPManager, ToolCollection

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


async def test_per_tool_policy_overrides_the_servers_defaults():
    """`[mcp.servers.tools.<name>]` makes one tool stricter (or looser) than its server;
    a field left out keeps the server's value."""
    from nanomuse.config import MCPToolPolicy

    manager = MCPManager(
        [
            MCPServerSettings(
                name="echo",
                command=sys.executable,
                args=[str(SERVER)],
                risk=RiskLevel.SAFE,
                reads_private_data=True,
                tools={"add": MCPToolPolicy(risk=RiskLevel.SENSITIVE, reads_private_data=False)},
            )
        ]
    )
    try:
        tools = {t.name: t for t in await manager.connect()}
        assert tools["echo__add"].risk == RiskLevel.SENSITIVE
        assert tools["echo__add"].reads_private_data is False
        assert tools["echo__add"].egress is False  # not set: the server's
        assert tools["echo__echo"].risk == RiskLevel.SAFE
        assert tools["echo__echo"].reads_private_data is True
    finally:
        await manager.close()


async def test_unavailable_server_is_skipped():
    manager = MCPManager([MCPServerSettings(name="nope", command="definitely-not-a-command-xyz")])
    try:
        assert await manager.connect() == []
    finally:
        await manager.close()


async def test_vault_placeholders_are_resolved_before_connecting():
    """A key kept in the vault reaches the server through url, args or env; the config
    object itself keeps the placeholder."""
    secrets = {"ECHO_MODE": "loud", "AMAP_KEY": "k-123"}

    def resolve(value):
        import re

        if isinstance(value, str):
            return re.sub(r"\{\{vault:(\w+)\}\}", lambda m: secrets[m.group(1)], value)
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    cfg = MCPServerSettings(
        name="echo",
        command=sys.executable,
        args=[str(SERVER), "{{vault:ECHO_MODE}}"],
        env={"ECHO_KEY": "{{vault:AMAP_KEY}}"},
        url=None,
    )
    manager = MCPManager([cfg], resolve=resolve)
    resolved = manager._resolved(cfg)
    assert resolved.args == [str(SERVER), "loud"] and resolved.env == {"ECHO_KEY": "k-123"}
    assert cfg.args[1] == "{{vault:ECHO_MODE}}" and cfg.env["ECHO_KEY"] == "{{vault:AMAP_KEY}}"
    url = MCPServerSettings(name="amap", url="https://mcp.amap.com/mcp?key={{vault:AMAP_KEY}}")
    assert manager._resolved(url).url == "https://mcp.amap.com/mcp?key=k-123"
    try:
        tools = await manager.connect()  # the echo server ignores its extra argument
        assert sorted(t.name for t in tools) == ["echo__add", "echo__echo"]
    finally:
        await manager.close()
