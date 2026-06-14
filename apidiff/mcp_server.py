"""APIDIFF MCP server — exposes diff() as an MCP tool for Cognis.Studio."""
from __future__ import annotations

import json

from apidiff.core import diff_files


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
    def apidiff_diff(old_text: str, new_text: str, fmt: str = "auto") -> str:
        """Diff two API definitions and return JSON findings.

        Args:
            old_text: The baseline (old) API definition text.
            new_text: The candidate (new) API definition text.
            fmt: Input format — one of 'auto', 'openapi', or 'graphql'.
        """
        try:
            result = diff_files(old_text, new_text, fmt=fmt)
        except (ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(result.to_dict())

    app.run()
    return 0
