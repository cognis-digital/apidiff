"""APIDIFF MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from apidiff.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-apidiff[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-apidiff[mcp]'")
        return 1
    app = FastMCP("apidiff")

    @app.tool()
    def apidiff_scan(target: str) -> str:
        """Breaking-change detector for OpenAPI / GraphQL across commits. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
