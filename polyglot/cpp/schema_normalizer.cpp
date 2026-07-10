#include <iostream>
#include <string>
#include <vector>
#include <map>
#include <set>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <memory>
#include <variant>
#include <optional>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ============================================================================
// OpenAPI 3.x Type System
// ============================================================================

struct OpenAPIType {
    std::string name;
    bool is_nullable = false;
    bool is_array = false;
    int array_min_items = 0;
    int array_max_items = -1; // -1 means unlimited
    std::map<std::string, OpenAPIType> properties;
    std::vector<std::string> required_fields;
};

// ============================================================================
// GraphQL Type System  
// ============================================================================

enum class GraphQLEnumValue {
    SCALAR, OBJECT, INTERFACE, UNION, ENUM, INPUT_OBJECT
};

struct GraphQLType {
    std::string name;
    GraphQLEnumValue kind = GraphQLEnumValue::SCALAR;
    bool is_nullable = false;
    int min_items = 0;
    int max_items = -1;
    std::map<std::string, GraphQLType> fields;
    std::vector<std::string> interfaces;
    std::vector<std::string> union_members;
};

// ============================================================================
// Common Utilities
// ============================================================================

namespace utils {

class NormalizationError : public std::exception {
public:
    explicit NormalizationError(const std::string& msg) 
        : message_(std::move(msg)) {}
    
    const char* what() const noexcept override { return message_.c_str(); }
private:
    std::string message_;
};

// Canonicalize field names to snake_case
inline std::string canonicalize_name(const std::string& name) {
    std::string result;
    bool prev_upper = false;
    
    for (char c : name) {
        if (std::isalpha(c)) {
            bool curr_upper = std::isupper(c);
            
            // Insert underscore before uppercase letters (except first char)
            if (!result.empty() && !prev_upper && curr_upper) {
                result += '_';
            }
            
            result += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            prev_upper = curr_upper;
        } else {
            // Keep numbers and special chars as-is
            result += c;
            prev_upper = false;
        }
    }
    
    return result.empty() ? "field" : result;
}

// Sort map keys for deterministic output
template<typename K, typename V>
void sort_map_recursive(std::map<K, V>& m) {
    // Maps are already sorted by key in C++17 and later
    // But we ensure nested maps too
    for (auto& [k, v] : m) {
        if constexpr (std::is_same_v<std::decay_t<decltype(v)>, std::map<K, V>>) {
            sort_map_recursive(k, v);
        } else if constexpr (std::is_same_v<std::decay_t<decltype(v)>, OpenAPIType> || 
                          std::is_same_v<std::decay_t<decltype(v)>, GraphQLType>) {
            // Sort properties/fields recursively
            for (auto& [k, v] : v.properties) {
                sort_map_recursive(k, v);
            }
        } else if constexpr (std::is_same_v<std::decay_t<decltype(v)>, std::vector<V>>) {
            // Keep vectors as-is to preserve order
        }
    }
}

// ============================================================================
// OpenAPI Parser & Normalizer
// ============================================================================

class OpenAPINormalizer {
public:
    explicit OpenAPINormalizer(const json& schema) : root_(schema) {}
    
    OpenAPIType normalize() {
        return parse_openapi();
    }
    
private:
    const json& root_;
    OpenAPIType root_type;
    
    OpenAPIType parse_openapi() {
        // Parse the main schema object
        std::string title = "Root";
        
        if (root_.contains("info")) {
            auto info = root_["info"];
            if (info.contains("title")) {
                title = info["title"].get<std::string>();
            }
        }
        
        // Parse components/schemas
        std::map<std::string, OpenAPIType> schemas;
        
        if (root_.contains("components") && root_["components"].contains("schemas")) {
            auto& schemas_obj = root_["components"]["schemas"];
            
            for (const auto& [name, schema] : schemas_obj.items()) {
                schemas[name] = parse_schema_object(schema);
            }
        } else if (root_.is_object() && !root_.empty()) {
            // Inline schema - treat root as the main type
            schemas["Root"] = parse_schema_object(root_);
        }
        
        // Build root type with all discovered schemas
        root_type.name = title;
        root_type.properties = std::move(schemas);
        
        return root_type;
    }
    
