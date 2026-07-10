package polyglot.java;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.fasterxml.jackson.core.type.TypeReference;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Core data structures for OpenAPI/GraphQL schema comparison.
 */
public class SpecParser {

    /**
     * Represents a parsed OpenAPI 3.x specification.
     */
    public static class OpenApiSpec {
        private String openapiVersion;
        private Info info;
        private List<Schema> paths = new ArrayList<>();
        private Map<String, Schema> componentsSchemas = new HashMap<>();

        public String getOpenapiVersion() { return openapiVersion; }
        public Info getInfo() { return info; }
        public List<Schema> getPaths() { return paths; }
        public Map<String, Schema> getComponentsSchemas() { return componentsSchemas; }

        @Override
        public String toString() {
            return "OpenApiSpec{" +
                    "openapiVersion='" + openapiVersion + '\'' +
                    ", info=" + (info != null ? info : "null") +
                    ", pathsCount=" + paths.size() +
                    ", componentsSchemasCount=" + componentsSchemas.size() +
                    '}';
        }

        public static OpenApiSpec fromJson(String json) throws IOException {
            ObjectMapper mapper = new ObjectMapper();
            return mapper.readValue(json, OpenApiSpec.class);
        }

        public static OpenApiSpec fromYaml(String yaml) throws IOException {
            ObjectMapper mapper = new ObjectMapper(new YAMLFactory());
            return mapper.readValue(yaml, OpenApiSpec.class);
        }

        public static OpenApiSpec fromFile(Path path) throws IOException {
            String content = Files.readString(path);
            if (content.contains("openapi:")) {
                return fromYaml(content);
            } else {
                return fromJson(content);
            }
        }
    }

    /**
     * Represents a parsed GraphQL SDL schema.
     */
    public static class GraphQLSchema {
        private String sdl;
        private Map<String, TypeDefinition> types = new HashMap<>();
        private List<TypeDefinition> queries = new ArrayList<>();
        private List<TypeDefinition> mutations = new ArrayList<>();

        public String getSdl() { return sdl; }
        public Map<String, TypeDefinition> getTypes() { return types; }
        public List<TypeDefinition> getQueries() { return queries; }
        public List<TypeDefinition> getMutations() { return mutations; }

        @Override
        public String toString() {
            return "GraphQLSchema{" +
                    "sdl='" + sdl.substring(0, Math.min(sdl.length(), 50)) + '\'' +
                    ", typesCount=" + types.size() +
                    '}';
        }

        public static GraphQLSchema fromSdl(String sdl) throws IOException {
            // Parse SDL into type definitions
            GraphQLSchema schema = new GraphQLSchema();
            schema.sdl = sdl;

            // Simple regex-based parsing of SDL (production would use graphql-java parser)
            parseSDL(sdl, schema);
            
            return schema;
        }

        private static void parseSDL(String sdl, GraphQLSchema schema) {
            // Extract type definitions
            String[] lines = sdl.split("\n");
            for (String line : lines) {
                line = line.trim();
                
                // Skip comments and empty lines
                if (line.isEmpty() || line.startsWith("#")) continue;

                // Parse scalar types
                if (line.matches("scalar\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Scalar"));
                    continue;
                }

                // Parse enum types
                if (line.matches("enum\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Enum"));
                    continue;
                }

                // Parse input/output types
                if (line.matches("(input|output)\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Input"));
                    continue;
                }

