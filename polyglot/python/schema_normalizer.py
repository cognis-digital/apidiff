"""
polyglot/python/schema_normalizer.py

A schema normalizer for detecting breaking changes in OpenAPI and GraphQL APIs.

This module provides canonical representations of API schemas that can be compared
across commits to identify what changed and whether those changes are breaking.

Breaking change categories:
- ADDITIVE: New paths, operations, fields (usually safe)
- DELETIVE: Removed resources, operations, fields (breaking!)
- MODIFYING: Changed types, parameters (potentially breaking)
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, Union


class ChangeType(Enum):
    """Categories of schema changes."""
    
    # Safe additions
    PATH_ADDED = "path_added"
    OPERATION_ADDED = "operation_added"
    FIELD_ADDED = "field_added"
    PARAMETER_ADDED = "parameter_added"
    SCHEMA_ADDED = "schema_added"
    
    # Breaking deletions
    PATH_REMOVED = "path_removed"
    OPERATION_REMOVED = "operation_removed"
    FIELD_REMOVED = "field_removed"
    PARAMETER_REMOVED = "parameter_removed"
    SCHEMA_REMOVED = "schema_removed"
    
    # Potentially breaking modifications
    TYPE_CHANGED = "type_changed"
    REQUIRED_ADDED = "required_added"
    REQUIRED_REMOVED = "required_removed"
    DEFAULT_CHANGED = "default_changed"
    ENUM_VALUE_REMOVED = "enum_value_removed"


@dataclass(frozen=True)
class Change:
    """Represents a single change between two schema versions."""
    
    change_type: ChangeType
    path: str  # The location of the change (e.g., "/users", "User.email")
    old_value: Any = None
    new_value: Any = None
    
    def __hash__(self):
        return hash((self.change_type, self.path, 
                     json.dumps(self.old_value, sort_keys=True) if self.old_value else "",
                     json.dumps(self.new_value, sort_keys=True) if self.new_value else ""))
    
    def summary(self) -> str:
        """Human-readable summary of the change."""
        prefix = {
            ChangeType.PATH_ADDED: "Added path",
            ChangeType.OPERATION_ADDED: "Added operation",
            ChangeType.FIELD_ADDED: "Added field",
            ChangeType.PARAMETER_ADDED: "Added parameter",
            ChangeType.SCHEMA_ADDED: "Added schema",
            ChangeType.PATH_REMOVED: "Removed path",
            ChangeType.OPERATION_REMOVED: "Removed operation",
            ChangeType.FIELD_REMOVED: "Removed field",
            ChangeType.PARAMETER_REMOVED: "Removed parameter",
            ChangeType.SCHEMA_REMOVED: "Removed schema",
            ChangeType.TYPE_CHANGED: "Changed type",
            ChangeType.REQUIRED_ADDED: "Added required field",
            ChangeType.REQUIRED_REMOVED: "Removed required field",
            ChangeType.DEFAULT_CHANGED: "Changed default value",
            ChangeType.ENUM_VALUE_REMOVED: "Removed enum value",
        }.get(self.change_type, str(self.change_type))
        
        if self.old_value is not None and self.new_value is not None:
            return f"{prefix}: {self.old_value} → {self.new_value}"
        elif self.old_value is not None:
            return f"{prefix}: removed ({self.old_value})"
        else:
            return prefix
        
    def is_breaking(self) -> bool:
        """Check if this change breaks existing clients."""
        breaking_types = [
            ChangeType.PATH_REMOVED,
            ChangeType.OPERATION_REMOVED,
            ChangeType.FIELD_REMOVED,
            ChangeType.PARAMETER_REMOVED,
            ChangeType.SCHEMA_REMOVED,
            ChangeType.TYPE_CHANGED,
            ChangeType.REQUIRED_ADDED,
            ChangeType.ENUM_VALUE_REMOVED,
        ]
        return self.change_type in breaking_types


@dataclass
class SchemaDiff:
    """Complete diff between two schema versions."""
    
    changes: List[Change] = field(default_factory=list)
    is_breaking: bool = False
    
    def add_change(self, change: Change):
        if not change.is_breaking():
            self.changes.append(change)
        
        # Track breaking status
        if any(c.is_breaking() for c in self.changes):
            self.is_breaking = True


def normalize_openapi_path(path: str) -> str:
    """Normalize an OpenAPI path string."""
    if not path:
        return ""
    
    # Remove trailing slash except for root
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    
    # Normalize parameter placeholders
    normalized_parts = []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            # Parameter placeholder - keep as-is but normalize case
            normalized_parts.append(part.upper())
        else:
            normalized_parts.append(part)
    
    return "/".join(normalized_parts)


def normalize_openapi_type(type_str: str, schemas: Dict[str, Any] = None) -> str:
    """Normalize an OpenAPI type string."""
    if not type_str:
        return ""
    
    # Resolve $ref references
    if type_str.startswith("$ref"):
        ref_path = type_str[5:].strip()  # Remove "$ref" prefix
        if schemas and ref_path in schemas:
            schema_def = schemas.get(ref_path, {})
            resolved_type = normalize_openapi_type(
                schema_def.get("type", "object"), 
                {**schemas, **schema_def}
            )
            return resolved_type
    
    # Normalize string types
    if type_str.startswith("string"):
        return "string"
    
    # Normalize number types
    if type_str in ("number", "integer", "float", "double"):
        return "number"
    
    # Normalize boolean
    if type_str == "boolean":
        return "boolean"
    
    # Normalize array
    if type_str.startswith("array"):
        item_type = type_str[5:].strip()  # Remove "array" prefix
        if item_type:
            return f"array<{normalize_openapi_type(item_type, schemas)}>"
        return "array<unknown>"
    
    # Normalize object
    if type_str == "object":
        return "object"
    
    # Return as-is for unknown types
    return type_str


def normalize_openapi_schema(schema: Dict[str, Any], base_schemas: Dict[str, Any] = None) -> str:
    """Create a normalized string representation of an OpenAPI schema."""
    if not isinstance(schema, dict):
        return json.dumps(schema, sort_keys=True)
    
    # Build the schema definition for $ref resolution
    full_schema = {**base_schemas, **schema} if base_schemas else schema
    
    def normalize_value(value: Any) -> str:
        """Recursively normalize a value."""
        if isinstance(value, dict):
            return normalize_openapi_schema(value, full_schema)
        elif isinstance(value, list):
            return "[" + ", ".join(normalize_value(v) for v in value) + "]"
        else:
            return str(value)
    
    # Create a normalized representation
    result = {
        "type": normalize_openapi_type(schema.get("type", ""), full_schema),
        "properties": {},
        "required": sorted(set(schema.get("required", [])), key=str),
    }
    
    if schema.get("properties"):
        for prop_name, prop_def in sorted(schema["properties"].items()):
            result["properties"][prop_name] = normalize_openapi_schema(
                prop_def, full_schema
            )
    
    # Add additional properties that might be relevant
    if schema.get("enum"):
        result["enum"] = sorted(set(str(e) for e in schema["enum"]))
    
    if schema.get("default") is not None:
        result["default"] = normalize_value(schema["default"])
    
    return json.dumps(result, sort_keys=True)


def extract_openapi_paths(spec: Dict[str, Any]) -> Dict[str, List[Dict]]:
    """Extract and normalize paths from an OpenAPI spec."""
    if not isinstance(spec, dict):
        return {}
    
    paths = {}
    for path, methods in sorted(spec.get("paths", {}).items()):
        normalized_path = normalize_openapi_path(path)
        
        operations = []
        for method, operation in sorted(methods.items()):
            if not isinstance(operation, dict):
                continue
            
            # Extract key information about the operation
            op_info = {
                "method": method.upper(),
                "operation_id": operation.get("operationId"),
                "summary": operation.get("summary") or "",
                "description": operation.get("description") or "",
                "parameters": [],
                "request_body": None,
                "responses": {},
            }
            
            # Normalize parameters
            for param in operation.get("parameters", []):
                if not isinstance(param, dict):
                    continue
                
                param_info = {
                    "name": param.get("in") or "",  # "path" | "query" | "header" | "cookie"
                    "location": param.get("in"),
                    "schema": normalize_openapi_schema(
                        param.get("schema", {}), spec
                    ),
                }
                
                if param_info["name"]:
                    op_info["parameters"].append(param_info)
            
            # Extract request body
            if operation.get("requestBody"):
                rb = operation["requestBody"]
                content = rb.get("content", {})
                for media_type, media_def in sorted(content.items()):
                    if isinstance(media_def, dict):
                        op_info["request_body"] = {
                            "media_type": media_type,
                            "schema": normalize_openapi_schema(
                                media_def.get("schema", {}), spec
                            ),
                        }
            
            # Extract responses
            for status_code, response in sorted(operation.get("responses", {}).items()):
                if isinstance(response, dict):
                    content = response.get("content", {})
                    for media_type, media_def in sorted(content.items()):
                        if isinstance(media_def, dict):
                            op_info["responses"][status_code] = {
                                "media_type": media_type,
                                "schema": normalize_openapi_schema(
                                    media_def.get("schema", {}), spec
                                ),
                            }
            
            # Add operation to paths
            if normalized_path not in paths:
                paths[normalized_path] = []
            paths[normalized_path].append(op_info)
    
    return paths


def extract_openapi_schemas(spec: Dict[str, Any]) -> List[Dict]:
    """Extract and normalize component schemas from an OpenAPI spec."""
    if not isinstance(spec, dict):
        return []
    
    schemas = []
    
    # Extract from components/schemas (OpenAPI 3.x)
    components = spec.get("components", {})
    if isinstance(components, dict):
        schemas_section = components.get("schemas", {})
        for name, schema in sorted(schemas_section.items()):
            if isinstance(schema, dict):
                normalized = normalize_openapi_schema(
                    schema, {**spec, **components}
                )
                schemas.append({
                    "name": name,
                    "normalized": normalized,
                })
    
    # Extract from definitions (OpenAPI 2.x)
    if spec.get("definitions"):
        for name, definition in sorted(spec["definitions"].items()):
            if isinstance(definition, dict):
                normalized = normalize_openapi_schema(
                    definition, {**spec, **components}
                )
                schemas.append({
                    "name": name,
                    "normalized": normalized,
                })
    
    return schemas


def extract_graphql_types(sdl: str) -> List[Dict]:
    """Extract and normalize GraphQL types from SDL string."""
    if not sdl or not isinstance(sdl, str):
        return []
    
    types = []
    
    # Simple regex-based extraction (works for most common cases)
    type_pattern = re.compile(
        r"(\w+)\s*(:\s*(?:\w+|\[\]\s*\w+|!\s*\w+|\?\s*\w+)?)?"
    )
    
    lines = sdl.split("\n")
    for line in lines:
        line = line.strip()
        
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue
        
        # Match type definitions
        match = type_pattern.match(line)
        if match:
            name = match.group(1)
            rest = line[match.end():].strip()
            
            # Determine if it's an input/output type
            is_input = "input" in line.lower() or "mutation" in line.lower()
            is_union = "union" in line.lower()
            is_interface = "interface" in line.lower()
            
            types.append({
                "name": name,
                "is_input": is_input,
                "is_output": not is_input and not is_union,
                "normalized": rest if rest else "",
            })
    
    return types


def extract_graphql_introspection(introspection: Dict) -> List[Dict]:
    """Extract and normalize GraphQL types from introspection result."""
    if not isinstance(introspection, dict):
        return []
    
    types = []
    
    # Extract object types (including input types)
    for type_name in introspection.get("data", {}).get("__schema", {}).get("types", []):
        if not isinstance(type_name, dict):
            continue
        
        name = type_name.get("name")
        kind = type_name.get("kind")
        
        # Skip non-object types (scalars, enums, etc.) for now
        if kind and "OBJECT" not in kind:
            continue
        
        fields = []
        for field_def in type_name.get("fields", []):
            if not isinstance(field_def, dict):
                continue
            
            field_info = {
                "name": field_def.get("name"),
                "type": normalize_openapi_type(
                    field_def.get("type", {}).get("name") or "",
                ),
            }
            
            # Check if required (non-nullable and no default)
            is_required = True
            type_def = field_def.get("type", {})
            if type_def:
                non_null = type_def.get("nonNull", False)
                has_default = "defaultValue" in field_def
                
                if non_null and not has_default:
                    is_required = True
            
            field_info["required"] = is_required
            fields.append(field_info)
        
        types.append({
            "name": name,
            "kind": kind,
            "fields": sorted(fields, key=lambda x: x.get("name", "")),
        })
    
    return types


def normalize_graphql_schema(sdl_or_introspection: Union[str, Dict]) -> str:
    """Create a normalized string representation of a GraphQL schema."""
    if isinstance(sdl_or_introspection, dict):
        # Introspection result - extract types and serialize
        types = extract_graphql_introspection(sdl_or_introspection)
        return json.dumps(types, sort_keys=True)
    
    elif isinstance(sdl_or_introspection, str):
        # SDL string - extract types and serialize
        types = extract_graphql_types(sdl_or_introspection)
        return json.dumps(types, sort_keys=True)
    
    else:
        return json.dumps({"error": "Unknown schema format"})


def compute_schema_hash(schema_repr: str) -> str:
    """Compute a stable hash of a normalized schema representation."""
    # Use SHA-256 for good collision resistance
    return hashlib.sha256(schema_repr.encode("utf-8")).hexdigest()


class SchemaNormalizer:
    """Main normalizer class for comparing API schemas across versions."""
    
    def __init__(self, spec_or_sdl: Union[Dict, str], schema_type: Optional[str] = None):
        """
        Initialize the normalizer with a schema.
        
        Args:
            spec_or_sdl: OpenAPI spec (dict) or GraphQL SDL (str)
            schema_type: "openapi" | "graphql" - auto-detected if not provided
        """
        self.schema_type = schema_type or self._detect_schema_type(spec_or_sdl)
        
        if self.schema_type == "openapi":
            self.spec = spec_or_sdl
            self.paths = extract_openapi_paths(spec_or_sdl)
            self.schemas = extract_openapi_schemas(spec_or_sdl)
        else:  # graphql
            self.sdl = spec_or