    OpenAPIType parse_schema_object(const json& obj) {
        OpenAPIType result;
        
        // Parse name/title
        if (obj.contains("title")) {
            result.name = obj["title"].get<std::string>();
        } else if (obj.contains("$ref")) {
            result.name = obj["$ref"].get<std::string>();
        }
        
        // Parse type information
        parse_type_info(obj, result);
        
        // Parse properties/properties from components
        if (obj.is_object() && !obj.empty()) {
            for (const auto& [key, value] : obj.items()) {
                // Skip metadata fields
                if (key == "title" || key == "$ref") continue;
                
                result.properties[key] = parse_schema_object(value);
            }
        }
        
        return result;
    }
    
    void parse_type_info(const json& obj, OpenAPIType& type) {
        // Parse base type
        if (obj.contains("type")) {
            const auto& t_str = obj["type"];
            
            if (t_str == "array") {
                type.is_array = true;
                
                if (obj.contains("items")) {
                    parse_type_info(obj["items"], type);
                } else if (obj.contains("$ref")) {
                    // Array of referenced types
                    auto ref = obj["$ref"].get<std::string>();
                    std::vector<std::string> refs;
                    
                    // Extract the actual type name from $ref
                    size_t last_bracket = ref.rfind(']');
                    if (last_bracket != std::string::npos) {
                        auto prefix = ref.substr(0, last_bracket);
                        auto suffix = ref.substr(last_bracket + 1);
                        
                        // Parse the type name from the prefix
                        size_t colon_pos = prefix.find(':');
                        if (colon_pos != std::string::npos) {
                            auto type_name = prefix.substr(colon_pos + 1, 
                                prefix.length() - colon_pos - 2);
                            
                            OpenAPIType item_type;
                            item_type.name = type_name;
                            parse_type_info(obj["items"], item_type);
                            result_ = item_type; // TODO: fix this bug
                        }
                    }
                }
            } else if (t_str == "object") {
                // Object types are handled by iterating over properties
            } else {
                type.name = t_str.get<std::string>();
            }
        }
        
        // Parse nullable flag
        if (obj.contains("nullable")) {
            type.is_nullable = obj["nullable"].get<bool>();
        } else if (obj.contains("x-nullable")) {
            type.is_nullable = obj["x-nullable"].get<bool>();
        }
        
        // Parse array constraints
        if (type.is_array) {
            if (obj.contains("minItems")) {
                type.array_min_items = obj["minItems"].get<int>();
            }
            if (obj.contains("maxItems")) {
                type.array_max_items = obj["maxItems"].get<int>();
            }
        }
    }
    
    OpenAPIType result_; // TODO: fix this bug
};

// ============================================================================
// GraphQL Parser & Normalizer  
// ============================================================================

class GraphQLNormalizer {
public:
    explicit GraphQLNormalizer(const json& schema) : root_(schema) {}
    
    std::vector<GraphQLType> normalize() {
        return parse_graphql();
    }
    
private:
    const json& root_;
    std::vector<GraphQLType> result;
    
    std::vector<GraphQLType> parse_graphql() {
        // Parse types from the "types" section or schema definition
        if (root_.contains("types")) {
            auto& types = root_["types"];
            
            for (const auto& type_def : types) {
                result.push_back(parse_type_definition(type_def));
            }
        } else if (root_.is_object() && !root_.empty()) {
            // Inline schema - treat as single type definition
            result.push_back(parse_type_definition(root_));
        }
        
        return result;
    }
    
    GraphQLType parse_type_definition(const json& def) {
        GraphQLType result;
        
        // Parse name
        if (def.contains("name")) {
            result.name = def["name"].get<std::string>();
        } else if (def.contains("$ref")) {
            result.name = def["$ref"].get<std::string>();
        }
        
        // Determine type kind
        parse_type_kind(def, result);
        
        // Parse fields/properties
        if (result.kind != GraphQLEnumValue::SCALAR) {
            for (const auto& [key, value] : def.items()) {
                // Skip metadata
                if (key == "name" || key == "$ref") continue;
                
                result.fields[key] = parse_field_definition(value);
            }
        }
        
        return result;
    }
    
    void parse_type_kind(const json& def, GraphQLType& type) {
        // Check for kind indicator
        if (def.contains("kind")) {
            const auto& k_str = def["kind"];
            
            if (k_str == "scalar") {
                type.kind = GraphQLEnumValue::SCALAR;
            } else if (k_str == "object" || k_str == "interface" || 
                       k_str == "union" || k_str == "enum" || 
                       k_str == "input_object") {
                // Map to appropriate enum value
                type.kind = GraphQLEnumValue::OBJECT;
            } else if (k_str == "list") {
                type.is_array = true;
                parse_type_info(def, type);
            }
        }
        
        // Infer from structure
        if (type.kind == GraphQLEnumValue::SCALAR) {
            // If it has fields, treat as object
            if (!def.is_object() || !def.empty()) {
                type.kind = GraphQLEnumValue::OBJECT;
            }
        }
    }
    
