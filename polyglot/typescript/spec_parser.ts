import { parse as yamlParse } from 'yaml';
import * as fs from 'fs/promises';

// ============================================================================
// TYPES & INTERFACES
// ============================================================================

export interface ParsedOpenAPI3x {
  info: OpenAPIInfo;
  paths: Map<string, PathItem[]>;
  schemas: SchemaRegistry;
  components?: {
    schemas?: Record<string, any>;
    parameters?: Record<string, any>;
    requestBodies?: Record<string, any>;
    responses?: Record<string, any>;
    examples?: Record<string, any>;
    headers?: Record<string, any>;
    securitySchemes?: Record<string, any>;
  };
}

export interface OpenAPIInfo {
  title: string;
  version: string;
  description?: string;
  contact?: { name: string; email?: string; url?: string };
  license?: { name: string; url?: string };
}

export interface PathItem {
  path: string;
  methods: Map<HttpMethod, Operation>;
}

export interface Operation {
  method: HttpMethod;
  operationId: string | undefined;
  summary?: string;
  description?: string;
  parameters: Parameter[];
  requestBody?: RequestBody;
  responses: ResponseMap;
  tags?: string[];
}

export type HttpMethod = 'get' | 'post' | 'put' | 'delete' | 'patch' | 'head' | 'options';

export interface Parameter {
  name: string;
  in: 'path' | 'query' | 'header' | 'cookie';
  required?: boolean;
  schema: SchemaRefOrInline;
}

export interface RequestBody {
  content: Map<string, MediaType>;
}

export interface ResponseMap {
  [status: string]: Response;
}

export interface Response {
  description: string;
  headers?: Record<string, Header>;
  content?: Map<string, MediaType>;
}

export interface MediaType {
  schema: SchemaRefOrInline;
  examples?: any[];
}

export interface SchemaRegistry {
  schemas: Map<string, SchemaDefinition>;
  types: Set<string>;
}

export interface SchemaDefinition {
  name: string;
  type: 'object' | 'string' | 'number' | 'boolean' | 'array' | 'null';
  properties?: Record<string, any>;
  required?: string[];
  items?: any;
  enum?: any[];
  format?: string;
}

export interface SchemaRefOrInline {
  $ref: string | undefined;
  inline: any;
}

// ============================================================================
// OPENAPI PARSER
// ============================================================================

interface OpenAPISource extends URLSearchParams {
  raw: string;
}

export class OpenAPIParser {
  private static readonly VERSIONS = ['3.0', '3.1'];

  public async parse(source: OpenAPISource): Promise<ParsedOpenAPI3x> {
    const raw = source.get('raw') || '';
    
    if (!raw) {
      throw new Error('OpenAPI spec is empty');
    }

    let doc: any;
    try {
      doc = JSON.parse(raw);
    } catch (e) {
      // Try YAML fallback
      const yamlDoc = yamlParse(raw);
      if (!yamlDoc || !yamlDoc.openapi) {
        throw new Error('Invalid OpenAPI spec. Not valid JSON or YAML.');
      }
      doc = yamlDoc;
    }

    return this.buildParsed(doc, source.get('raw')!);
  }

  private buildParsed(doc: any, raw: string): ParsedOpenAPI3x {
    const version = doc.openapi || '';
    
    if (!this.VERSIONS.includes(version)) {
      throw new Error(`Unsupported OpenAPI version: ${version}`);
    }

    // Build paths map with methods
    const pathsMap = new Map<string, PathItem[]>();
    
    for (const [pathStr, pathData] of Object.entries(doc.paths || {})) {
      if (!Array.isArray(pathData)) continue;
      
      const methods: Map<HttpMethod, Operation> = new Map();
      
      for (const methodData of pathData) {
        if (!methodData.get || !methodData.post) continue; // Basic check
        
        const operation: Operation = {
          method: methodData.get || 'get',
          operationId: methodData.operationId,
          summary: methodData.summary,
          description: methodData.description,
          parameters: this.extractParameters(methodData),
          requestBody: methodData.requestBody ? { content: new Map() } : undefined,
          responses: this.buildResponseMap(methodData.responses || {}),
          tags: methodData.tags,
        };

        methods.set(operation.method, operation);
      }
      
      pathsMap.set(pathStr, [methods]);
    }

    // Build schema registry
    const schemas = new SchemaRegistry();
    
    if (doc.components?.schemas) {
      for (const [name, schema] of Object.entries(doc.components.schemas)) {
        schemas.schemas.set(name, this.normalizeSchema(name, schema));
        schemas.types.add(name);
      }
    }

    return {
      info: {
        title: doc.info?.title || 'Unknown',
        version: doc.info?.version || '0.0.0',
        description: doc.info?.description,
        contact: doc.info?.contact,
        license: doc.info?.license,
      },
      paths: pathsMap,
      schemas,
      components: doc.components,
    };
  }

