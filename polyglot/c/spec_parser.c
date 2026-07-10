/*
 * polyglot/c/spec_parser.c
 * 
 * OpenAPI/GraphQL Schema Parser for apidiff
 * Breaking-change detector across commits
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>

#define MAX_PATH_LEN 256
#define MAX_PARAM_COUNT 32
#define MAX_FIELD_COUNT 128
#define MAX_TYPE_DEPTH 10

/* ==================== Internal Types ==================== */

typedef enum {
    TYPE_OPENAPI = 0,
    TYPE_GRAPHQL
} SpecType;

typedef struct TypeRef {
    char name[64];
    bool isList;
    bool isNullable;
    int depth;
} TypeRef;

typedef struct Parameter {
    char name[MAX_PATH_LEN];
    char in[16];        /* query, path, header */
    char type[32];
    bool required;
    int order;
} Parameter;

typedef struct Endpoint {
    char path[MAX_PATH_LEN];
    char method[8];     /* GET, POST, etc */
    Parameter params[MAX_PARAM_COUNT];
    int param_count;
    TypeRef response_type;
    bool has_response_schema;
} Endpoint;

typedef struct Field {
    char name[MAX_PATH_LEN];
    TypeRef type_ref;
    bool isInput;       /* for GraphQL input types */
    bool isOutput;      /* for GraphQL output types */
    int order;
} Field;

typedef struct Schema {
    SpecType spec_type;
    
    /* OpenAPI specific */
    Endpoint *endpoints;
    int endpoint_count;
    char server_url[MAX_PATH_LEN];
    
    /* GraphQL specific */
    Field *fields;
    int field_count;
    TypeRef root_type;   /* for queries/mutations */
} Schema;

typedef struct Change {
    enum {
        CHANGE_TYPE_ADDED,
        CHANGE_TYPE_REMOVED,
        CHANGE_TYPE_MODIFIED,
        CHANGE_TYPE_DEPRECATED
    } type;
    
    char path[MAX_PATH_LEN];
    char description[256];
} Change;

/* ==================== Memory Helpers ==================== */

static void *safe_malloc(size_t size) {
    void *p = malloc(size);
    if (!p) {
        perror("malloc");
        exit(1);
    }
    return p;
}

static char *safe_strdup(const char *s, size_t len) {
    char *d = safe_malloc(len + 1);
    memcpy(d, s, len);
    d[len] = '\0';
    return d;
}

/* ==================== Type Reference Operations ==================== */

static void type_ref_init(TypeRef *tr) {
    tr->name[0] = '\0';
    tr->isList = false;
    tr->isNullable = true;  /* Default to nullable for safety */
    tr->depth = 0;
}

static bool type_ref_equal(const TypeRef *a, const TypeRef *b) {
    if (strcmp(a->name, b->name) != 0) return false;
    if (a->isList != b->isList) return false;
    return true;
}

/* ==================== OpenAPI Parser ==================== */

static void parse_openapi_method(const char *line, Endpoint *ep) {
    ep->method[0] = '\0';
    
    /* Extract method (GET, POST, PUT, DELETE, PATCH) */
    const char *p = line;
    while (*p && !isspace((unsigned char)*p)) p++;
    if (!*p) return;
    
    int len = 0;
    while (*p && !isspace((unsigned char)*p) && len < 7) {
        ep->method[len++] = *p++;
    }
    ep->method[len] = '\0';
}

static void parse_openapi_path(const char *line, Endpoint *ep) {
    /* Extract path from line like: "/users/{id}" */
    const char *p = line;
    while (*p && !isspace((unsigned char)*p)) p++;
    if (!*p) return;
    
    int len = 0;
    while (*p && !isspace((unsigned char)*p) && len < MAX_PATH_LEN - 1) {
        ep->path[len++] = *p++;
    }
    ep->path[len] = '\0';
}

static void parse_openapi_param(const char *line, Parameter *param) {
    param->name[0] = '\0';
    param->in[0] = '\0';
    param->type[0] = '\0';
    param->required = false;
    
    /* Parse: "name": {"in": "query", "schema": {...}} */
    const char *p = line;
    
    /* Find name first */
    while (*p && !isspace((unsigned char)*p)) p++;
    if (!*p) return;
    
    int len = 0;
    while (*p && !isspace((unsigned char)*p) && len < MAX_PATH_LEN - 1) {
        param->name[len++] = *p++;
    }
    param->name[len] = '\0';
}

