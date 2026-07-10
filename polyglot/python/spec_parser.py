import json
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path


class BreakingChangeType(Enum):
    PATH_REMOVED = auto()
    OPERATION_REMOVED = auto()
    SCHEMA_CHANGED = auto()
    REQUIRED_FIELD_ADDED = auto()
    FIELD_REMOVED = auto()
    ARGUMENT_REMOVED = auto()
    TYPE_CHANGED = auto()
    ENUM_VALUE_REMOVED = auto()


@dataclass(frozen=True)
class PathOperation:
    path: str
    method: str
    request_schema: Optional[Dict] = None
    response_schema: Optional[Dict] = None
    headers: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash((self.path, self.method))


@dataclass(frozen=True)
class OpenAPISpecSummary:
    paths: List[PathOperation] = field(default_factory=list)
    schemas: Dict[str, Any] = field(default_factory=dict)
    components_schemas: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash((tuple(sorted(self.paths)), tuple(sorted(self.schemas.items()))))


@dataclass(frozen=True)
class GraphQLTypeField:
    name: str
    type_name: str  # e.g., "User!", "String", "[Int!]"
    is_input: bool = False

    def __hash__(self):
        return hash((self.name, self.type_name))


@dataclass(frozen=True)
class GraphQLTypeSummary:
    name: str
    kind: str  # OBJECT, INPUT_OBJECT, ENUM, SCALAR, INTERFACE, UNION
    fields: List[GraphQLTypeField] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)

    def __hash__(self):
        return hash((self.name, self.kind, tuple(sorted(self.fields)), tuple(sorted(self.interfaces))))


@dataclass(frozen=True)
class GraphQLSpecSummary:
    types: Dict[str, GraphQLTypeSummary] = field(default_factory=dict)
    directives: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash((tuple(sorted(self.types.items())), tuple(sorted(self.directives.items()))))


class SpecParserError(Exception):
    """Base exception for parser errors."""
    pass


def _parse_openapi_schemas(spec: Dict, schemas: Dict[str, Any]) -> None:
    """Extract all schema definitions from OpenAPI spec."""
    # Check components/schemas (OpenAPI 3.x)
    if 'components' in spec and 'schemas' in spec['components']:
        schemas.update(spec['components']['schemas'])
    
    # Check info/schema (legacy OpenAPI 2.0)
    if '$schema' in spec:
        version = spec.get('$schema', '')
        if '3.' not in version:
            schemas.update(spec.get('definitions', {}))


def _parse_openapi_paths(spec: Dict, base_url: str = "") -> List[PathOperation]:
    """Extract path operations from OpenAPI spec."""
    paths = []
    
    for path, methods in spec.get('paths', {}).items():
        full_path = f"{base_url.rstrip('/')}/{path.lstrip('/')}" if base_url else path
        
        for method, operation in methods.items():
            request_schema = None
            response_schema = None
            
            # Extract request body schema
            if 'requestBody' in operation:
                rb = operation['requestBody']
                content = rb.get('content', {})
                json_content = content.get('application/json') or content.get('*/json')
                if json_content and '$ref' not in json_content:
                    request_schema = json_content
                
            # Extract response schema (use 200 as default)
            responses = operation.get('responses', {})
            for status_code, resp in responses.items():
                content = resp.get('content', {})
                if 'application/json' in content or '*/json' in content:
                    json_content = content['application/json'] or content['*/json']
                    if json_content and '$ref' not in json_content:
                        response_schema = json_content
            
            paths.append(PathOperation(
                path=full_path,
                method=method.upper(),
                request_schema=request_schema,
                response_schema=response_schema,
                headers={k: v for k, v in operation.get('headers', {}).items()}
            ))
    
    return paths


def _parse_graphql_types(sdl: str) -> Dict[str, GraphQLTypeSummary]:
    """Parse GraphQL SDL and extract type summaries."""
    types = {}
    current_type = None
    
    # Simple state machine parser for SDL
    lines = sdl.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line or line.startswith('#'):
            i += 1
            continue
        
        # Check for type definition start
        match = _match_type_def(line)
        if match:
            current_type = {
                'name': match['name'],
                'kind': match['kind'],
                'fields': [],
                'interfaces': []
            }
            
            # Extract interfaces (implements/extends)
            for iface in match.get('interfaces', []):
                if iface not in current_type['interfaces']:
                    current_type['interfaces'].append(iface)
            
            i += 1
            continue
        
        # Check for field definition within a type
        if current_type and _match_field_def(line, current_type):
            i += 1
            continue
        
        # Type ended or new section
        if not line.startswith('type ') and not line.startswith('interface '):
            if current_type:
                types[current_type['name']] = GraphQLTypeSummary(
                    name=current_type['name'],
                    kind=current_type['kind'],
                    fields=current_type['fields'],
                    interfaces=current_type['interfaces']
                )
                current_type = None
        
        i += 1
    
    # Don't forget the last type
    if current_type:
        types[current_type['name']] = GraphQLTypeSummary(
            name=current_type['name'],
            kind=current_type['kind'],
            fields=current_type['fields'],
            interfaces=current_type['interfaces']
        )
    
    return types