                // Parse object types
                if (line.matches("type\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Object"));
                    continue;
                }

                // Parse union types
                if (line.matches("union\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Union"));
                    continue;
                }

                // Parse interface types
                if (line.matches("interface\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Interface"));
                    continue;
                }

                // Parse query/mutation types
                if (line.matches("(query|mutation)\\s+([a-zA-Z_][a-zA-Z0-9_]*)")) {
                    String name = extractName(line);
                    schema.types.put(name, new TypeDefinition(name, "Query"));
                    continue;
                }

                // Parse field definitions within types
                if (line.matches("field\\s+(\\w+)\\s*:\\s*(\\S+).*")) {
                    String typeName = extractName(line.substring(0, line.indexOf(":")));
                    TypeDefinition typeDef = schema.types.get(typeName);
                    if (typeDef != null) {
                        // Extract field name and type
                        int colonPos = line.indexOf(":", 5);
                        String fieldName = line.substring(6, colonPos).trim();
                        String fieldType = line.substring(colonPos + 1).trim().split("\\s+\\|")[0].trim();
                        
                        if (!typeDef.fields.isEmpty()) {
                            typeDef.fields.put(fieldName, new FieldDefinition(fieldType));
                        } else {
                            typeDef.fields.put(fieldName, new FieldDefinition(fieldType));
                        }
                    }
                }
            }

            // Extract query/mutation root types
            for (String name : schema.types.keySet()) {
                TypeDefinition def = schema.types.get(name);
                if ("Query".equals(def.kind) || "Mutation".equals(def.kind)) {
                    if ("Query".equals(def.kind)) {
                        schema.queries.add(def);
                    } else {
                        schema.mutations.add(def);
                    }
                }
            }
        }

        private static String extractName(String line) {
            int lastSpace = line.lastIndexOf(' ');
            return line.substring(lastSpace + 1).trim();
        }
    }

    /**
     * Represents a type definition in GraphQL schema.
     */
    public static class TypeDefinition {
        private String name;
        private String kind; // Scalar, Enum, Object, Input, Union, Interface, Query, Mutation
        private Map<String, FieldDefinition> fields = new HashMap<>();

        public TypeDefinition(String name, String kind) {
            this.name = name;
            this.kind = kind;
        }

        public String getName() { return name; }
        public String getKind() { return kind; }
        public Map<String, FieldDefinition> getFields() { return fields; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof TypeDefinition)) return false;
            TypeDefinition that = (TypeDefinition) o;
            return name != null ? name.equals(that.name) : that.name == null;
        }

        @Override
        public int hashCode() {
            return name != null ? name.hashCode() : 0;
        }

        @Override
        public String toString() {
            return "TypeDefinition{" +
                    "name='" + name + '\'' +
                    ", kind='" + kind + '\'' +
                    ", fieldsCount=" + fields.size() +
                    '}';
        }
    }

    /**
     * Represents a field definition in GraphQL schema.
     */
    public static class FieldDefinition {
        private String type;
        private boolean required = false;

        public FieldDefinition(String type) {
            this.type = type;
        }

        public String getType() { return type; }
        
        public void setRequired(boolean required) { this.required = required; }
        public boolean isRequired() { return required; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof FieldDefinition)) return false;
            FieldDefinition that = (FieldDefinition) o;
            return type != null ? type.equals(that.type) : that.type == null;
        }

        @Override
        public int hashCode() {
            return type != null ? type.hashCode() : 0;
        }

        @Override
        public String toString() {
            return "FieldDefinition{" +
                    "type='" + type + '\'' +
                    ", required=" + required +
                    '}';
        }
    }

    /**
     * Represents a detected breaking change.
     */
    public static class BreakingChange {
        private enum ChangeType {
            FIELD_REMOVED,
            FIELD_TYPE_CHANGED,
            REQUIRED_FIELD_ADDED,
            OPTIONAL_FIELD_REMOVED,
            TYPE_REMOVED,
            NEW_TYPE_ADDED,
            ENUM_VALUE_REMOVED,
            ENUM_VALUE_ADDED,
            INTERFACE_IMPLEMENTATION_CHANGED
        }

        private ChangeType type;
        private String typeName;
        private String fieldName;
        private String oldType;
        private String newType;
        private String details;

        public BreakingChange(ChangeType type) {
            this.type = type;
        }

        public ChangeType getType() { return type; }
        public String getTypeName() { return typeName; }
        public String getFieldName() { return fieldName; }
        public String getOldType() { return oldType; }
        public String getNewType() { return newType; }
        public String getDetails() { return details; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof BreakingChange)) return false;
            BreakingChange that = (BreakingChange) o;
            return type != null ? type.equals(that.type) : that.type == null;
        }

        @Override
        public int hashCode() {
            return type != null ? type.hashCode() : 0;
        }

        @Override
        public String toString() {
            return "BreakingChange{" +
                    "type=" + type +
                    ", typeName='" + typeName + '\'' +
                    ", fieldName='" + fieldName + '\'' +
                    ", oldType='" + oldType + '\'' +
                    ", newType='" + newType + '\'' +
                    '}';
        }
    }

    /**
     * Result of comparing two schema versions.
     */
    public static class DiffResult {
        private OpenApiSpec v1;
        private OpenApiSpec v2;
        private GraphQLSchema gqlV1;
        private GraphQLSchema gqlV2;
        private List<BreakingChange> changes = new ArrayList<>();

        public OpenApiSpec getV1() { return v1; }
        public void setV1(OpenApiSpec v1) { this.v1 = v1; }
        
        public OpenApiSpec getV2() { return v2; }
        public void setV2(OpenApiSpec v2) { this.v2 = v2; }

        public GraphQLSchema getGqlV1() { return gqlV1; }
        public void setGqlV1(GraphQLSchema gqlV1) { this.gqlV1 = gqlV1; }

        public GraphQLSchema getGqlV2() { return gqlV2; }
        public void setGqlV2(GraphQLSchema gqlV2) { this.gqlV2 = gqlV2; }

        public List<BreakingChange> getChanges() { return changes; }
        
        public boolean hasBreakingChanges() {
            return !changes.isEmpty();
        }

        @Override
        public String toString() {
            StringBuilder sb = new StringBuilder();
            sb.append("DiffResult{v1=").append(v1).append(", v2=").append(v2);
            if (gqlV1 != null) sb.append(", gqlV1=").append(gqlV1);
            if (gqlV2 != null) sb.append(", gqlV2=").append(gqlV2);
            sb.append("}");
            return sb.toString();
        }

        public static DiffResult create() {
            return new DiffResult();
        }
    }

    /**
     * Main parser and comparison engine.
     */
    public static class ParserEngine {

        private final ObjectMapper jsonMapper = new ObjectMapper();
        private final ObjectMapper yamlMapper = new ObjectMapper(new YAMLFactory());

        /**
         * Parse an OpenAPI spec from a file path.
         */
        public OpenApiSpec parseOpenApi(String filePath) throws IOException {
            Path path = Path.of(filePath);
            if (!Files.exists(path)) {
                throw new IOException("File not found: " + filePath);
            }
            return OpenApiSpec.fromFile(path);
        }

        /**
         * Parse a GraphQL SDL schema from string.
         */
        public GraphQLSchema parseGraphQLSdl(String sdl) throws IOException {
            if (sdl == null || sdl.trim().isEmpty()) {
                throw new IllegalArgumentException("Empty SDL provided");
            }
            return GraphQLSchema.fromSdl(sdl);
        }

        /**
         * Parse a GraphQL schema from file.
         */
        public GraphQLSchema parseGraphQLFile(String filePath) throws IOException {
            Path path = Path.of(filePath);
            if (!Files.exists(path)) {
                throw new IOException("File not found: " + filePath);
            }
            String content = Files.readString(path);
            return parseGraphQLSdl(content);
        }

        /**
         * Detect breaking changes between two OpenAPI specs.
         */
        public DiffResult compareOpenApi(OpenApiSpec v1, OpenApiSpec v2) {
            DiffResult result = DiffResult.create();
            result.setV1(v1);
            result.setV2(v2);

            // Compare paths (endpoints)
            Map<String, Schema> v1Paths = buildPathMap(v1.getPaths());
            Map<String, Schema> v2Paths = buildPathMap(v2.getPaths());

            // Check for removed paths
            for (String path : v1Paths.keySet()) {
                if (!v2Paths.containsKey(path)) {
                    BreakingChange change = new BreakingChange(BreakingChange.ChangeType.FIELD_REMOVED);
                    change.setTypeName("PATH");
                    change.setFieldName(path);
                    change.setOldType(v1Paths.get(path).toString());
                    result.getChanges().add(change);
                }
            }

            // Check for added paths (info only)
            for (String path : v2Paths.keySet()) {
                if (!v1Paths.containsKey(path)) {
                    BreakingChange change = new BreakingChange(BreakingChange.ChangeType.NEW_TYPE_ADDED);
                    change.setTypeName("PATH");
                    change.setFieldName(path);
                    result.getChanges().add(change);
                }
            }

            // Compare components schemas
            compareSchemas(v1.getComponentsSchemas(), v2.getComponentsSchemas(), 
                         "COMPONENT_SCHEMA", result);

            return result;
        }

        /**
         * Detect breaking changes between two GraphQL schemas.
         */
        public DiffResult compareGraphQL(GraphQLSchema v1, GraphQLSchema v2) {
            DiffResult result = DiffResult.create();
            result.setGqlV1(v1);
            result.setGqlV2(v2);

            // Compare types
            Map<String, TypeDefinition> v1Types = v1.getTypes();
            Map<String, TypeDefinition> v2Types = v2.getTypes();

            // Check for removed types (breaking)
            for (String typeName : v1Types.keySet()) {
                if (!v2Types.containsKey(typeName)) {
                    BreakingChange change = new BreakingChange(BreakingChange.ChangeType.TYPE_REMOVED);
                    change.setTypeName(typeName);
                    TypeDefinition def = v1Types.get(typeName);
                    change.setOldType(def.getKind());
                    result.getChanges().add(change);
                }
            }

            // Check for added types (info only)
            for (String typeName : v2Types.keySet()) {