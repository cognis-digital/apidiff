using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace polyglot.csharp
{
    // ============================================================================
    // OPENAPI 3.0 PARSER
    // ============================================================================

    /// <summary>
    /// Represents a parsed OpenAPI specification document.
    /// </summary>
    [JsonSerializable(typeof(OpenApiSpec))]
    public partial record OpenApiSpec
    {
        [JsonPropertyName("openapi")] public string? Version { get; init; }
        [JsonPropertyName("info")] public Info? Info { get; init; }
        [JsonPropertyName("paths")] public Dictionary<string, PathItem>? Paths { get; init; }
        [JsonPropertyName("components")] public Components? Components { get; init; }
    }

    /// <summary>
    /// Represents a path item in the OpenAPI spec.
    /// </summary>
    [JsonSerializable(typeof(PathItem))]
    public partial record PathItem
    {
        [JsonPropertyName("get")] public Operation? Get { get; init; }
        [JsonPropertyName("post")] public Operation? Post { get; init; }
        [JsonPropertyName("put")] public Operation? Put { get; init; }
        [JsonPropertyName("delete")] public Operation? Delete { get; init; }
        [JsonPropertyName("patch")] public Operation? Patch { get; init; }
        [JsonPropertyName("options")] public Operation? Options { get; init; }
        [JsonPropertyName("head")] public Operation? Head { get; init; }
        [JsonPropertyName("trace")] public Operation? Trace { get; init; }

        /// <summary>
        /// Gets all HTTP methods available for this path.
        /// </summary>
        public IEnumerable<Operation> GetAllOperations() =>
            Get?.AllOf ?? Enumerable.Empty<Operation>();

        /// <summary>
        /// Gets the operation for a specific HTTP method, or null if not found.
        /// </summary>
        public Operation? TryGetOperation(string httpMethod) =>
            httpMethod.ToLowerInvariant() switch
            {
                "get" => Get,
                "post" => Post,
                "put" => Put,
                "delete" => Delete,
                "patch" => Patch,
                "options" => Options,
                "head" => Head,
                "trace" => Trace,
                _ => null,
            };

        /// <summary>
        /// Gets all unique paths from this path item.
        /// </summary>
        public static IEnumerable<string> GetAllPaths(IEnumerable<PathItem?> items) =>
            items?.SelectMany(p => p.GetAllOperations())
                  .Select(o => o.PathTemplate)
                  .Distinct() ?? Enumerable.Empty<string>();
    }

    /// <summary>
    /// Represents an HTTP operation in the OpenAPI spec.
    /// </summary>
    [JsonSerializable(typeof(Operation))]
    public partial record Operation
    {
        [JsonPropertyName("operationId")] public string? OperationId { get; init; }
        [JsonPropertyName("summary")] public string? Summary { get; init; }
        [JsonPropertyName("description")] public string? Description { get; init; }
        [JsonPropertyName("parameters")] public List<Parameter>? Parameters { get; init; }
        [JsonPropertyName("requestBody")] public RequestBody? RequestBody { get; init; }
        [JsonPropertyName("responses")] public Dictionary<string, Response>? Responses { get; init; }

        /// <summary>
        /// Gets the path template for this operation.
        /// </summary>
        public string PathTemplate => GetParentPath() ?? "";

        private static string? GetParentPath()
        {
            var stack = new Stack<PathItem>();
            while (true)
            {
                if (stack.Count == 0) return null;
                var parent = stack.Pop();
                if (parent is Operation operation && operation.PathTemplate != null)
                    return operation.PathTemplate;

                // Try to get the path from the parent PathItem
                // This requires walking back through the spec structure
            }
        }
    }

    /// <summary>
    /// Represents a parameter in an OpenAPI operation.
    /// </summary>
    [JsonSerializable(typeof(Parameter))]
    public partial record Parameter
    {
        [JsonPropertyName("name")] public string? Name { get; init; }
        [JsonPropertyName("in")] public string? In { get; init; }
        [JsonPropertyName("schema")] public Schema? Schema { get; init; }
        [JsonPropertyName("required")] public bool Required { get; init; }

        /// <summary>
        /// Gets the parameter type.
        /// </summary>
        public string Type => Schema?.Type ?? "string";

        /// <summary>
        /// Checks if this is a path parameter (used in URL templating).
        /// </summary>
        public bool IsPathParameter() => In == "path";

        /// <summary>
        /// Gets the JSON schema properties for this parameter.
        /// </summary>
        public Dictionary<string, object>? GetProperties() => Schema?.Properties;
    }

    /// <summary>
    /// Represents a request body in an OpenAPI operation.
    /// </summary>
    [JsonSerializable(typeof(RequestBody))]
    public partial record RequestBody
    {
        [JsonPropertyName("content")] public Dictionary<string, MediaType>? Content { get; init; }

        /// <summary>
        /// Gets the schema for the request body content.
        /// </summary>
        public Schema? GetSchema() => Content?.Values.FirstOrDefault()?.Schema;

        /// <summary>
        /// Gets all schemas from this request body.
        /// </summary>
        public IEnumerable<Schema?> GetAllSchemas() =>
            Content?.SelectMany(m => m.Schema) ?? Enumerable.Empty<Schema?>();
    }

    /// <summary>
    /// Represents a response in an OpenAPI operation.
    /// </summary>
    [JsonSerializable(typeof(Response))]
    public partial record Response
    {
        [JsonPropertyName("content")] public Dictionary<string, MediaType>? Content { get; init; }

        /// <summary>
        /// Gets the schema for this response content.
        /// </summary>
        public Schema? GetSchema() => Content?.Values.FirstOrDefault()?.Schema;

        /// <summary>
        /// Checks if this is a success response (2xx).
        /// </summary>
        public bool IsSuccessResponse() => int.TryParse(Key, out var code) && code >= 200 && code < 300;
    }

    /// <summary>
    /// Represents media type information in an OpenAPI spec.
    /// </summary>
    [JsonSerializable(typeof(MediaType))]
    public partial record MediaType
    {
        [JsonPropertyName("schema")] public Schema? Schema { get; init; }
        [JsonPropertyName("examples")] public List<Example>? Examples { get; init; }

        /// <summary>
        /// Gets all examples from this media type.
        /// </summary>
        public IEnumerable<object?> GetAllExamples() =>
            Examples?.Select(e => e.Value) ?? Enumerable.Empty<object?>();
    }

    /// <summary>
    /// Represents a JSON schema in an OpenAPI spec.
    /// </summary>
    [JsonSerializable(typeof(Schema))]
    public partial record Schema
    {
        [JsonPropertyName("type")] public string? Type { get; init; }
        [JsonPropertyName("properties")] public Dictionary<string, Schema>? Properties { get; init; }
        [JsonPropertyName("required")] public List<string>? Required { get; init; }
        [JsonPropertyName("allOf")] public List<Schema>? AllOf { get; init; }
        [JsonPropertyName("oneOf")] public List<Schema>? OneOf { get; init; }
        [JsonPropertyName("anyOf")] public List<Schema>? AnyOf { get; init; }
        [JsonPropertyName("items")] public Schema? Items { get; init; }

        /// <summary>
        /// Gets the schema type as a set of possible types.
        /// </summary>
        public HashSet<string> GetTypes() => Type != null ? new HashSet<string>(Type.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)) : new();

        /// <summary>
        /// Checks if this schema is an object with properties.
        /// </summary>
        public bool IsObjectSchema() => Type == "object" || Properties?.Count > 0;

        /// <summary>
        /// Gets all property names from this schema (including nested ones).
        /// </summary>
        public IEnumerable<string> GetAllPropertyNames()
        {
            var queue = new Queue<(Dictionary<string, Schema>, string)>();
            if (Properties != null)
                foreach (var kvp in Properties)
                    queue.Enqueue((kvp.Value, kvp.Key));

            while (queue.Count > 0)
            {
                var (schema, _) = queue.Dequeue();
                if (schema?.Properties != null)
                    foreach (var kvp in schema.Properties)
                        queue.Enqueue((kvp.Value, kvp.Key));
            }

            return queue.SelectMany(t => t.Item2);
        }
    }

    /// <summary>
    /// Represents a component in an OpenAPI spec.
    /// </summary>
    [JsonSerializable(typeof(Components))]
    public partial record Components
    {
        [JsonPropertyName("schemas")] public Dictionary<string, Schema>? Schemas { get; init; }
        [JsonPropertyName("parameters")] public Dictionary<string, Parameter>? Parameters { get; init; }

        /// <summary>
        /// Gets all schemas from components.
        /// </summary>
        public IEnumerable<Schema?> GetAllSchemas() =>
            Schemas?.SelectMany(s => s.Value) ?? Enumerable.Empty<Schema?>();
    }

    /// <summary>
    /// Represents an example in an OpenAPI spec.
    /// </summary>
    [JsonSerializable(typeof(Example))]
    public partial record Example
    {
        [JsonPropertyName("value")] public object? Value { get; init; }
        [JsonPropertyName("externalValue")] public string? ExternalValue { get; init; }

        /// <summary>
        /// Gets the example value as a string.
        /// </summary>
        public string? GetValueString() => Value?.ToString();
    }

    // ============================================================================
    // GRAPHQL PARSER
    // ============================================================================

    /// <summary>
    /// Represents a parsed GraphQL schema document.
    /// </summary>
    [JsonSerializable(typeof(GraphQlSchema))]
    public partial record GraphQlSchema
    {
        [JsonPropertyName("__schema")] public SchemaMeta? __Schema { get; init; }

        /// <summary>
        /// Gets all types defined in this schema.
        /// </summary>
        public IEnumerable<TypeDefinition?> GetAllTypes() =>
            __Schema?.types ?? Enumerable.Empty<TypeDefinition?>();

        /// <summary>
        /// Gets the root query type.
        /// </summary>
        public TypeDefinition? GetQueryType() =>
            __Schema?.queryType?.name != null ? GetTypeByName(__Schema.queryType.name) : null;

        /// <summary>
        /// Gets the root mutation type.
        /// </summary>
        public TypeDefinition? GetMutationType() =>
            __Schema?.mutationType?.name != null ? GetTypeByName(__Schema.mutationType.name) : null;

        /// <summary>
        /// Gets the root subscription type.
        /// </summary>
        public TypeDefinition? GetSubscriptionType() =>
            __Schema?.subscriptionType?.name != null ? GetTypeByName(__Schema.subscriptionType.name) : null;

        private TypeDefinition? GetTypeByName(string name) =>
            GetAllTypes().FirstOrDefault(t => t.name == name);
    }

    /// <summary>
    /// Represents a type definition in a GraphQL schema.
    /// </summary>
    [JsonSerializable(typeof(TypeDefinition))]
    public partial record TypeDefinition
    {
        [JsonPropertyName("kind")] public string? Kind { get; init; }
        [JsonPropertyName("name")] public string? Name { get; init; }
        [JsonPropertyName("fields")] public List<FieldDefinition>? Fields { get; init; }

        /// <summary>
        /// Gets all fields from this type (including nested).
        /// </summary>
        public IEnumerable<FieldDefinition?> GetAllFields() =>
            Fields?.SelectMany(f => f) ?? Enumerable.Empty<FieldDefinition?>();

        /// <summary>
        /// Checks if this is an input type (used for arguments).
        /// </summary>
        public bool IsInputType() => Kind == "INPUT_OBJECT";

        /// <summary>
        /// Gets the fields that are required.
        /// </summary>
        public IEnumerable<FieldDefinition?> GetRequiredFields() =>
            Fields?.Where(f => f.isRequired) ?? Enumerable.Empty<FieldDefinition?>();
    }

    /// <summary>
    /// Represents a field definition in a GraphQL schema.
    /// </summary>
    [JsonSerializable(typeof(FieldDefinition))]
    public partial record FieldDefinition
    {
        [JsonPropertyName("name")] public string? Name { get; init; }
        [JsonPropertyName("type")] public TypeRef? Type { get; init; }
        [JsonPropertyName("args")] public List<ArgumentDefinition>? Args { get; init; }

        /// <summary>
        /// Gets the field type name.
        /// </summary>
        public string TypeName => Type?.name ?? "";

        /// <summary>
        /// Checks if this is a list type.
        /// </summary>
        public bool IsListType() => Type?.type != null && Type.type == "LIST";

        /// <summary>
        /// Gets the inner type name for list types.
        /// </summary>
        public string? GetInnerTypeName() => IsListType() ? Type?.innerType?.name : null;

        /// <summary>
        /// Checks if this field is required (non-null).
        /// </summary>
        public bool IsRequired() => Type?.type != null && Type.type == "NON_NULL";

        /// <summary>
        /// Gets the argument names for this field.
        /// </summary>
        public IEnumerable<string> GetArgumentNames() =>
            Args?.Select(a => a.name) ?? Enumerable.Empty<string>();
    }

    /// <summary>
    /// Represents a type reference in a GraphQL schema.
    /// </summary>
    [JsonSerializable(typeof(TypeRef))]
    public partial record TypeRef
    {
        [JsonPropertyName("name")] public string? Name { get; init; }
        [JsonPropertyName("type")] public string? Type { get; init; }
        [JsonPropertyName("innerType")] public TypeRef? InnerType { get; init; }

        /// <summary>
        /// Gets the full type name including wrapper types.
        /// </summary>
        public string GetFullTypeName()
        {
            var parts = new List<string>();
            while (true)
            {
                if (InnerType != null && InnerType.Name != null)
                    parts.Insert(0, InnerType.Name);

                if (Type == "NON_NULL")
                    parts.Add("NonNull");
                else if (Type == "LIST")
                    parts.Add("List");
                else
                    break;

                InnerType = InnerType?.InnerType;
            }

            return string.Join(".", parts) + "." + Name ?? "";
        }
    }

    /// <summary>
    /// Represents an argument definition in a GraphQL schema.
    /// </summary>
    [JsonSerializable(typeof(ArgumentDefinition))]
    public partial record ArgumentDefinition
    {
        [JsonPropertyName("name")] public string? Name { get; init; }
        [JsonPropertyName("type")] public TypeRef? Type { get; init; }

        /// <summary>
        /// Gets the argument type name.
        /// </summary>
        public string TypeName => Type?.name ?? "";

        /// <summary>
        /// Checks if this argument is required (non-null).
        /// </summary>
        public bool IsRequired() => Type?.type != null && Type.type == "NON_NULL";
    }

    /// <summary>
    /// Represents schema metadata in a GraphQL schema.
    /// </summary>
    [JsonSerializable(typeof(SchemaMeta))]
    public partial record SchemaMeta
    {
        [JsonPropertyName("queryType")] public QueryRef? queryType { get; init; }
        [JsonPropertyName("mutationType")] public QueryRef? mutationType { get; init; }
        [JsonPropertyName("subscriptionType")] public QueryRef? subscription