"""Command-line interface for APIDIFF.

Usage:
    apidiff diff OLD NEW [--format table|json] [--fmt auto|openapi|graphql]
    apidiff --version

Exit codes:
    0  no breaking changes
    1  breaking changes detected
    2  usage / IO error
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import TOOL_NAME, TOOL_VERSION
from .core import DiffResult, Severity, diff_files


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _render_table(result: DiffResult) -> str:
    lines: List[str] = []
    s = result.to_dict()["summary"]
    lines.append(f"format: {result.api_format}")
    lines.append(
        f"changes: {s['total']}  breaking: {s['breaking']}  "
        f"warning: {s['warning']}  info: {s['info']}"
    )
    lines.append("")
    if not result.changes:
        lines.append("No changes detected.")
        return "\n".join(lines)

    order = {Severity.BREAKING: 0, Severity.WARNING: 1, Severity.INFO: 2}
    width = max(len(c.location) for c in result.changes)
    width = min(max(width, 8), 48)
    for c in sorted(result.changes, key=lambda x: order[x.severity]):
        loc = c.location if len(c.location) <= width else c.location[: width - 1] + "…"
        lines.append(f"  [{c.severity.value:<8}] {loc:<{width}}  {c.message}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Breaking-change detector for OpenAPI / GraphQL across commits.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"{TOOL_NAME} {TOOL_VERSION}",
    )
    sub = parser.add_subparsers(dest="command")

    d = sub.add_parser("diff", help="Diff two API definitions")
    d.add_argument("old", help="Path to the OLD (baseline) API definition")
    d.add_argument("new", help="Path to the NEW (candidate) API definition")
    d.add_argument("--format", choices=("table", "json"), default="table",
                   help="Output format (default: table)")
    d.add_argument("--fmt", choices=("auto", "openapi", "graphql"),
                   default="auto", help="Input API format (default: auto-detect)")
    d.add_argument("--fail-on", choices=("breaking", "warning", "never"),
                   default="breaking",
                   help="Severity threshold that yields a non-zero exit")
    return parser


def _exit_code(result: DiffResult, fail_on: str) -> int:
    if fail_on == "never":
        return 0
    if fail_on == "warning":
        return 1 if (result.breaking or result.warnings) else 0
    return 1 if result.has_breaking() else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "diff":
        parser.print_help()
        return 2

    try:
        old_text = _read(args.old)
        new_text = _read(args.new)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        result = diff_files(old_text, new_text, fmt=args.fmt)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"error: failed to diff: {e}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(_render_table(result))

    return _exit_code(result, args.fail_on)


if __name__ == "__main__":
    sys.exit(main())
