/*
 * polyglot/c/schema_normalizer.c
 * 
 * Schema normalizer for apidiff - breaking-change detector tool.
 * Parses OpenAPI 3.x and GraphQL SDL into canonical representations.
 */

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>
#include <limits.h>

/* ==================== CONFIGURATION ==================== */

#define MAX_SCHEMA_SIZE    (16 * 1024)   /* 16KB per schema */
#define MAX_PATH_DEPTH     32             /* Nested object depth limit */
#define HASH_SEED          0x9E3779B9ULL  /* Golden ratio for hashing */

/* ==================== TYPES ==================== */

typedef enum {
    NORM_OPENAPI,
    NORM_GRAPHQL
} norm_type_t;

typedef struct {
    char *raw_data;
    size_t raw_len;
    norm_type_t type;
    bool valid;
    int parse_error;
    union {
        /* OpenAPI 3.x fields */
        struct {
            char *info_title;
            char *info_version;
            char *servers_url;
            size_t paths_count;
            void **paths;
        } openapi;
        
        /* GraphQL SDL fields */
        struct {
            char *schema_id;
            size_t types_count;
            void **types;
        } graphql;
    };
} normalized_schema_t;

/* ==================== UTILITY FUNCTIONS ==================== */

static inline unsigned long hash_combine(unsigned long h, unsigned char c)
{
    h ^= (unsigned long)c * 0x517CC1B7ULL;
    h *= 0xFF9E263DULL;
    return h ^ (h >> 47);
}

static inline unsigned long hash_string(const char *s, size_t len)
{
    unsigned long h = HASH_SEED;
    for (size_t i = 0; i < len && s[i]; i++) {
        h = hash_combine(h, (unsigned char)s[i]);
    }
    return h ^ (h >> 31);
}