def _match_type_def(line: str) -> Optional[Dict]:
    """Match a type definition line."""
    # Type definitions
    if line.startswith('type ') or line.startswith('interface '):
        name = line.split()[1].rstrip(',')
        kind = 'OBJECT'
        
        interfaces = []
        for iface in ['implements', 'extends']:
            if iface in line:
                iface_match = f"{iface} " + ''.join(c for c in line if c.isalpha() or c == '_' or c == '.')
                interfaces.append(iface_match.split()[1].rstrip(','))
        
        return {
            'name': name,
            'kind': kind,
            'interfaces': interfaces
        }
    
    # Input object types
    elif line.startswith('input ') or line.startswith('interface '):
        name = line.split()[1].rstrip(',')
        kind = 'INPUT_OBJECT' if line.startswith('input ') else 'INTERFACE'
        
        interfaces = []
        for iface in ['implements', 'extends']:
            if iface in line:
                iface_match = f"{iface} " + ''.join(c for c in line if c.isalpha() or c == '_' or c == '.')
                interfaces.append(iface_match.split()[1].rstrip(','))
        
        return {
            'name': name,
            'kind': kind,
            'interfaces': interfaces
        }
    
    # Enum types
    elif line.startswith('enum '):
        name = line.split()[1].rstrip(',')
        return {
            'name': name,
            'kind': 'ENUM',
            'interfaces': []
        }
    
    # Scalar types (usually at start of file)
    elif line.startswith('scalar ') and not any(t in sdl for t in ['type ', 'interface ', 'enum ', 'input ']):
        return {
            'name': line.split()[1].rstrip(','),
            'kind': 'SCALAR',
            'interfaces': []
        }
    
    # Union types
    elif line.startswith('union ') or line.startswith('type '):
        name = line.split()[1].rstrip(',')
        kind = 'UNION' if line.startswith('union ') else 'OBJECT'
        
        members = []
        for member in ['on', 'of']:
            if member in line:
                members.append(line.split(member)[1].strip().rstrip(','))
        
        return {
            'name': name,
            'kind': kind,
            'interfaces': members
        }
    
    # Interface types
    elif line.startswith('interface ') and not any(t in sdl for t in ['type ', 'enum ', 'input ']):
        name = line.split()[1].rstrip(',')
        return {
            'name': name,
            'kind': 'INTERFACE',
            'interfaces': []
        }
    
    return None


def _match_field_def(line: str, current_type: Dict) -> bool:
    """Match a field definition within a type."""
    if not line or line.startswith('#'):
        return False
    
    # Field definitions start with lowercase letter (after type/interface name)
    # They typically have format: "fieldName: Type"
    parts = line.split()
    if len(parts) >= 2 and parts[0].islower():
        current_type['fields'].append({
            'name': parts[0],
            'type': ''.join(parts[1:])
        })
        return True
    
    # Check for nested type definitions (new type inside a type definition)
    if line.startswith('type ') or line.startswith('interface ') or \
       line.startswith('enum ') or line.startswith('input '):
        current_type['fields'].append({
            'name': parts[0] if len(parts) > 0 else '',
            'type': ''.join(parts[1:]) if len(parts) > 1 else ''
        })
        return True
    
    return False


def _parse_graphql_sdl(sdl: str) -> GraphQLSpecSummary:
    """Parse complete GraphQL SDL into a summary."""
    types = _parse_graphql_types(sdl)
    
    # Extract directives if present
    directives = {}
    for line in sdl.split('\n'):
        stripped = line.strip()
        if stripped.startswith('directive '):
            parts = stripped.split()
            name = parts[1]
            args_str = ''.join(parts[2:])
            directives[name] = {'args': args_str}
    
    return GraphQLSpecSummary(types=types, directives=dict(directives))


def _normalize_schema(schema: Dict) -> str:
    """Normalize a schema for comparison."""
    if not schema:
        return ''
    
    # Remove $ref and normalize types
    normalized = {}
    for key, value in sorted(schema.items()):
        if isinstance(value, dict):
            if '$ref' in value:
                normalized[key] = value['$ref']
            else:
                normalized[key] = _normalize_schema(value)
        elif isinstance(value, list):
            normalized[key] = [_normalize_schema(v) for v in value]
        elif isinstance(value, str):
            # Normalize type references (remove !, [], etc.)
            clean_type = value.replace('!', '').replace('[', '').replace(']', '')
            normalized[key] = clean_type if clean_type else value
        else:
            normalized[key] = value
    
    return json.dumps(normalized, sort_keys=True)