  private extractParameters(op: any): Parameter[] {
    const params: Parameter[] = [];
    
    // Path parameters (required)
    if (op.parameters) {
      for (const param of op.parameters) {
        if (param.in === 'path') {
          params.push({
            name: param.name,
            in: 'path',
            required: true,
            schema: this.normalizeSchemaRef(param),
          });
        } else {
          params.push({
            name: param.name,
            in: param.in,
            required: param.required,
            schema: this.normalizeSchemaRef(param),
          });
        }
      }
    }

    // Request body parameters (for POST/PUT/PATCH)
    if (op.requestBody && op.method !== 'get' && op.method !== 'head') {
      const requestBody = op.requestBody as any;
      
      for (const [mediaType, media] of Object.entries(requestBody.content || {})) {
        params.push({
          name: '_body',
          in: 'body',
          required: requestBody.required,
          schema: this.normalizeSchemaRef(media),
        });
        
        if (media.mediaType) {
          const contentType = media.mediaType.split(';')[0].trim();
          if (!contentType.startsWith('application/json')) continue;
          
          // Extract JSON schema from examples
          if (Array.isArray(media.examples)) {
            for (const example of media.examples) {
              params.push({
                name: '_example',
                in: 'body',
                required: false,
                schema: this.normalizeSchemaRef(example),
              });
            }
          }
        }
      }
    }

    return params;
  }

  private buildResponseMap(responses: any): ResponseMap {
    const map: ResponseMap = {};
    
    for (const [status, response] of Object.entries(responses)) {
      if (!response || !response.description) continue;
      
      map[status] = {
        description: response.description,
        headers: this.buildHeaderMap(response.headers),
        content: this.buildContentTypeMap(response.content),
      };
    }

    return map;
  }

  private buildHeaderMap(headers?: any): Record<string, Header> | undefined {
    if (!headers) return undefined;
    
    const result: Record<string, Header> = {};
    for (const [name, header] of Object.entries(headers)) {
      result[name] = {
        description: header.description || '',
        schema: this.normalizeSchemaRef(header),
      };
    }
    return result;
  }

  private buildContentTypeMap(content?: any): Map<string, MediaType> | undefined {
    if (!content) return undefined;
    
    const map = new Map();
    for (const [mediaType, media] of Object.entries(content)) {
      map.set(mediaType, {
        schema: this.normalizeSchemaRef(media),
        examples: Array.isArray(media.examples) ? media.examples : undefined,
      });
    }
    return map;
  }

  private normalizeSchema(name: string, schema: any): SchemaDefinition {
    const result: SchemaDefinition = {
      name,
      type: 'object', // Default for unknown types
    };

    if (schema.type) {
      result.type = schema.type as any;
    } else if (Array.isArray(schema.properties)) {
      result.type = 'object';
    } else if (schema.items) {
      result.type = 'array';
    } else if (schema.enum) {
      result.type = 'string';
    }

    // Extract properties for objects
    if (schema.properties && typeof schema.properties === 'object') {
      result.properties = {};
      
      for (const [propName, propSchema] of Object.entries(schema.properties)) {
        const normalized = this.normalizeSchemaRef(propSchema);
        result.properties[propName] = normalized;
        
        // Track required properties
        if (!result.required) {
          result.required = [];
        }
        if (schema.required && schema.required.includes(propName)) {
          result.required.push(propName);
        }
      }
    }

    // Handle items for arrays
    if (schema.items) {
      const itemSchema = this.normalizeSchemaRef(schema.items);
      result.items = itemSchema;
    }

    return result;
  }

  private normalizeSchemaRef(schema: any): SchemaRefOrInline {
    if (!schema || !schema.$ref) {
      return { $ref: undefined, inline: schema };
    }
    
    const refPath = schema.$ref.replace(/^#\/components\/schemas\//i, '');
    return { $ref: schema.$ref, inline: this.normalizeSchema(refPath, schema) };
  }

  private normalizeSchema(name: string, schema: any): SchemaDefinition {
    if (!schema || !schema.type) {
      return { name, type: 'object' };
    }
    
    const result: SchemaDefinition = {
      name,
      type: schema.type as any,
    };

    // Copy over other properties that might be useful for comparison
    if (schema.properties) {
      result.properties = schema.properties;
    }
    if (schema.required) {
      result.required = schema.required;
    }
    if (schema.items) {
      result.items = this.normalizeSchemaRef(schema.items);
    }
    if (schema.enum) {
      result.enum = schema.enum;
    }

    return result;
  }
}

// ============================================================================
// GRAPHQL PARSER
// ============================================================================

interface GraphQLSource extends URLSearchParams {
  raw: string;
}

export class GraphQLParser {
  public async parse(source: GraphQLSource): Promise<ParsedGraphQL> {
    const raw = source.get('raw') || '';
    
    if (!raw) {
      throw new Error('GraphQL schema is empty');
    }

    try {
      return this.buildParsed(raw);
    } catch (e) {
      // Try parsing as JSON first, then SDL
      let doc: any;
      
      try {
        doc = JSON.parse(raw);
        if (!doc.__schema || !Array.isArray(doc.__schema.types)) {
          throw new Error('Invalid GraphQL introspection response');
        }
        return this.buildParsedFromIntrospection(doc, raw);
      } catch (parseErr) {
        // Assume SDL format
        return this.buildParsed(raw);
      }
    }
  }

