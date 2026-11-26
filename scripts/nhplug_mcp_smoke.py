"""Pinned upstream stdio handshake, no provider requests or real credentials."""
import asyncio
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED = "c61e38ca37de801911ac6c29a685077802513d44"
TOOLS = {
    "list_apis",
    "describe_api",
    "call_api",
    "get_stock_price",
    "get_stock_balance",
    "list_accounts",
}


async def run(path: Path) -> None:
    head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if head != EXPECTED:
        raise RuntimeError("unexpected upstream revision")
    params = StdioServerParameters(
        command="node",
        args=[str(path / "dist/index.js")],
        cwd=str(path),
        env={
            "NHPLUG_APP_KEY": "synthetic-placeholder",
            "NHPLUG_APP_SECRET": "synthetic-placeholder",
            "NHPLUG_BASE_URL": "https://127.0.0.1:9",
            "NHPLUG_AUTH_URL": "https://127.0.0.1:9",
            "NHPLUG_ALLOW_HOSTS": "127.0.0.1",
            "NHPLUG_DEFAULT_ACCOUNT": "",
        },
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        info = await session.initialize()
        assert info.serverInfo.name == "nhplug-mcp"
        assert info.serverInfo.version == "0.1.0"
        assert {tool.name for tool in (await session.list_tools()).tools} == TOOLS
        print("NHPLUG MCP handshake + six registered tools verified; no provider calls")


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1]).resolve()))