def _normalize_field(field: GraphQLTypeField) -> str:
    """Normalize a field for comparison."""
    # Remove modifiers like ! (non-null), [] (list)
    clean_type = field.type_name.replace('!', '').replace('[', '').replace(']', '')
    return f"{field.name}:{clean_type}"


def _normalize_graphql_spec(spec: GraphQLSpecSummary) -> str:
    """Normalize a GraphQL spec for comparison."""
    normalized_types = {}
    
    for name, type_summary in sorted(spec.types.items()):
        fields_normalized = []
        
        for field in sorted(type_summary.fields, key=lambda f: _normalize_field(f)):
            clean_name = _normalize_field(field)
            if clean_name not in fields_normalized:
                fields_normalized.append(clean_name)
        
        normalized_types[name] = {
            'kind': type_summary.kind,
            'fields': sorted(fields_normalized),
            'interfaces': sorted(type_summary.interfaces)
        }
    
    return json.dumps(normalized_types, sort_keys=True)


def _compare_openapi_specs(old: OpenAPISpecSummary, new: OpenAPISpecSummary) -> List[Dict]:
    """Compare two OpenAPI specs and find breaking changes."""
    changes = []
    
    # Build lookup dictionaries
    old_paths_by_key = {(p.path, p.method): p for p in old.paths}
    new_paths_by_key = {(p.path, p.method): p for p in new.paths}
    
    all_keys = set(old_paths_by_key.keys()) | set(new_paths_by_key.keys())
    
    # Check for removed operations (breaking)
    for key in all_keys:
        if key not in old_paths_by_key and key in new_paths_by_key:
            changes.append({
                'type': BreakingChangeType.OPERATION_REMOVED,  # Actually added
                'path': key[0],
                'method': key[1]
            })
        elif key not in new_paths_by_key and key in old_paths_by_key:
            op = old_paths_by_key[key]
            changes.append({
                'type': BreakingChangeType.OPERATION_REMOVED,
                'path': key[0],
                'method': key[1],
                'details': f"Removed {op.method} on {key[0]}"
            })
    
    # Check for schema changes in paths
    all_paths = set(p.path for p in old.paths) | set(p.path for p in new.paths)
    for path in all_paths:
        if path in old_paths_by_key and path in new_paths_by_key:
            old_op = old_paths_by_key[(path, 'ANY')]  # Simplified lookup
            new_op = new_paths_by_key[(path, 'ANY')]
            
            # Compare request/response schemas
            for field_name in ['request_schema', 'response_schema']:
                old_val = getattr(old_op, field_name)
                new_val = getattr(new_op, field_name)
                
                if old_val and new_val:
                    old_norm = _normalize_schema(old_val)
                    new_norm = _normalize_schema(new_val)
                    
                    if old_norm != new_norm:
                        changes.append({
                            'type': BreakingChangeType.SCHEMA_CHANGED,
                            'path': path,
                            'field': field_name.replace('_schema', ''),
                            'details': f"Schema changed for {old_norm} -> {new_norm}"
                        })


def _compare_graphql_specs(old: GraphQLSpecSummary, new: GraphQLSpecSummary) -> List[Dict]:
    """Compare two GraphQL specs and find breaking changes."""
    changes = []
    
    # Build lookup dictionaries
    old_types_by_name = {t.name: t for t in old.types}
    new_types_by_name = {t.name: t for t in new.types}
    
    all_names = set(old_types_by_name.keys()) | set(new_types_by_name.keys())
    
    # Check for removed types (breaking)
    for name in all_names:
        if name not in old_types_by_name and name in new_types_by_name:
            changes.append({
                'type': BreakingChangeType.SCHEMA_CHANGED,  # New type added
                'name': name,
                'details': f"New type '{name}' added"
            })
        elif name not in new_types_by_name and name in old_types_by_name:
            old_type = old_types_by_name[name]
            changes.append({
                'type': BreakingChangeType.FIELD_REMOVED,  # Type removed
                'name': name,
                'details': f"Type '{name}' ({old_type.kind}) removed"
            })
    
    # Check for field changes within types
    for name in all_names:
        if name in old_types_by_name and name in new_types_by_name:
            old_type = old_types_by_name[name]
            new_type = new_types_by_name[name]
            
            # Compare fields
            old_fields_set = set(_normalize_field(f) for f in old_type.fields)
            new_fields_set = set(_normalize_field(f) for f in new_type.fields)
            
            removed_fields