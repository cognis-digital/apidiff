import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ============================================================================
// TYPES & INTERFACES
// ============================================================================

export interface OpenAPISchema {
  openapi: string;
  info: { title: string; version: string };
  paths: Record<string, PathItem>;
  components?: { schemas: Record<string, SchemaObject> };
}

export interface PathItem {
  get?: OperationObject;
  post?: OperationObject;
  put?: OperationObject;
  delete?: OperationObject;
  patch?: OperationObject;
  parameters?: ParameterLocation[];
}

export interface OperationObject {
  summary?: string;
  description?: string;
  operationId: string;
  parameters?: ParameterReference[];
  requestBody?: ReferenceOrObject<RequestBody>;
  responses: ResponsesObject;
}

export interface SchemaObject {
  type: 'object' | 'string' | 'number' | 'boolean' | 'array' | 'null';
  properties?: Record<string, SchemaObject>;
  required: string[];
  items?: SchemaObject;
  oneOf?: SchemaObject[];
  anyOf?: SchemaObject[];
  allOf?: SchemaObject[];
  enum?: (string | number)[];
  format?: string;
  description?: string;
}

export interface GraphQLSchema {
  __schema: IntrospectionQuery;
}

interface IntrospectionQuery {
  queryType: { name: string };
  mutationType?: { name: string } | null;
  subscriptionType?: { name: string } | null;
  types: IntrospectionType[];
  directives: IntrospectionDirective[];
}

interface IntrospectionType {
  kind: 'OBJECT' | 'INTERFACE' | 'UNION' | 'ENUM' | 'INPUT_OBJECT' | 'SCALAR';
  name: string;
  fields?: { name: string; args: IntrospectionArgument[] }[];
  interfaces?: IntrospectionTypeRef[];
  possibleTypes?: IntrospectionTypeRef[];
  enumValues?: IntrospectionEnumValue[];
  inputFields?: IntrospectionInputField[];
}

interface IntrospectionTypeRef {
  kind: 'OBJECT' | 'INTERFACE';
  name: string;
}

interface IntrospectionArgument {
  name: string;
  description?: string;
  type: IntrospectionTypeRef;
  defaultValue?: any;
}

interface IntrospectionEnumValue {
  name: string;
  description?: string;
  deprecationReason?: string | null;
}

interface IntrospectionInputField {
  name: string;
  description?: string;
  type: IntrospectionTypeRef;
  defaultValue?: any;
}

interface IntrospectionDirective {
  name: string;
  description?: string;
  locations: string[];
  args: IntrospectionArgument[];
}

// ============================================================================
// OPENAPI NORMALIZER
// ============================================================================

export class OpenAPINormalizer {
  private readonly schemaCache = new Map<string, SchemaObject>();

  constructor(private openapiSpec: OpenAPISchema) {}

  normalize(): NormalizedOpenAPISchema {
    const normalized: NormalizedOpenAPISchema = {
      metadata: this.normalizeMetadata(),
      paths: this.normalizePaths(),
      components: this.normalizeComponents(),
    };

    return normalized;
  }

  private normalizeMetadata() {
    return {
      title: this.openapiSpec.info.title,
      version: this.openapiSpec.info.version,
      openapiVersion: this.openapiSpec.openapi,
    };
  }

  private normalizePaths(): NormalizedPaths {
    const paths: NormalizedPaths = {};

    for (const [path, pathItem] of Object.entries(this.openapiSpec.paths)) {
      // Normalize path string - trim trailing slash, lowercase method names
      const normalizedPath = this.normalizePathString(path);
      
      const operations: Record<string, NormalizedOperation> = {};
      
      if (pathItem.get) {
        operations.get = this.normalizeOperation(pathItem.get);
      }
      if (pathItem.post) {
        operations.post = this.normalizeOperation(pathItem.post);
      }
      if (pathItem.put) {
        operations.put = this.normalizeOperation(pathItem.put);
      }
      if (pathItem.delete) {
        operations.delete = this.normalizeOperation(pathItem.delete);
      }
      if (pathItem.patch) {
        operations.patch = this.normalizeOperation(pathItem.patch);
      }

      // Only include paths with at least one operation
      if (Object.keys(operations).length > 0) {
        paths[normalizedPath] = operations;
      }
    }

    return paths;
  }

  private normalizePathString(path: string): string {
    let normalized = path.trim();
    
    // Remove trailing slash if present (but keep root /)
    if (normalized.length > 1 && normalized.endsWith('/')) {
      normalized = normalized.slice(0, -1);
    }
    
    return normalized;
  }

  private normalizeOperation(operation: OperationObject): NormalizedOperation {
    const normalized: NormalizedOperation = {
      operationId: this.normalizeString(operation.operationId),
      summary: this.normalizeString(operation.summary || ''),
      description: this.normalizeString(operation.description || ''),
      responses: this.normalizeResponses(operation.responses),
    };

    if (operation.parameters) {
      normalized.parameters = operation.parameters.map(p => ({
        name: p.name,
        in: p.in,
        required: p.required,
        schema: this.normalizeSchema(p.schema),
      }));
    }

    return normalized;
  }