static inline bool is_whitespace(char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

/* ==================== OPENAPI PARSER ==================== */

typedef struct {
    char *title;
    char *version;
    char *url;
} server_info_t;

static int parse_openapi_version(const char *json, size_t len)
{
    const char *p = strstr(json, "\"info\"");
    if (!p) return -1;
    
    p += 5;
    while (*p && is_whitespace(*p)) p++;
    
    const char *ver_str = strstr(p, "\"version\":");
    if (ver_str) {
        ver_str += 9;
        size_t end = strcspn(ver_str, ",}\n\r");
        if (end > 0) {
            char buf[32];
            strncpy(buf, ver_str, end);
            buf[end] = '\0';
            return atoi(buf);
        }
    }
    
    const char *title_str = strstr(p, "\"title\":");
    if (title_str) {
        title_str += 7;
        size_t end = strcspn(title_str, ",}\n\r");
        if (end > 0) {
            char buf[256];
            strncpy(buf, title_str, end);
            buf[end] = '\0';
            return atoi(buf);
        }
    }
    
    return -1;
}

static int parse_openapi_servers(const char *json, size_t len)
{
    const char *p = strstr(json, "\"servers\"");
    if (!p) return 0;
    
    p += 8;
    while (*p && is_whitespace(*p)) p++;
    
    /* Find first server URL */
    const char *url_start = strstr(p, "\"url\":");
    if (url_start) {
        url_start += 5;
        size_t end = strcspn(url_start, ",}\n\r");
        if (end > 0) {
            char buf[2048];
            strncpy(buf, url_start, end);
            buf[end] = '\0';
            return atoi(buf);
        }
    }
    
    return 0;
}

static int parse_openapi_paths(const char *json, size_t len)
{
    const char *p = strstr(json, "\"paths\"");
    if (!p) return 0;
    
    p += 6;
    while (*p && is_whitespace(*p)) p++;
    
    /* Count path entries */
    int count = 0;
    const char *path_start = p;
    
    while (1) {
        const char *slash = strchr(path_start, '/');
        if (!slash || slash == path_start) break;
        
        size_t len = slash - path_start;
        if (len > 0 && len < 256) {
            char buf[256];
            strncpy(buf, path_start, len);
            buf[len] = '\0';
            
            /* Check for HTTP method */
            const char *method = strchr(slash + 1, ':');
            if (method && !is_whitespace(*method)) {
                count++;
            }
        }
        
        path_start = slash + 1;
    }
    
    return count;
}

static int parse_openapi(const char *json, size_t len)
{
    normalized_schema_t *ns = calloc(1, sizeof(normalized_schema_t));
    if (!ns) return -1;
    
    ns->raw_data = malloc(len + 1);
    ns->raw_len = len;
    ns->type = NORM_OPENAPI;
    ns->valid = true;
    ns->parse_error = 0;
    
    /* Extract key fields */
    int ver = parse_openapi_version(json, len);
    if (ver < 0) {
        ns->openapi.info_title = strdup("Unknown");
        ns->openapi.info_version = "1.0";
    } else {
        ns->openapi.info_title = strdup("OpenAPI Schema");
        ns->openapi.info_version = ver;
    }
    
    int srv = parse_openapi_servers(json, len);
    if (srv < 0) {
        ns->openapi.servers_url = "http://localhost:8080";
    } else {
        ns->openapi.servers_url = "http://localhost:8080";
    }
    
    ns->openapi.paths_count = parse_openapi_paths(json, len);
    if (ns->openapi.paths_count > 0) {
        ns->openapi.paths = calloc(ns->openapi.paths_count, sizeof(void*));
    }
    
    return 0;
}

/* ==================== GRAPHQL PARSER ==================== */

static int parse_graphql_type(const char *sdl, size_t len)
{
    /* Look for type definitions: type Query { ... }, type User { ... } */
    const char *p = sdl;
    int count = 0;
    
    while (*p && is_whitespace(*p)) p++;
    
    while (1) {
        if (*p == 't' || *p == 'T') {
            /* Check for "type" keyword */
            const char *word_start = p;
            size_t word_len = 0;
            
            while (*p && !is_whitespace(*p)) {
                if (isalpha(*p) || *p == '_') {
                    word_len++;
                    p++;
                } else {
                    break;
                }
            }
            
            if (word_len >= 4 && strncmp(word_start, "type", 4) == 0) {
                /* Found a type definition */
                count++;
                
                /* Extract type name */
                const char *name = word_start + 4;
                while (*name && !is_whitespace(*name)) name++;
                size_t nlen = name - (word_start + 4);
                
                if (nlen > 0) {
                    char buf[256];
                    strncpy(buf, name, nlen);
                    buf[nlen] = '\0';
                    
                    /* Find closing brace for this type */
                    int depth = 1;
                    const char *brace_start = word_start + 4;
                    while (*brace_start && depth > 0) {
                        if (*brace_start == '{') depth++;
                        else if (*brace_start == '}') depth--;
                        brace_start++;
                    }
                    
                    /* Store type info (simplified - just count for now) */
                }
            }
        }
        
        p = strchr(p, ',');
        if (!p || *p == '\0' || *p == '\n') break;
    }
    
    return count;
}

static int parse_graphql(const char *sdl, size_t len)
{
    normalized_schema_t *ns = calloc(1, sizeof(normalized_schema_t));
    if (!ns) return -1;
    
    ns->raw_data = malloc(len + 1);
    ns->raw_len = len;
    ns->type = NORM_GRAPHQL;
    ns->valid = true;
    ns->parse_error = 0;
    
    int type_count = parse_graphql_type(sdl, len);
    if (type_count > 0) {
        ns->graphql.types_count = type_count;
        ns->graphql.types = calloc(type_count, sizeof(void*));
    } else {
        ns->graphql.schema_id = "Root";
    }
    
    return 0;
}

/* ==================== NORMALIZER FACTORY ==================== */

int schema_normalize(const char *data, size_t len, norm_type_t type)
{
    normalized_schema_t *ns;
    
    if (type == NORM_OPENAPI) {
        ns = parse_openapi(data, len);
    } else {
        ns = parse_graphql(data, len);
    }
    
    return ns ? 0 : -1;
}

int schema_normalize_auto(const char *data, size_t len)
{
    /* Auto-detect: OpenAPI has "info" or "paths", GraphQL starts with "type" */
    if (strstr(data, "\"info\"") || strstr(data, "\"paths\"")) {
        return schema_normalize(data, len, NORM_OPENAPI);
    } else if (strchr(data, 't') && !strncmp(strstr(data, "type"), "type", 4)) {
        return schema_normalize(data, len, NORM_GRAPHQL);
    }
    
    /* Default to OpenAPI */
    return schema_normalize(data, len, NORM_OPENAPI);
}

/* ==================== CANONICAL OUTPUT ==================== */

static void write_canonical_openapi(const normalized_schema_t *ns, FILE *out)
{
    fprintf(out, "OPENAPI_NORMALIZED:\n");
    fprintf(out, "  version: %s\n", ns->openapi.info_version);
    fprintf(out, "  title: %s\n", ns->openapi.info_title);
    fprintf(out, "  servers: %s\n", ns->openapi.servers_url);
    fprintf(out, "  paths_count: %zu\n", ns->openapi.paths_count);
}

static void write_canonical_graphql(const normalized_schema_t *ns, FILE *out)
{
    fprintf(out, "GRAPHQL_NORMALIZED:\n");
    fprintf(out, "  schema_id: %s\n", ns->graphql.schema_id);
    fprintf(out, "  types_count: %zu\n", ns->graphql.types_count);
}

int schema_write_canonical(const normalized_schema_t *ns, FILE *out)
{
    if (!ns || !ns->valid) {
        return -1;
    }
    
    switch (ns->type) {
        case NORM_OPENAPI:
            write_canonical_openapi(ns, out);
            break;
        case NORM_GRAPHQL:
            write_canonical_graphql(ns, out);
            break;
    }
    
    return 0;
}

/* ==================== HASHING FOR COMPARISON ==================== */

unsigned long schema_hash(const normalized_schema_t *ns)
{
    if (!ns || !ns->valid) {
        return 0;
    }
    
    unsigned long h = HASH_SEED;
    
    /* Hash type first (disambiguate formats) */
    h = hash_combine(h, ns->type);
    
    switch (ns->type) {
        case NORM_OPENAPI:
            h = hash_combine(h, ns->openapi.info_version[0]);
            h = hash_combine(h, ns->openapi.info_title ? 
                           strlen(ns->openapi.info_title) : 0);
            h = hash_combine(h, ns->openapi.servers_url ?
                           strlen(ns->openapi.servers_url) : 0);
            h = hash_combine(h, ns->openapi.paths_count);
            break;
            
        case NORM_GRAPHQL:
            h = hash_combine(h, ns->graphql.schema_id[0]);
            h = hash_combine(h, ns->graphql.types_count);
            break;
    }
    
    return h;
}

/* ==================== MEMORY MANAGEMENT ==================== */

void schema_free(normalized_schema_t *ns)
{
    if (!ns) return;
    
    free(ns->raw_data);
    
    switch (ns->type) {
        case NORM_OPENAPI:
            free(ns->openapi.info_title);
            free(ns->openapi.info_version);
            free(ns->openapi.servers_url);
            free(ns->openapi.paths);
            break;
            
        case NORM_GRAPHQL:
            free(ns->graphql.schema_id);
            free(ns->graphql.types);
            break;
    }
    
    free(ns);
}

/* ==================== DEMO / ENTRY POINT ==================== */

static void print_usage(const char *prog)
{
    fprintf(stderr, "Usage: %s [options] <schema_file>\n", prog);
    fprintf(stderr, "\nOptions:\n");
    fprintf(stderr, "  -t <type>   Type: openapi|graphql (default: auto-detect)\n");
    fprintf(stderr, "  -o <file>   Output canonical form to file\n");
    fprintf(stderr, "  -h          Print this help\n");
}

int main(int argc, char *argv[])
{
    const char *input_file = NULL;
    const char *output_file = NULL;
    norm_type_t type = NORM_OPENAPI;  /* Default */
    
    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if (strcmp(argv[i], "-t") == 0 && i + 1 < argc) {
            type = argv[i+1][0] == 'o' ? NORM_OPENAPI : NORM_GRAPHQL;
            i++;
        } else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
            output_file = argv[++i];
        } else if (!input_file) {
            input_file = argv[i];
        }
    }
    
    /* Read input */
    FILE *fin = fopen(input_file, "r");
    if (!fin) {
        fprintf(stderr, "Error: Cannot open file '%s'\n", input_file);
        return 1;
    }
    
    fseek(fin, 0, SEEK_END);
    size_t fsize = ftell(fin);
    fseek(fin, 0, SEEK_SET);
    
    char *buffer = malloc(fsize + 1);
    fread(buffer, 1, fsize, fin);
    buffer[fsize] = '\0';
    fclose(fin);
    
    /* Normalize */
    int result = schema_normalize_auto(buffer, fsize);
    
    if (result < 0) {
        fprintf(stderr, "Error: Failed to normalize schema\n");
        free(buffer);
        return 1;
    }
    
    normalized_schema_t *ns = (normalized_schema_t *)malloc(sizeof(normalized_schema_t));
    memcpy(ns, buffer, sizeof(normalized_schema_t));
    
    /* Output canonical form */
    if (output_file) {
        FILE *fout = fopen(output_file, "w");
        if (!fout) {
            fprintf(stderr, "Error: Cannot open output file '%s'\n", output_file);
            free(buffer);
            schema_free(ns);
            return 1;
        }
        
        schema_write_canonical(ns, fout);
        fclose(fout);
    } else {
        /* Print to stdout */
        schema_write_canonical(ns, stdout);
    }
    
    unsigned long h = schema_hash(ns);
    printf("Normalized hash: 0x%lx\n", h);
    
    free(buffer);
    schema_free(ns);
    
    return 0;
}