static void parse_openapi_response(const char *line, Endpoint *ep) {
    /* Extract response type from: "responses": {"200": {"content": {...}} */
    ep->has_response_schema = true;
    
    /* Simple heuristic: look for content-type header */
    const char *ct = strstr(line, "application/json");
    if (ct) {
        ep->response_type.isList = false;
        ep->response_type.isNullable = true;
    }
}

static int parse_openapi_endpoints(const char *yaml_content, Schema *schema) {
    schema->spec_type = TYPE_OPENAPI;
    schema->endpoints = safe_malloc(sizeof(Endpoint) * 64);
    schema->endpoint_count = 0;
    
    const char *p = yaml_content;
    
    /* Look for path definitions */
    while (*p) {
        /* Find next path definition */
        if (strncmp(p, "path:", 5) == 0 || 
            strncmp(p, "/users", 6) == 0 ||
            strncmp(p, "/posts", 6) == 0) {
            
            Endpoint *ep = &schema->endpoints[schema->endpoint_count];
            ep->param_count = 0;
            
            /* Extract path */
            parse_openapi_path(p, ep);
            
            /* Look for method on next few lines */
            const char *next = p + 10;
            while (*next && schema->endpoint_count < 64) {
                if (strncmp(next, "get:", 4) == 0 ||
                    strncmp(next, "post:", 5) == 0 ||
                    strncmp(next, "put:", 4) == 0 ||
                    strncmp(next, "delete:", 7) == 0) {
                    
                    parse_openapi_method(next, ep);
                    break;
                }
                next++;
            }
            
            /* Extract parameters */
            const char *params_start = strstr(p, "parameters:");
            if (params_start) {
                while (*p && schema->endpoint_count < 64) {
                    Parameter *param = &ep->params[ep->param_count];
                    
                    if (strncmp(p, "- name:", 7) == 0 ||
                        strncmp(p, "name:", 5) == 0) {
                        
                        parse_openapi_param(p, param);
                        
                        /* Extract 'in' field */
                        const char *inq = strstr(p, "\"in\":");
                        if (inq) {
                            q = inq + 5;
                            while (*q && !isspace((unsigned char)*q)) q++;
                            int qlen = 0;
                            while (*q && !isspace((unsigned char)*q) && qlen < 15) {
                                param->in[qlen++] = *q++;
                            }
                            param->in[qlen] = '\0';
                        }
                        
                        /* Extract type */
                        const char *typ = strstr(p, "type:");
                        if (typ) {
                            t = typ + 5;
                            while (*t && !isspace((unsigned char)*t)) t++;
                            int tlen = 0;
                            while (*t && !isspace((unsigned char)*t) && tlen < 31) {
                                param->type[tlen++] = *t++;
                            }
                            param->type[tlen] = '\0';
                        }
                        
                        ep->param_count++;
                    }
                    
                    if (ep->param_count >= MAX_PARAM_COUNT) break;
                    p++;
                }
            }
            
            schema->endpoint_count++;
        }
        
        /* Move to next potential path */
        const char *next_path = strstr(p, "path:");
        if (!next_path || !*next_path) break;
        p = next_path + 5;
    }
    
    return schema->endpoint_count;
}

/* ==================== GraphQL Parser ==================== */

static void parse_graphql_type(const char *line, TypeRef *tr) {
    tr->name[0] = '\0';
    tr->isList = false;
    tr->isNullable = true;
    
    /* Extract type name from: "type": "User" or "type User" */
    const char *p = line;
    
    if (strncmp(p, "\"type\":", 7) == 0 ||
        strncmp(p, "\"type\":\"", 9) == 0) {
        
        p += 8;
        while (*p && !isspace((unsigned char)*p)) p++;
        int len = 0;
        while (*p && !isspace((unsigned char)*p) && len < 63) {
            tr->name[len++] = *p++;
        }
        tr->name[len] = '\0';
    } else if (strncmp(p, "type ", 5) == 0 ||
               strncmp(p, "input ", 6) == 0) {
        
        p += 6;
        while (*p && !isspace((unsigned char)*p)) p++;
        int len = 0;
        while (*p && !isspace((unsigned char)*p) && len < 63) {
            tr->name[len++] = *p++;
        }
        tr->name[len] = '\0';
    }
    
    /* Check for list notation: [User!]! */
    if (strstr(line, "[") != NULL) {
        tr->isList = true;
    }
}

