"""Core diff engine for APIDIFF.

Supports two input formats:
  * OpenAPI 3.x  (JSON)
  * GraphQL SDL  (text; a pragmatic subset parser — stdlib only)

Changes are classified as BREAKING / WARNING / INFO. A change is breaking when
it can break an existing consumer of the API (removed endpoint, removed field a
client may read, new required input the client won't send, narrowed types,
etc.).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Severity(str, Enum):
    BREAKING = "BREAKING"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Change:
    severity: Severity
    code: str
    location: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class DiffResult:
    api_format: str
    changes: List[Change] = field(default_factory=list)

    def add(self, severity: Severity, code: str, location: str, message: str) -> None:
        self.changes.append(Change(severity, code, location, message))

    @property
    def breaking(self) -> List[Change]:
        return [c for c in self.changes if c.severity == Severity.BREAKING]

    @property
    def warnings(self) -> List[Change]:
        return [c for c in self.changes if c.severity == Severity.WARNING]

    def has_breaking(self) -> bool:
        return bool(self.breaking)

    def to_dict(self) -> Dict[str, Any]:
        counts = {s.value: 0 for s in Severity}
        for c in self.changes:
            counts[c.severity.value] += 1
        return {
            "format": self.api_format,
            "summary": {
                "total": len(self.changes),
                "breaking": counts[Severity.BREAKING.value],
                "warning": counts[Severity.WARNING.value],
                "info": counts[Severity.INFO.value],
            },
            "changes": [c.to_dict() for c in self.changes],
        }


# --------------------------------------------------------------------------
# Format detection
# --------------------------------------------------------------------------
def detect_format(text: str) -> str:
    """Return 'openapi' or 'graphql' for the given document text."""
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc):
                return "openapi"
    if re.search(r"\b(type|input|enum|interface|union)\s+\w", text):
        return "graphql"
    # Fall back: JSON => openapi, else graphql
    return "openapi" if stripped.startswith("{") else "graphql"


# --------------------------------------------------------------------------
# OpenAPI diff
# --------------------------------------------------------------------------
def _load_json(text: str) -> Dict[str, Any]:
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError("OpenAPI document must be a JSON object")
    return doc


def _params_index(op: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in op.get("parameters", []) or []:
        if isinstance(p, dict) and "name" in p:
            out[(p["name"], p.get("in", "query"))] = p
    return out


def _schema_props(schema: Dict[str, Any]) -> Dict[str, Any]:
    return (schema or {}).get("properties", {}) or {}


def diff_openapi(old_text: str, new_text: str) -> DiffResult:
    old = _load_json(old_text)
    new = _load_json(new_text)
    res = DiffResult(api_format="openapi")

    old_paths = old.get("paths", {}) or {}
    new_paths = new.get("paths", {}) or {}

    # Removed paths
    for path in old_paths:
        if path not in new_paths:
            res.add(Severity.BREAKING, "path.removed", path,
                    f"Path '{path}' was removed")

    # Added paths
    for path in new_paths:
        if path not in old_paths:
            res.add(Severity.INFO, "path.added", path,
                    f"Path '{path}' was added")

    methods = ("get", "put", "post", "delete", "patch", "head", "options")
    for path in old_paths:
        if path not in new_paths:
            continue
        old_item = old_paths[path] or {}
        new_item = new_paths[path] or {}
        for m in methods:
            old_op = old_item.get(m)
            new_op = new_item.get(m)
            loc = f"{m.upper()} {path}"
            if old_op and not new_op:
                res.add(Severity.BREAKING, "operation.removed", loc,
                        f"Operation '{loc}' was removed")
                continue
            if new_op and not old_op:
                res.add(Severity.INFO, "operation.added", loc,
                        f"Operation '{loc}' was added")
                continue
            if not old_op or not new_op:
                continue
            _diff_operation(res, loc, old_op, new_op)

    return res


def _diff_operation(res: DiffResult, loc: str, old_op: Dict[str, Any],
                    new_op: Dict[str, Any]) -> None:
    old_params = _params_index(old_op)
    new_params = _params_index(new_op)

    # Removed params
    for key, p in old_params.items():
        if key not in new_params:
            name, where = key
            res.add(Severity.WARNING, "param.removed", loc,
                    f"Parameter '{name}' (in: {where}) was removed")

    # Added / required-tightened params
    for key, p in new_params.items():
        name, where = key
        if key not in old_params:
            if p.get("required"):
                res.add(Severity.BREAKING, "param.added.required", loc,
                        f"New required parameter '{name}' (in: {where}) added")
            else:
                res.add(Severity.INFO, "param.added", loc,
                        f"New optional parameter '{name}' (in: {where}) added")
        else:
            old_p = old_params[key]
            if p.get("required") and not old_p.get("required"):
                res.add(Severity.BREAKING, "param.required.added", loc,
                        f"Parameter '{name}' (in: {where}) became required")
            elif old_p.get("required") and not p.get("required"):
                res.add(Severity.INFO, "param.required.removed", loc,
                        f"Parameter '{name}' (in: {where}) is no longer required")

    # Request body required-fields
    old_body = _body_schema(old_op)
    new_body = _body_schema(new_op)
    if old_body is not None and new_body is not None:
        old_req = set(old_body.get("required", []) or [])
        new_req = set(new_body.get("required", []) or [])
        for f in sorted(new_req - old_req):
            res.add(Severity.BREAKING, "requestBody.required.added", loc,
                    f"Request body field '{f}' became required")
        for f in sorted(old_req - new_req):
            res.add(Severity.INFO, "requestBody.required.removed", loc,
                    f"Request body field '{f}' is no longer required")
        # Property type narrowing / removal in request body
        _diff_props(res, loc, "requestBody", _schema_props(old_body),
                    _schema_props(new_body), removed_breaking=False)

    # Response schema: removing a response-property breaks readers
    old_resp = _success_response_schema(old_op)
    new_resp = _success_response_schema(new_op)
    if old_resp is not None and new_resp is not None:
        _diff_props(res, loc, "response", _schema_props(old_resp),
                    _schema_props(new_resp), removed_breaking=True)

    # Removed success response status codes
    old_codes = set((old_op.get("responses", {}) or {}).keys())
    new_codes = set((new_op.get("responses", {}) or {}).keys())
    for code in sorted(old_codes - new_codes):
        if code.startswith("2"):
            res.add(Severity.BREAKING, "response.removed", loc,
                    f"Success response '{code}' was removed")


def _diff_props(res: DiffResult, loc: str, scope: str,
                old_props: Dict[str, Any], new_props: Dict[str, Any],
                removed_breaking: bool) -> None:
    for name in old_props:
        if name not in new_props:
            sev = Severity.BREAKING if removed_breaking else Severity.WARNING
            res.add(sev, f"{scope}.property.removed", loc,
                    f"{scope} property '{name}' was removed")
            continue
        old_t = (old_props[name] or {}).get("type")
        new_t = (new_props[name] or {}).get("type")
        if old_t and new_t and old_t != new_t:
            res.add(Severity.BREAKING, f"{scope}.property.type.changed", loc,
                    f"{scope} property '{name}' type changed: {old_t} -> {new_t}")
    for name in new_props:
        if name not in old_props:
            res.add(Severity.INFO, f"{scope}.property.added", loc,
                    f"{scope} property '{name}' was added")


def _body_schema(op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rb = op.get("requestBody")
    if not isinstance(rb, dict):
        return None
    content = rb.get("content", {}) or {}
    for ctype in ("application/json", *content.keys()):
        media = content.get(ctype)
        if isinstance(media, dict) and "schema" in media:
            return media["schema"]
    return None


def _success_response_schema(op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    responses = op.get("responses", {}) or {}
    for code in ("200", "201", "2XX", "default"):
        resp = responses.get(code)
        if isinstance(resp, dict):
            content = resp.get("content", {}) or {}
            media = content.get("application/json")
            if isinstance(media, dict) and "schema" in media:
                return media["schema"]
    return None


# --------------------------------------------------------------------------
# GraphQL SDL diff (stdlib subset parser)
# --------------------------------------------------------------------------
@dataclass
class GQLField:
    name: str
    type: str
    args: Dict[str, str]  # arg name -> type


@dataclass
class GQLType:
    kind: str           # type | input | enum | interface | union
    name: str
    fields: Dict[str, GQLField] = field(default_factory=dict)
    values: List[str] = field(default_factory=list)  # for enums


_TYPE_HEADER = re.compile(
    r"\b(type|input|interface|enum|union)\s+(\w+)", re.MULTILINE)


def _parse_graphql(text: str) -> Dict[str, GQLType]:
    """Parse a pragmatic subset of GraphQL SDL into a type map."""
    # Strip comments
    text = re.sub(r"#[^\n]*", "", text)
    types: Dict[str, GQLType] = {}

    i = 0
    for m in _TYPE_HEADER.finditer(text):
        kind, name = m.group(1), m.group(2)
        if kind == "union":
            types[name] = GQLType(kind=kind, name=name)
            continue
        brace = text.find("{", m.end())
        if brace == -1:
            continue
        body, _ = _read_block(text, brace)
        gt = GQLType(kind=kind, name=name)
        if kind == "enum":
            gt.values = [v.strip() for v in body.split() if v.strip()]
        else:
            for fld in _parse_fields(body):
                gt.fields[fld.name] = fld
        types[name] = gt
    return types


def _read_block(text: str, open_idx: int) -> Tuple[str, int]:
    depth = 0
    start = open_idx + 1
    for j in range(open_idx, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j], j
    return text[start:], len(text)


_FIELD_RE = re.compile(
    r"(\w+)\s*(?:\(([^)]*)\))?\s*:\s*([\[\]\w!]+)")


def _parse_fields(body: str) -> List[GQLField]:
    fields_out: List[GQLField] = []
    for m in _FIELD_RE.finditer(body):
        name, raw_args, ftype = m.group(1), m.group(2), m.group(3)
        args: Dict[str, str] = {}
        if raw_args:
            for arg in raw_args.split(","):
                am = re.match(r"\s*(\w+)\s*:\s*([\[\]\w!]+)", arg)
                if am:
                    args[am.group(1)] = am.group(2)
        fields_out.append(GQLField(name=name, type=ftype, args=args))
    return fields_out


def diff_graphql(old_text: str, new_text: str) -> DiffResult:
    old = _parse_graphql(old_text)
    new = _parse_graphql(new_text)
    res = DiffResult(api_format="graphql")

    for name in old:
        if name not in new:
            res.add(Severity.BREAKING, "type.removed", name,
                    f"Type '{name}' was removed")
    for name in new:
        if name not in old:
            res.add(Severity.INFO, "type.added", name,
                    f"Type '{name}' was added")

    for name, old_t in old.items():
        new_t = new.get(name)
        if new_t is None:
            continue
        if old_t.kind != new_t.kind:
            res.add(Severity.BREAKING, "type.kind.changed", name,
                    f"Type '{name}' kind changed: {old_t.kind} -> {new_t.kind}")
            continue
        if old_t.kind == "enum":
            _diff_enum(res, old_t, new_t)
        else:
            _diff_object(res, old_t, new_t)
    return res


def _diff_enum(res: DiffResult, old_t: GQLType, new_t: GQLType) -> None:
    old_vals = set(old_t.values)
    new_vals = set(new_t.values)
    for v in sorted(old_vals - new_vals):
        res.add(Severity.BREAKING, "enum.value.removed", old_t.name,
                f"Enum value '{old_t.name}.{v}' was removed")
    for v in sorted(new_vals - old_vals):
        res.add(Severity.WARNING, "enum.value.added", old_t.name,
                f"Enum value '{old_t.name}.{v}' was added")


def _diff_object(res: DiffResult, old_t: GQLType, new_t: GQLType) -> None:
    is_input = old_t.kind == "input"
    for fname, old_f in old_t.fields.items():
        new_f = new_t.fields.get(fname)
        loc = f"{old_t.name}.{fname}"
        if new_f is None:
            res.add(Severity.BREAKING, "field.removed", loc,
                    f"Field '{loc}' was removed")
            continue
        if old_f.type != new_f.type:
            # For output: tightening optional->required is safe; loosening is breaking.
            # For input: required->optional safe; optional->required breaking.
            sev = _type_change_severity(old_f.type, new_f.type, is_input)
            res.add(sev, "field.type.changed", loc,
                    f"Field '{loc}' type changed: {old_f.type} -> {new_f.type}")
        if is_input:
            _diff_input_args_via_type(res, loc, old_f, new_f)
        else:
            _diff_field_args(res, loc, old_f, new_f)
    for fname, new_f in new_t.fields.items():
        if fname not in old_t.fields:
            loc = f"{new_t.name}.{fname}"
            if is_input and new_f.type.endswith("!"):
                res.add(Severity.BREAKING, "input.field.added.required", loc,
                        f"New required input field '{loc}' was added")
            else:
                res.add(Severity.INFO, "field.added", loc,
                        f"Field '{loc}' was added")


def _diff_input_args_via_type(res: DiffResult, loc: str, old_f: GQLField,
                              new_f: GQLField) -> None:
    # Input object fields don't carry args; placeholder for symmetry.
    return


def _diff_field_args(res: DiffResult, loc: str, old_f: GQLField,
                     new_f: GQLField) -> None:
    for aname, atype in old_f.args.items():
        if aname not in new_f.args:
            res.add(Severity.BREAKING, "arg.removed", loc,
                    f"Argument '{aname}' on '{loc}' was removed")
    for aname, atype in new_f.args.items():
        if aname not in old_f.args:
            if atype.endswith("!"):
                res.add(Severity.BREAKING, "arg.added.required", loc,
                        f"New required argument '{aname}: {atype}' on '{loc}'")
            else:
                res.add(Severity.INFO, "arg.added", loc,
                        f"New optional argument '{aname}: {atype}' on '{loc}'")
        else:
            old_at = old_f.args[aname]
            if old_at != atype:
                # required-ifying an arg is breaking
                if atype.endswith("!") and not old_at.endswith("!"):
                    res.add(Severity.BREAKING, "arg.required.added", loc,
                            f"Argument '{aname}' on '{loc}' became required")
                else:
                    res.add(Severity.WARNING, "arg.type.changed", loc,
                            f"Argument '{aname}' on '{loc}' type changed: "
                            f"{old_at} -> {atype}")


def _type_change_severity(old_type: str, new_type: str, is_input: bool) -> Severity:
    old_base = old_type.rstrip("!")
    new_base = new_type.rstrip("!")
    old_req = old_type.endswith("!")
    new_req = new_type.endswith("!")
    if old_base != new_base:
        return Severity.BREAKING
    # same base type, nullability changed
    if is_input:
        # optional -> required breaks callers
        return Severity.BREAKING if (new_req and not old_req) else Severity.INFO
    # output: required -> optional breaks readers expecting non-null
    return Severity.BREAKING if (old_req and not new_req) else Severity.INFO


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
def diff_files(old_text: str, new_text: str,
               fmt: Optional[str] = None) -> DiffResult:
    if fmt in (None, "auto"):
        fmt = detect_format(new_text)
    if fmt == "openapi":
        return diff_openapi(old_text, new_text)
    if fmt == "graphql":
        return diff_graphql(old_text, new_text)
    raise ValueError(f"Unknown format: {fmt}")
