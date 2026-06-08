"""APIDIFF — breaking-change detector for OpenAPI / GraphQL across commits.

Compares two API definitions (OpenAPI 3.x JSON or GraphQL SDL) and reports
changes classified by severity. Designed for CI: non-zero exit when a
breaking change is detected.
"""
from .core import (
    Change,
    DiffResult,
    Severity,
    diff_openapi,
    diff_graphql,
    diff_files,
    detect_format,
)

TOOL_NAME = "apidiff"
TOOL_VERSION = "1.0.0"

__all__ = [
    "TOOL_NAME",
    "TOOL_VERSION",
    "Change",
    "DiffResult",
    "Severity",
    "diff_openapi",
    "diff_graphql",
    "diff_files",
    "detect_format",
]