  private normalizeResponses(responses: ResponsesObject): NormalizedResponses {
    const normalized: NormalizedResponses = {};
    
    for (const [code, response] of Object.entries(responses)) {
      if (typeof code === 'string') continue; // Skip non-numeric codes
      
      const numericCode = parseInt(code, 10);
      if (isNaN(numericCode)) continue;

      normalized[numericCode] = this.normalizeResponse(response);
    }

    return normalized;
  }

  private normalizeResponse(response: ResponseObject): NormalizedResponse {
    const normalized: NormalizedResponse = {};
    
    // Normalize content types - sort and deduplicate
    if (response.content) {
      normalized.contentTypes = Object.keys(response.content).sort().join(',');
      
      for (const [contentType, mediaType] of Object.entries(response.content)) {
        const parts = contentType.split(';').map(s => s.trim());
        const mainType = parts[0];
        
        if (!normalized.contentTypes) {
          normalized.contentTypes = mainType;
        } else if (!normalized.contentTypes.includes(mainType)) {
          normalized.contentTypes += ',' + mainType;
        }

        // Normalize schema within content type
        if (mediaType.schema && mediaType.schema.$ref) {
          const refName = this.extractRefName(mediaType.schema.$ref);
          normalized.schemaRef = refName;
        } else if (mediaType.schema) {
          normalized.schemaInline = true;
        }

        // Normalize headers
        if (mediaType.headers) {
          normalized.headers = {};
          for (const [headerName, header] of Object.entries(mediaType.headers)) {
            normalized.headers[headerName] = this.normalizeHeader(header);
          }
        }
      }
    }

    // Normalize description
    if (response.description) {
      normalized.description = this.normalizeString(response.description);
    }

    return normalized;
  }

  private normalizeHeader(header: HeaderObject): NormalizedHeader {
    const normalized: NormalizedHeader = {};
    
    if (header.schema && header.schema.$ref) {
      const refName = this.extractRefName(header.schema.$ref);
      normalized.schemaRef = refName;
    } else if (header.schema) {
      normalized.schemaInline = true;
    }

    return normalized;
  }

  private normalizeSchema(schema: SchemaObject | ReferenceOrObject<SchemaObject>): NormalizedSchema {
    // Handle $ref references
    if (schema.$ref) {
      const refName = this.extractRefName(schema.$ref);
      
      // Check cache first
      if (this.schemaCache.has(refName)) {
        return { type: 'ref', name: refName };
      }

      // Resolve reference - for demo, we'll create a placeholder
      // In production, you'd resolve against the components.schemas map
      const resolved = this.resolveReference(refName);
      
      if (resolved) {
        return resolved;
      } else {
        // Fallback: treat as inline schema with ref name
        return { type: 'ref', name: refName };
      }
    }

    // Handle oneOf, anyOf, allOf
    if (schema.oneOf || schema.anyOf || schema.allOf) {
      const combined = this.normalizeComposite(schema);
      
      // Cache the result
      const key = JSON.stringify({ type: 'composite', parts: [combined] });
      this.schemaCache.set(key, combined);
      
      return combined;
    }

    // Handle array types
    if (schema.type === 'array' && schema.items) {
      const itemsSchema = this.normalizeSchema(schema.items);
      return {
        type: 'array',
        itemSchemaRef: itemsSchema.type === 'ref' ? itemsSchema.name : undefined,
        itemSchemaInline: itemsSchema.type !== 'ref',
      };
    }

    // Handle object types with properties
    if (schema.type === 'object' && schema.properties) {
      const props: Record<string, NormalizedSchema> = {};
      
      for (const [propName, propSchema] of Object.entries(schema.properties)) {
        props[propName] = this.normalizeSchema(propSchema);
      }

      return {
        type: 'object',
        properties: props,
        required: schema.required || [],
      };
    }

    // Handle enum types
    if (schema.enum) {
      const normalizedEnum = schema.enum.map((val): string | number => {
        if (typeof val === 'string') {
          return this.normalizeString(val);
        }
        return val;
      });
      
      return {
        type: 'enum',
        values: normalizedEnum,
      };
    }

    // Handle basic types
    const baseType = schema.type || 'unknown';
    
    if (baseType === 'string') {
      return {
        type: 'string',
        format: this.normalizeString(schema.format || ''),
        pattern: this.normalizeString(schema.pattern || ''),
        minLength: typeof schema.minLength === 'number' ? schema.minLength : undefined,
        maxLength: typeof schema.maxLength === 'number' ? schema.maxLength : undefined,
      };
    }

    if (baseType === 'number') {
      return {
        type: 'number',
        format: this.normalizeString(schema.format || ''),
        minimum: typeof schema.minimum === 'number' ? schema.minimum : undefined,
        maximum: typeof schema.maximum === 'number' ? schema.maximum : undefined,
      };
    }

    if (baseType === 'boolean') {
      return { type: 'boolean' };
    }

    // Unknown or null types
    return { type: baseType || 'unknown' };
  }

