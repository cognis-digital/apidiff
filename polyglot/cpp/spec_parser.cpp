#include <iostream>
#include <string>
#include <vector>
#include <map>
#include <optional>
#include <variant>
#include <sstream>
#include <regex>
#include <algorithm>
#include <memory>
#include <functional>
#include <stdexcept>

// ============================================================================
// Forward declarations and core types
// ============================================================================

namespace apidiff {

enum class HttpMethod : uint8_t {
    GET = 0, POST, PUT, DELETE, PATCH, HEAD, OPTIONS, TRACE, CONNECT
};

enum class GraphQLKind : uint8_t {
    SCALAR, OBJECT, INTERFACE, UNION, ENUM, INPUT_OBJECT, 
    DIRECTIVE, VARIATION, FRAGMENT_SPREAD, FRAGMENT_DEFINITION,
    QUERY, MUTATION, SUBSCRIPTION
};

struct ParseError {
    std::string message;
    int line = 0;
    int column = 0;
    
    bool operator==(const ParseError& other) const {
        return message == other.message && 
               line == other.line && 
               column == other.column;
    }
};

template<typename T>
struct Result {
    T value;
    std::optional<ParseError> error;
    
    bool has_value() const { return !error.has_value(); }
    bool has_error() const { return error.has_value(); }
    
    T& operator*() { return value; }
    const T& operator*() const { return value; }
    
    T* operator->() { return &value; }
    const T* operator->() const { return &value; }
};

template<typename T>
Result<T> ok(T&& v) {
    return Result<T>{std::move(v), std::nullopt};
}

template<typename T, typename E = ParseError>
Result<T> err(E e) {
    return Result<T>{T{}, std::optional<E>(e)};
}

// ============================================================================
// Minimal YAML/JSON parsing utilities (self-contained)
// ============================================================================

class YAMLParser {
public:
    static Result<std::map<std::string, std::variant<YAMLNode, ParseError>>> 
    parse_yaml(const std::string& yaml);
    
private:
    enum class NodeType : uint8_t {
        SCALAR, SEQUENCE, MAPPING, NULL, DOCUMENT_START, DOCUMENT_END
    };
    
    struct YAMLNode {
        NodeType type;
        std::string scalar_value;
        std::vector<YAMLNode> children;
        std::map<std::string, YAMLNode> mapping_children;
        
        bool is_scalar() const { return type == NodeType::SCALAR; }
        bool is_sequence() const { return type == NodeType::SEQUENCE; }
        bool is_mapping() const { return type == NodeType::MAPPING; }
    };
    
    static Result<YAMLNode> parse_yaml_node(const std::string& yaml, 
                                           size_t pos = 0);
};

class JSONParser {
public:
    static Result<std::map<std::string, std::variant<JSONValue, ParseError>>> 
    parse_json(const std::string& json);
    
private:
    enum class JSONType : uint8_t {
        OBJECT, ARRAY, STRING, NUMBER, BOOLEAN, NULL
    };
    
    struct JSONValue {
        JSONType type;
        std::string string_value;
        double number_value = 0.0;
        bool boolean_value = false;
        std::vector<JSONValue> array_children;
        std::map<std::string, JSONValue> object_children;
    };
    
    static Result<JSONValue> parse_json_value(const std::string& json, 
                                              size_t pos = 0);
};

// ============================================================================
// OpenAPI Specification Data Model
// ============================================================================

struct RequestBody {
    std::optional<std::map<std::string, YAMLNode>> content;
    bool required = false;
};

struct Parameter {
    std::string name;
    std::string in;  // "path", "query", "header", "cookie"
    std::optional<YAMLNode> schema;
    bool required = false;
    std::string description;
};

struct Operation {
    HttpMethod method;
    std::string operationId;
    std::vector<Parameter> parameters;
    RequestBody requestBody;
    std::map<std::string, YAMLNode> responses;
    std::optional<YAMLNode> requestExample;
    std::optional<YAMLNode> responseExamples;
};

struct PathItem {
    std::string path;
    std::vector<Operation> operations;
    std::optional<YAMLNode> summary;
    std::optional<YAMLNode> description;
    std::map<std::string, YAMLNode> servers;
};

struct OpenAPISpec {
    std::string info_title;
    std::optional<int> info_version;
    std::vector<PathItem> paths;
    std::map<std::string, YAMLNode> components_schemas;
    std::map<std::string, YAMLNode> components_parameters;
};

// ============================================================================
// GraphQL Schema Data Model
// ============================================================================

struct GraphQLField {
    std::optional<YAMLNode> type;
    std::vector<std::pair<std::string, YAMLNode>> arguments;
    bool is_deprecated = false;
    std::optional<std::string> description;
};

struct GraphQLType {
    std::string name;
    GraphQLKind kind;
    std::map<std::string, GraphQLField> fields;
    std::vector<YAMLNode> enum_values;
    std::vector<YAMLNode> interfaces;
    std::vector<YAMLNode> implements;
};

struct GraphQLSchema {
    std::optional<YAMLNode> operation_types;  // query, mutation, subscription
    std::map<std::string, YAMLNode> types;
    std::map<std::string, YAMLNode> directives;
};

// ============================================================================
// OpenAPI Parser Implementation
// ============================================================================

class OpenAPISpecParser {
public:
    Result<OpenAPISpec> parse(const std::string& yaml_or_json) {
        auto [root, err] = YAMLParser::parse_yaml(yaml_or_json);
        
        if (err.has_value()) {
            return err;
        }
        
        OpenAPISpec spec;
        extract_openapi_info(root, spec);
        extract_paths(root, spec);
        extract_components(root, spec);
        
        // Normalize paths: add leading slash if missing
        for (auto& path_item : spec.paths) {
            if (!path_item.path.empty() && !path_item.path.front().is_slash()) {
                path_item.path = "/" + path_item.path;
            }
        }
        
        return ok(spec);
    }
    
private:
    static bool is_slash(char c) { return c == '/'; }
    
