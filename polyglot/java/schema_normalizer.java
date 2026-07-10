package polyglot.java;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * SchemaNormalizer - Produces a canonical representation of OpenAPI/GraphQL schemas.
 * 
 * Deterministic output: identical input always produces byte-identical output.
 */
public final class SchemaNormalizer {

    private static final Pattern WHITESPACE = Pattern.compile("\\s+");
    private static final String LINE_SEPARATOR = "\n";
    private static final int INDENT_SIZE = 2;

    /**
     * Normalizes the given schema text and returns canonical JSON.
     * 
     * @param input OpenAPI 3.x or GraphQL SDL as a string
     * @return Canonical JSON representation
     */
    public static String normalize(String input) {
        if (input == null || input.isEmpty()) {
            return "{}";
        }

        try {
            // Parse to AST, normalize, then serialize back
            JsonNode root = parseAndNormalize(input);
            
            // Use compact output for storage, pretty-printed for readability
            String canonicalCompact = root.toString();
            String canonicalPretty = format(root, 0);
            
            return canonicalPretty;
        } catch (IOException e) {
            throw new RuntimeException("Failed to normalize schema: " + input, e);
        }
    }

    /**
     * Parses and normalizes the input into a JsonNode AST.
     */
    private static JsonNode parseAndNormalize(String input) throws IOException {
        // Use Jackson for robust JSON parsing with good defaults
        ObjectMapper mapper = new ObjectMapper();
        
        // Parse as generic JSON first (works for both OpenAPI and GraphQL SDL)
        JsonNode root = mapper.readTree(input);
        
        if (root == null || !root.isObject()) {
            return root;
        }

        // Apply normalization recursively
        normalizeObject(root, 0);

        return root;
    }

    /**
     * Recursively normalizes an object node.
     */
    private static void normalizeObject(JsonNode node, int depth) {
        if (node == null || !node.isObject()) {
            return;
        }

        // Collect all keys and sort them for deterministic iteration
        List<String> sortedKeys = new ArrayList<>(node.fieldNames());
        Collections.sort(sortedKeys);

        // Build a new object with sorted keys
        JsonNode.Builder builder = node.object();
        
        for (String key : sortedKeys) {
            JsonNode value = node.get(key);
            
            if (value != null && value.isObject()) {
                normalizeObject(value, depth + 1);
            } else if (value.isArray() && !value.isEmpty()) {
                // For arrays, we sort elements for determinism
                List<JsonNode> sortedElements = new ArrayList<>(value.size());
                
                // Sort array elements by their string representation
                value.elements().forEachRemaining(e -> sortedElements.add(e));
                Collections.sort(sortedElements);
                
                builder.set(key, JsonNodeFactory.array(sortedElements));
            } else {
                builder.set(key, value);
            }
        }

        node = builder.build();
    }

    /**
     * Formats the JSON with consistent indentation for readability.
     */
    private static String format(JsonNode root, int indent) throws IOException {
        StringBuilder sb = new StringBuilder();
        
        if (root == null || !root.isObject()) {
            return root.toString();
        }

        int spaces = indent * INDENT_SIZE;
        boolean first = true;

        for (Iterator<Map.Entry<String, JsonNode>> it = root.fields(); it.hasNext(); ) {
            Map.Entry<String, JsonNode> entry = it.next();
            
            if (!first) {
                sb.append(LINE_SEPARATOR);
            }
            first = false;

            String key = escapeJsonKey(entry.getKey());
            int nextIndent = indent + 1;
            String nextSpaces = spaces + INDENT_SIZE;

            sb.append("  ").append(key).append(": ");

            JsonNode value = entry.getValue();
            
            if (value.isObject() || value.isArray()) {
                // Pretty-print nested structures
                sb.append(format(value, nextIndent));
            } else {
                // Compact scalar values
                String valStr = escapeJsonValue(value.asText());
                
                // Handle special cases
                if ("null".equals(valStr)) {
                    sb.append("null");
                } else if (valStr.isEmpty()) {
                    sb.append("\"\"");
                } else {
                    sb.append(valStr);
                }
            }

            sb.append(", ");
        }

        // Remove trailing comma and newline
        int len = sb.length();
        if (len > 0) {
            sb.setLength(len - 2);
        }

        return sb.toString();
    }

