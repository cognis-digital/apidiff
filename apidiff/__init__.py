"""APIDIFF — Breaking-change detector for OpenAPI / GraphQL across commits."""
from apidiff.core import scan, TOOL_NAME, TOOL_VERSION
__all__ = ["scan", "TOOL_NAME", "TOOL_VERSION"]