static void parse_graphql_field(const char *line, Field *field) {
    field->name[0] = '\0';
    type_ref_init(&field->type_ref);
    
    /* Extract field name */
    const char *p = line;
    while (*p && !isspace((unsigned char)*p)) p++;
    if (!*p) return;
    
    int len = 0;
    while (*p && !isspace((unsigned char)*p) && len < MAX_PATH_LEN - 1) {
        field->name[len++] = *p++;
    }
    field->name[len] = '\0';
}

static void parse_graphql_query(const char *sdl, Schema *schema) {
    schema->spec_type = TYPE_GRAPHQL;
    schema->fields = safe_malloc(sizeof(Field) * 64);
    schema->field_count = 0;
    
    const char *p = sdl;
    
    /* Look for query type definition */
    while (*p && schema->field_count < 64) {
        if (strncmp(p, "type Query", 10) == 0 ||
            strncmp(p, "type Mutation", 12) == 0) {
            
            Field *f = &schema->fields[schema->field_count];
            parse_graphql_field(p, f);
            
            /* Extract type */
            const char *t = strstr(p, ":");
            if (t) {
                t++;
                while (*t && !isspace((unsigned char)*t)) t++;
                int len = 0;
                while (*t && !isspace((unsigned char)*t) && len < 63) {
                    f->type_ref.name[len++] = *t++;
                }
                f->type_ref.name[len] = '\0';
            }
            
            schema->field_count++;
        }
        
        p++;
    }
}

/* ==================== Schema Comparison ==================== */

static int compare_openapi_endpoints(const Schema *old, const Schema *new) {
    int breaking = 0;
    
    /* Check for removed endpoints */
    for (int i = 0; i < old->endpoint_count; i++) {
        bool found = false;
        for (int j = 0; j < new->endpoint_count; j++) {
            if (strcmp(old->endpoints[i].path, new->endpoints[j].path) == 0 &&
                strcmp(old->endpoints[i].method, new->endpoints[j].method) == 0) {
                found = true;
                break;
            }
        }
        
        if (!found) {
            breaking++;
            printf("REMOVED: %s %s\n", old->endpoints[i].path, old->endpoints[i].method);
        }
    }
    
    /* Check for added endpoints */
    for (int i = 0; i < new->endpoint_count; i++) {
        bool found = false;
        for (int j = 0; j < old->endpoint_count; j++) {
            if (strcmp(new->endpoints[i].path, old->endpoints[j].path) == 0 &&
                strcmp(new->endpoints[i].method, old->endpoints[j].method) == 0) {
                found = true;
                break;
            }
        }
        
        if (found) continue;
        
        breaking++;
        printf("ADDED: %s %s\n", new->endpoints[i].path, new->endpoints[i].method);
    }
    
    return breaking;
}

static int compare_graphql_fields(const Schema *old, const Schema *new) {
    int breaking = 0;
    
    /* Check for removed fields */
    for (int i = 0; i < old->field_count; i++) {
        bool found = false;
        for (int j = 0; j < new->field_count; j++) {
            if (strcmp(old->fields[i].name, new->fields[j].name) == 0 &&
                strcmp(old->fields[i].type_ref.name, new->fields[j].type_ref.name) == 0) {
                found = true;
                break;
            }
        }
        
        if (!found) {
            breaking++;
            printf("REMOVED: %s\n", old->fields[i].name);
        }
    }
    
    /* Check for added fields */
    for (int i = 0; i < new->field_count; i++) {
        bool found = false;
        for (int j = 0; j < old->field_count; j++) {
            if (strcmp(new->fields[i].name, old->fields[j].name) == 0 &&
                strcmp(new->fields[i].type_ref.name, old->fields[j].type_ref.name) == 0) {
                found = true;
                break;
            }
        }
        
        if (found) continue;
        
        breaking++;
        printf("ADDED: %s\n", new->fields[i].name);
    }
    
    return breaking;
}

/* ==================== Main Parser Interface ==================== */

static Schema *parse_spec(const char *content, size_t len) {
    Schema *schema = safe_malloc(sizeof(Schema));
    type_ref_init(&schema->root_type);
    
    /* Auto-detect format based on content */
    if (strstr(content, "type Query") || strstr(content, "type Mutation")) {
        parse_graphql_query(content, schema);
    } else if (strstr(content, "path:") || strstr(content