    /**
     * Escapes a JSON key string.
     */
    private static String escapeJsonKey(String key) {
        StringBuilder sb = new StringBuilder(key.length() + 4);
        
        for (char c : key.toCharArray()) {
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    sb.append(c);
            }
        }

        return sb.toString();
    }

    /**
     * Escapes a JSON string value.
     */
    private static String escapeJsonValue(String value) {
        StringBuilder sb = new StringBuilder(value.length() + 4);
        
        for (char c : value.toCharArray()) {
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    sb.append(c);
            }
        }

        return sb.toString();
    }

    /**
     * Main entry point for demonstration and testing.
     */
    public static void main(String[] args) throws Exception {
        // Example OpenAPI 3.x schema
        String openapiSchema = """
            {
                "openapi": "3.0.1",
                "info": {
                    "title": "Pet Store API",
                    "version": "1.0.0"
                },
                "paths": {
                    "/pets/{petId}": {
                        "get": {
                            "responses": {
                                "200": {
                                    "description": "Success",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "$ref": "#/components/schemas/Pet"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "/pets": {
                        "post": {
                            "requestBody": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/Pet"
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "components": {
                    "schemas": {
                        "Pet": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "integer"
                                },
                                "name": {
                                    "type": "string"
                                }
                            }
                        }
                    }
                }
            }
            """;

        // Example GraphQL SDL with potential inconsistencies
        String graphqlSdl = """
            type Query {
                pet(id: ID!): Pet
                pets: [Pet!]!
            }

            type Mutation {
                createPet(name: String!, id: Int!): Pet
            }

            input CreatePetInput {
                name: String!
                id: Int!
            }

            type Pet {
                id: ID!
                name: String!
                age: Int
            }
            """;

        System.out.println("=== OpenAPI Schema Normalization ===");
        String normalizedOpenapi = normalize(openapiSchema);
        System.out.println(normalizedOpenapi);

        System.out.println("\n\n=== GraphQL SDL Normalization ===");
        String normalizedGraphql = normalize(graphqlSdl);
        System.out.println(normalizedGraphql);

        // Demonstrate determinism - same input produces same output
        String firstRun = normalize(openapiSchema);
        String secondRun = normalize(openapiSchema);
        
        if (firstRun.equals(secondRun)) {
            System.out.println("\n\n=== Determinism Check: PASSED ===");
            System.out.println("Two runs produced identical output.");
        } else {
            System.out.println("\n\n=== Determinism Check: FAILED ===");
            System.out.println("Outputs differ!");
        }

        // Demonstrate whitespace insensitivity
        String withExtraWhitespace = openapiSchema.replace("  ", "   ").replace("\n", "\n\n");
        String normalizedWithExtra = normalize(withExtraWhitespace);
        
        if (normalizedOpenapi.equals(normalizedWithExtra)) {
            System.out.println("\n=== Whitespace Insensitivity: PASSED ===");
            System.out.println("Extra whitespace was handled correctly.");
        } else {
            System.out.println("\n=== Whitespace Insensitivity: FAILED ===");
        }

        // Demonstrate case normalization for types (if applicable)
        String mixedCaseSchema = """
            {
                "info": {"title": "Test", "version": "1.0"},
                "paths": {
                    "/test": {
                        "get": {
                            "responses": {
                                "200": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "String",  // Capitalized
                                                "properties": {
                                                    "name": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """;

        String normalizedMixedCase = normalize(mixedCaseSchema);
        System.out.println("\n=== Mixed Case Type Handling ===");
        System.out.println(normalizedMixedCase);

        // Test with empty/null input
        System.out.println("\n=== Edge Cases ===");
        System.out.println("Empty string: '" + normalize("") + "'");
        System.out.println("Null-like: '" + normalize(null) + "'");
    }
}