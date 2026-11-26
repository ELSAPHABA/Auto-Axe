"""Local, credential-free SDK handshake smoke. No remote transport."""

from mcp.server.fastmcp import FastMCP

from autoaxe.infrastructure.config import Settings

server = FastMCP("Auto-Axe fixture smoke")


@server.tool()
def fixture_health() -> dict[str, bool]:
    return {"fixture_only": True, "live_enabled": False}


def main() -> None:
    Settings()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