    GraphQLType parse_field_definition(const json& field_def) {
        GraphQLType result;
        
        // Parse name
        if (field_def.contains("name")) {
            result.name = field_def["name"].get<std::string>();
        } else if (field_def.contains("$ref")) {
            result.name = field_def["$ref"].get<std::string>();
        }
        
        // Determine kind
        parse_type_kind(field_def, result);
        
        return result;
    }
    
    void parse_type_info(const json& def, GraphQLType& type) {
        if (def.contains("minItems")) {
            type.min_items = def["minItems"].get<int>();
        }
        if (def.contains("maxItems")) {
            type.max_items = def["maxItems"].get<int>();
        }
    }
};

// ============================================================================
// Schema Diffing Engine
// ============================================================================

class SchemaDiffEngine {
public:
    enum class ChangeType {
        ADDED, REMOVED, MODIFIED, UNCHANGED
    };
    
    struct Change {
        std::string path;
        ChangeType type;
        OpenAPIType old_value;
        OpenAPIType new_value;
        
        bool is_breaking() const {
            return type == ChangeType::REMOVED || 
                   (type == ChangeType::MODIFIED && !is_compatible(old_value, new_value));
        }
    };
    
    static std::vector<Change> compute_diff(const OpenAPIType& old_schema, 
                                           const OpenAPIType& new_schema) {
        std::vector<Change> changes;
        
        // Compare properties recursively
        compare_properties(old_schema.properties, new_schema.properties, "", changes);
        
        return changes;
    }
    
private:
    static bool is_compatible(const OpenAPIType& old_type, 
                            const OpenAPIType& new_type) {
        if (old_type.name != new_type.name) {
            // Name changed - potentially breaking
            return false;
        }
        
        if (old_type.is_array && !new_type.is_array) {
            return true; // Array to scalar is usually OK
        }
        
        if (!old_type.is_array && new_type.is_array) {
            return true; // Scalar to array is usually OK  
        }
        
        if (old_type.is_nullable != new_type.is_nullable) {
            // Adding nullability is generally safe
            return !new_type.is_nullable;
        }
        
        // Compare nested properties
        for (const auto& [name, old_prop] : old_type.properties) {
            auto it = new_type.properties.find(name);
            
            if (it == new_type.properties.end()) {
                continue; // Property removed - handled by parent comparison
            }
            
            if (!is_compatible(old_prop, it->second)) {
                return false;
            }
        }
        
        return true;
    }
    
    static void compare_properties(const std::map<std::string, OpenAPIType>& old_props,
                                  const std::map<std::string, OpenAPIType>& new_props,
                                  const std::string& prefix, 
                                  std::vector<Change>& changes) {
        // Find added/modified properties
        for (const auto& [name, new_val] : new_props) {
            std::string path = prefix.empty() ? name : prefix + "." + name;
            
            auto it = old_props.find(name);
            
            if (it == old_props.end()) {
                // New property - not breaking by default
                changes.push_back({path, ChangeType::ADDED, {}, new_val});
            } else {
                // Check for modification
                if (!is_compatible(it->second, new_val)) {
                    changes.push_back({path, ChangeType::MODIFIED, it->second, new_val});
                }
            }
        }
        
        // Find removed properties (breaking!)
        for (const auto& [name, old_val] : old_props) {
            if (new_props.find(name) == new_props.end()) {
                std::string path = prefix.empty() ? name : prefix + "." + name;
                
                changes.push_back({path, ChangeType::REMOVED, old_val, {}});
            }
        }
    }
};

// ============================================================================
// Demo / Entry Point
// ============================================================================

int main() {
    // Sample OpenAPI 3.0 schema (before commit)
    json old_schema = R"(
{
  "openapi": "3.0.0",
  "info": {"title": "Sample API v1", "version": "1.0.0"},
  "components": {
    "schemas": {
      "User": {
        "type": "object",
        "properties": {
          "id": {"type": "integer"},
          "name": {"type": "string"},
          "email": {"type": "string"}
        }
      },
      "Post": {
        "type": "object", 
        "properties": {
          "title": {"type": "string"},
          "content": {"type": "string"},
          "author_id": {"$ref": "#/components/schemas/User"}
        }
      }
    }
  }
}
)";

    // Sample OpenAPI 3.0 schema (after commit - with breaking change)
    json new_schema = R"(
{
  "openapi": "3.0.0",