    void extract_openapi_info(const YAMLNode& root, OpenAPISpec& spec) {
        auto info = root.mapping_children["info"];
        if (info.is_mapping()) {
            auto title = info.mapping_children["title"].scalar_value;
            spec.info_title = title;
            
            auto version_str = info.mapping_children["version"].scalar_value;
            if (!version_str.empty() && !isdigit(version_str.front())) {
                try {
                    spec.info_version = std::stoi(version_str);
                } catch (...) {}
            }
        }
    }
    
    void extract_paths(const YAMLNode& root, OpenAPISpec& spec) {
        auto paths_node = root.mapping_children["paths"];
        if (paths_node.is_mapping()) {
            for (const auto& [path_key, path_value] : paths_node.mapping_children) {
                PathItem path_item;
                path_item.path = path_key;
                
                // Extract common properties
                extract_path_common(path_value, path_item);
                
                // Extract operations
                if (path_value.is_mapping()) {
                    for (const auto& [method_key, method_value] : 
                         path_value.mapping_children) {
                        Operation operation;
                        operation.method = parse_http_method(method_key);
                        
                        // Extract operationId
                        auto op_id_node = method_value.mapping_children["operationId"];
                        if (op_id_node.is_scalar()) {
                            operation.operationId = op_id_node.scalar_value;
                        }
                        
                        // Extract parameters
                        extract_parameters(method_value, operation.parameters);
                        
                        spec.paths.push_back(path_item);
                    }
                }
            }
        }
    }
    
    static HttpMethod parse_http_method(const std::string& method) {
        if (method == "get") return HttpMethod::GET;
        if (method == "post") return HttpMethod::POST;
        if (method == "put") return HttpMethod::PUT;
        if (method == "delete") return HttpMethod::DELETE;
        if (method == "patch") return HttpMethod::PATCH;
        if (method == "head") return HttpMethod::HEAD;
        if (method == "options") return HttpMethod::OPTIONS;
        if (method == "trace") return HttpMethod::TRACE;
        if (method == "connect") return HttpMethod::CONNECT;
        return HttpMethod::GET; // default fallback
    }
    
    void extract_path_common(const YAMLNode& path_value, PathItem& path_item) {
        auto summary_node = path_value.mapping_children["summary"];
        if (summary_node.is_scalar()) {
            path_item.summary = summary_node;
        }
        
        auto description_node = path_value.mapping_children["description"];
        if (description_node.is_scalar()) {
            path_item.description = description_node.scalar_value;
        }
    }
    
    void extract_parameters(const YAMLNode& method_value, 
                           std::vector<Parameter>& parameters) {
        // Parameters can be in "parameters" array or inline with operation
        auto params_array = method_value.mapping_children["parameters"];
        
        if (params_array.is_sequence()) {
            for (const auto& param_node : params_array.children) {
                Parameter param;
                
                if (param_node.is_mapping()) {
                    // Extract parameter properties
                    auto name_node = param_node.mapping_children["name"];
                    if (name_node.is_scalar()) {
                        param.name = name_node.scalar_value;
                    }
                    
                    auto in_node = param_node.mapping_children["in"];
                    if (in_node.is_scalar()) {
                        param.in = in_node.scalar_value;
                    }
                    
                    auto required_node = param_node.mapping_children["required"];
                    if (required_node.is_scalar()) {
                        param.required = required_node.scalar_value == "true";
                    }
                }
                
                parameters.push_back(param);
            }
        }
    }
    
