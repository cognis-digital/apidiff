"""APIDIFF MCP server — exposes the diff engine as an MCP tool.

Lets an MCP-aware client (Claude Desktop, Cursor, Cognis.Studio, the
uncensored-fleet) ask apidiff to compare two API definitions and return the
classified changes as JSON. The server is passive and read-only: it opens two
local files and diffs them. It performs no network access and no active
scanning.

Start it with::

    apidiff mcp                     # via the CLI subcommand
    python -m apidiff.mcp_server    # direct

Requires the optional 'mcp' extra::

    pip install "cognis-apidiff[mcp]"
"""
from __future__ import annotations

from apidiff.core import scan, to_json


def serve() -> int:
    """Start an MCP stdio server exposing the apidiff diff tool."""
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-apidiff[mcp]'")
        return 1
    app = FastMCP("apidiff")

    @app.tool()
    def apidiff_diff(old_path: str, new_path: str, fmt: str = "auto") -> str:
        """Detect breaking changes between two OpenAPI/GraphQL definitions.

        Args:
            old_path: path to the baseline (old) API definition file.
            new_path: path to the candidate (new) API definition file.
            fmt: 'auto' (default), 'openapi', or 'graphql'.

        Returns a JSON document with a severity summary and the full list of
        BREAKING / WARNING / INFO changes.
        """
        return to_json(scan(old_path, new_path,
                            fmt=None if fmt == "auto" else fmt))

    app.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve())