  private normalizeComposite(schema: SchemaObject): NormalizedSchema {
    const parts: NormalizedSchema[] = [];

    if (schema.oneOf) {
      for (const part of schema.oneOf) {
        parts.push(this.normalizeSchema(part));
      }
    } else if (schema.anyOf) {
      for (const part of schema.anyOf) {
        parts.push(this.normalizeSchema(part));
      }
    } else if (schema.allOf) {
      for (const part of schema.allOf) {
        parts.push(this.normalizeSchema(part));
      }
    }

    return {
      type: 'composite',
      kind: schema.oneOf ? 'oneOf' : schema.anyOf ? 'anyOf' : 'allOf',
      parts,
    };
  }

  private normalizeComponents(): NormalizedComponents | null {
    if (!this.openapiSpec.components) {
      return null;
    }

    const normalized: NormalizedComponents = {};

    // Normalize schemas
    if (this.openapiSpec.components.schemas) {
      for (const [name, schema] of Object.entries(this.openapiSpec.components.schemas)) {
        normalized.schemas[name] = this.normalizeSchema(schema);
      }
    }

    return normalized;
  }

  private resolveReference(refName: string): NormalizedSchema | null {
    // Try to find in components.schemas
    if (this.openapiSpec.components?.schemas) {
      const schema = this.openapiSpec.components.schemas[refName];
      if (schema) {
        return this.normalizeSchema(schema);
      }
    }

    // Try to find in paths parameters
    for (const pathItem of Object.values(this.openapiSpec.paths)) {
      for (const operation of [
        pathItem.get, pathItem.post, pathItem.put, 
        pathItem.delete, pathItem.patch
      ]) {
        if (operation?.parameters) {
          for (const param of operation.parameters) {
            if (param.schema && param.schema.$ref === refName) {
              return this.normalizeSchema(param.schema);
            }
          }
        }
      }
    }

    // Try to find in requestBody
    for (const pathItem of Object.values(this.openapiSpec.paths)) {
      for (const operation of [
        pathItem.get, pathItem.post, pathItem.put, 
        pathItem.delete, pathItem.patch
      ]) {
        if (operation?.requestBody) {
          const body = this.extractRequestBody(operation.requestBody);
          if (body && body.schema && body.schema.$ref === refName) {
            return this.normalizeSchema(body.schema);
          }
        }
      }
    }

    // Try to find in response content schemas
    for (const pathItem of Object.values(this.openapiSpec.paths)) {
      for (const operation of [
        pathItem.get, pathItem.post, pathItem.put, 
        pathItem.delete, pathItem.patch
      ]) {
        if (operation?.responses) {
          for (const response of Object.values(operation.responses)) {
            if (response.content) {
              for (const mediaType of Object.values(response.content)) {
                if (mediaType.schema && mediaType.schema.$ref === refName) {
                  return this.normalizeSchema(mediaType.schema);
                }
              }
            }
          }
        }
      }
    }

    // Try to find in header schemas
    for (const pathItem of Object.values(this.openapiSpec.paths)) {
      for (const operation of [
        pathItem.get, pathItem.post, pathItem.put, 
        pathItem.delete, pathItem.patch
      ]) {
        if (operation?.responses) {
          for (const response of Object.values(operation.responses)) {
            if (response.content) {
              for (const mediaType of Object.values(response.content)) {
                if (mediaType.headers) {
                  for (const header of Object.values(mediaType.headers)) {
                    if (header.schema && header.schema.$ref === refName) {
                      return this.normalizeSchema(header.schema);
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    // Try to find in path parameters
    for (const [path, pathItem] of Object.entries(this.openapiSpec.paths)) {
      if (pathItem.parameters) {
        for (const param of pathItem.parameters) {
          if (param.schema && param.schema.$ref === refName) {
            return this.normalizeSchema(param.schema);
          }
        }
      }
    }

    // Not found - return null
    return null;
  }

  private extractRequestBody(requestBody: ReferenceOrObject<RequestBody>): RequestBody | null {
    if (requestBody.$ref) {
      const refName = this.extractRefName(requestBody.$ref);
      
      // Try components.schemas first
      if (this.openapiSpec.components?.schemas[refName]) {
        return { schema: this.openapiSpec.components.schemas[refName] };
      }

      // Try to resolve as a path parameter reference
      for (const [path, pathItem] of Object.entries(this.openapiSpec.paths)) {
        if (pathItem.parameters) {
          for (const param of pathItem.parameters) {
            if (param.schema && param.schema.$ref === requestBody.$ref) {
              return { schema: param.schema };
            }
          }
        }
      }

      // Try to resolve as a response content reference
      for (const [path, pathItem] of Object.entries(this.openapiSpec.paths)) {
        for (const operation of [