    void extract_components(const YAMLNode& root, OpenAPISpec& spec) {
        auto components = root.mapping_children["components"];
        
        if (components.is_mapping()) {
            // Extract schemas
            auto schemas_node = components.mapping_children["schemas"];
            if (schemas_node.is_mapping()) {
                for (const auto& [schema_name, schema_value] : 
                     schemas_node.mapping_children) {
                    spec.components_schemas[schema_name] = schema_value;
                }
            }
            
            // Extract parameters
            auto params_node = components.mapping_children["parameters"];
            if (params_node.is_mapping()) {
                for (const auto& [param_name, param_value] : 
                     params_node.mapping_children) {
                    spec.components_parameters[param_name] = param_value;
                }
            }
        }
    }
};

// ============================================================================
// GraphQL Parser Implementation
// ============================================================================

class GraphQLSchemaParser {
public:
    Result<GraphQLSchema> parse(const std::string& sdl) {
        auto [root, err] = YAMLParser::parse_yaml(sdl);
        
        if (err.has_value()) {
            return err;
        }
        
        GraphQLSchema schema;
        extract_operation_types(root, schema);
        extract_types(root, schema);
        extract_directives(root, schema);
        
        // Normalize type names: remove leading "type " prefix if present
        for (auto& [name, type_value] : schema.types) {
            if (!name.empty() && name.substr(0, 5) == "type ") {
                name = name.substr(5);
            } else if (!name.empty() && name.substr(0, 7) == "enum ") {
                name = name.substr(7);
            }
        }
        
        return ok(schema);
    }
    
private:
    void extract_operation_types(const YAMLNode& root, GraphQLSchema& schema) {
        auto operation_types_node = root.mapping_children["operationTypes"];
        
        if (operation_types_node.is_mapping()) {
            for (const auto& [op_type_key, op_value] : 
                 operation_types_node.mapping_children) {
                std::string op_name;
                
                // Parse operation type name (e.g., "query", "mutation")
                if (op_type_key.is_scalar()) {
                    op_name = op_type_key.scalar_value;
                } else if (op_type_key.is_mapping() && 
                           !op_type_key.mapping_children.empty()) {
                    auto name_node = op_type_key.mapping_children.begin()->first;
                    if (name_node.is_scalar()) {
                        op_name = name_node.scalar_value;
                    }
                }
                
                // Store operation type info
                schema.operation_types[op_name] = op_value;
            }
        }
    }
    
    void extract_types(const YAMLNode& root, GraphQLSchema& schema) {
        auto types_node = root.mapping_children["types"];
        
        if (types_node.is_mapping()) {
            for (const auto& [type_name, type_value] : 
                 types_node.mapping_children) {
                GraphQLType type;
                type.name = type_name;
                
                // Determine kind from name prefix
                if (type_name.substr(0, 5) == "enum ") {
                    type.kind = GraphQLKind::ENUM;
                } else if (type_name.substr(0, 13) == "input_object") {
                    type.kind = GraphQLKind::INPUT_OBJECT;
                } else if (type_name.substr(0, 6) == "union ") {
                    type.kind = GraphQLKind::UNION;
                } else if (type_name.substr(0, 8) == "interface") {
                    type.kind = GraphQLKind::INTERFACE;
                } else if (type_name.substr(0, 5) == "scalar") {
                    type.kind = GraphQLKind::SCALAR;
                } else if (type_name.substr(0, 7) == "directive") {
                    type.kind = GraphQLKind::DIRECTIVE;
                } else {
                    type.kind = GraphQLKind::OBJECT;
                }
                
                // Extract fields for object types
                auto fields_node = type_value.mapping_children["fields"];
                if (fields_node.is_mapping()) {
                    for (const auto& [field_name, field_value] : 
                         fields_node.mapping_children) {
                        GraphQLField field;
                        
                        if (field_value.is_mapping()) {
                            // Extract arguments
                            auto args_node = field_value.mapping_children["arguments"];
                            if (args_node.is_sequence()) {
                                for (const auto& arg_node : args_node.children) {
                                    std::string arg_name;
                                    
                                    if (arg_node.is_mapping() && 
                                        !arg_node.mapping_children.empty()) {
                                        auto name_node = 
                                            arg_node.mapping_children.begin()->first;
                                        if (name_node.is_scalar()) {
                                            arg_name = name_node.scalar_value;
                                        }
                                    }
                                    
                                    field.arguments.push_back(
                                        std::make_pair(arg_name, arg_node));
                                }
                            }
                            
                            // Extract type information
                            auto type_node = 
                                field_value.mapping_children["type"];
                            if (type_node.is_scalar()) {
                                field.type = type_node;
                            }
                        }
                        
                        type.fields[field_name] = field;
                    }
                }
                
                schema.types[type.name] = type_value;
            }
        }