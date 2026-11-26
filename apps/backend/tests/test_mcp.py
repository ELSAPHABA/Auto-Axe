import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_local_stdio_handshake():
    server = StdioServerParameters(command=sys.executable, args=["-m", "autoaxe.entrypoints.mcp"])
    async with stdio_client(server) as (reader, writer), ClientSession(reader, writer) as session:
        init = await session.initialize()
        assert init.serverInfo.name == "Auto-Axe fixture smoke"
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == ["fixture_health"]
        result = await session.call_tool("fixture_health", {})
        assert not result.isError