  private buildParsed(sdl: string): ParsedGraphQL {
    const result: ParsedGraphQL = {
      schemaId: 'unknown',
      types: new Map(),
      queries: [],
      mutations: [],
      subscriptions: [],
    };

    // Parse SDL into structured representation
    const parsedSDL = this.parseSDL(sdl);
    
    // Extract type definitions
    for (const [name, typeDef] of Object.entries(parsedSDL.types)) {
      result.types.set(name, this.normalizeType(name, typeDef));
    }

    // Extract queries
    if (parsedSDL.queries) {
      for (const queryName of parsedSDL.queries) {
        const queryType = parsedSDL.types.get(queryName);
        if (queryType && queryType.kind === 'OBJECT') {
          result.queries.push({ name: queryName, type: queryType });
        }
      }
    }

    // Extract mutations
    if (parsedSDL.mutations) {
      for (const mutationName of parsedSDL.mutations) {
        const mutationType = parsedSDL.types.get(mutationName);
        if (mutationType && mutationType.kind === 'OBJECT') {
          result.mutations.push({ name: mutationName, type: mutationType });
        }
      }
    }

    // Extract subscriptions
    if (parsedSDL.subscriptions) {
      for (const subName of parsedSDL.subscriptions) {
        const subType = parsedSDL.types.get(subName);
        if (subType && subType.kind === 'OBJECT') {
          result.subscriptions.push({ name: subName, type: subType });
        }
      }
    }

    return result;
  }

  private buildParsedFromIntrospection(doc: any, raw: string): ParsedGraphQL {
    const schemaId = doc.__schema.id || 'introspection';
    
    const result: ParsedGraphQL = {
      schemaId,
      types: new Map(),
      queries: [],
      mutations: [],
      subscriptions: [],
    };

    // Build type map from introspection
    for (const type of doc.__schema.types) {
      if (!type.kind || !type.name) continue;
      
      const normalized = this.normalizeType(type.name, type);
      result.types.set(normalized.name, normalized);
    }

    // Extract queries (fields on Query root type)
    const queryType = doc.__schema.types.find((t: any) => t.name === 'Query');
    if (queryType && Array.isArray(queryType.fields)) {
      for (const field of queryType.fields) {
        result.queries.push({ name: field.name, type: this.normalizeType(field.name, field.type) });
      }
    }

    // Extract mutations (fields on Mutation root type)
    const mutationType = doc.__schema.types.find((t: any) => t.name === 'Mutation');
    if (mutationType && Array.isArray(mutationType.fields)) {
      for (const field of mutationType.fields) {
        result.mutations.push({ name: field.name, type: this.normalizeType(field.name, field.type) });
      }
    }

    // Extract subscriptions (fields on Subscription root type)
    const subscriptionType = doc.__schema.types.find((t: any) => t.name === 'Subscription');
    if (subscriptionType && Array.isArray(subscriptionType.fields)) {
      for (const field of subscriptionType.fields) {
        result.subscriptions.push({ name: field.name, type: this.normalizeType(field.name, field.type) });
      }
    }

    return result;
  }

  private parseSDL(sdl: string): any {
    // Simple SDL parser - extracts types and their fields
    const result: any = {
      types: new Map(),
      queries: [],
      mutations: [],
      subscriptions: [],
    };

    // Match type definitions
    const typeRegex = /type\s+(\w+)\s*\{/g;
    let match;
    
    while ((match = typeRegex.exec(sdl)) !== null) {
      const typeName = match[1];
      
      result.types.set(typeName, {
        name: typeName,
        kind: 'OBJECT',
        fields: [],
      });
    }

    // Match query/mutation/subscription root types
    const rootRegex = /type\s+(Query|Mutation|Subscription)\s*\{/g;
    
    while ((match = rootRegex.exec(sdl)) !== null) {
      const rootType = match[1];
      
      if (rootType === 'Query') {
        result.queries.push(match[1]);
      } else if (rootType === 'Mutation') {
        result.mutations.push(match[1]);
      } else if (rootType === 'Subscription') {
        result.subscriptions.push(match[1]);
      }