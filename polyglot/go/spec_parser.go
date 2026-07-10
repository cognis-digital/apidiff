package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// ==================== OPENAPI PARSER ====================

type OpenAPISpec struct {
	Openapi string `json:"openapi"`
	Info    Info   `json:"info"`
	Paths   Paths  `json:"paths"`
	Schemas map[string]SchemaRef `json:"schemas,omitempty"`
}

type Info struct {
	Title       string `json:"title"`
	Version     string `json:"version"`
	Description string `json:"description,omitempty"`
}

type SchemaRef struct {
	$ref    string      `json:"$ref,omitempty"`
	Type    string      `json:"type,omitempty"`
	Format  string      `json:"format,omitempty"`
	Items   *SchemaRef  `json:"items,omitempty"`
	Props   map[string]Property `json:"properties,omitempty"`
	Default interface{}  `json:"default,omitempty"`
}

type Property struct {
	Type    string      `json:"type,omitempty"`
	Format  string      `json:"format,omitempty"`
	Items   *SchemaRef  `json:"items,omitempty"`
	Enum    []interface{} `json:"enum,omitempty"`
	Default interface{}  `json:"default,omitempty"`
}

type Paths map[string]PathItem

type PathItem struct {
	Get     Operation `json:"get,omitempty"`
	Post    Operation `json:"post,omitempty"`
	Put     Operation `json:"put,omitempty"`
	Delete  Operation `json:"delete,omitempty"`
	Patch   Operation `json:"patch,omitempty"`
	Options Operation `json:"options,omitempty"`
	Head    Operation `json:"head,omitempty"`
}

type Operation struct {
	Summary       string      `json:"summary,omitempty"`
	Description   string      `json:"description,omitempty"`
	Tags          []string    `json:"tags,omitempty"`
	Parameters    []Parameter `json:"parameters,omitempty"`
	Responses     Responses   `json:"responses,omitempty"`
}

type Parameter struct {
	Name       string         `json:"name,omitempty"`
	In         string         `json:"in,omitempty"`
	Schema     *SchemaRef     `json:"schema,omitempty"`
	Required   bool           `json:"required,omitempty"`
	Description string         `json:"description,omitempty"`
}

type Responses map[int]ResponseValue

type ResponseValue struct {
	Description string      `json:"description,omitempty"`
	Schema      *SchemaRef  `json:"schema,omitempty"`
	Content     []Content   `json:"content,omitempty"`
}

type Content struct {
	MediaType string       `json:"media_type,omitempty"`
	Schema    *SchemaRef   `json:"schema,omitempty"`
	Examples  []interface{} `json:"examples,omitempty"`
}

// ==================== GRAPHQL PARSER ====================

type GraphQLSpec struct {
	Schema     Schema      `json:"__schema"`
	TypeDefs   string      `json:"__typeDefs,omitempty"`
}

type Schema struct {
	QueryType    TypeRef  `json:"queryType"`
	MutationType TypeRef  `json:"mutationType,omitempty"`
	SubscriptionType TypeRef `json:"subscriptionType,omitempty"`
	Types        []Type   `json:"types"`
	Directives   []Directive `json:"directives"`
}

type TypeRef struct {
	Name string `json:"name"`
}

type Type struct {
	Name         string      `json:"name"`
	Description  string      `json:"description,omitempty"`
	Kind         string      `json:"kind"`
	Fields       []Field     `json:"fields,omitempty"`
	Interfaces   []string    `json:"interfaces,omitempty"`
	PossibleTypes []TypeRef   `json:"possibleTypes,omitempty"`
}

type Field struct {
	Name        string  `json:"name"`
	Description string  `json:"description,omitempty"`
	Type        TypeRef  `json:"type"`
	Args        []InputValue `json:"args,omitempty"`
}

type InputValue struct {
	Name    string      `json:"name"`
	Type    TypeRef     `json:"type"`
	DefaultValue interface{} `json:"defaultValue,omitempty"`
}

type Directive struct {
	Name         string  `json:"name"`
	Description  string  `json:"description,omitempty"`
	Locations    []string `json:"locations"`
	Args         []InputValue `json:"arguments"`
}

// ==================== TYPE SYSTEM HELPERS ====================

func extractTypeName(ref string) string {
	if ref == "" || ref == "#" {
		return "unknown"
	}
	parts := strings.Split(ref, "/")
	return parts[len(parts)-1]
}

func getTypeNameFromRef(ref string) string {
	return extractTypeName(ref)
}

// ==================== SPEC NORMALIZER ====================

type NormalizedSpec struct {
	OpenAPI *OpenAPISpec
	GraphQL *GraphQLSpec
	Metadata Metadata
}

type Metadata struct {
	Title         string
	Version       string
	Source        string
	ParsedAt      string
	Type          SpecType
}

func ParseToNormalized(source string, specType SpecType) (*NormalizedSpec, error) {
	var raw interface{}
	
	data, err := os.ReadFile(source)
	if err != nil {
		return nil, fmt.Errorf("read file: %w", err)
	}
	
	err = json.Unmarshal(data, &raw)
	if err != nil {
		return nil, fmt.Errorf("parse JSON: %w", err)
	}
	
	var result *NormalizedSpec
	
	switch specType {
	case SpecTypeOpenAPI:
		result = parseOpenAPI(raw)
	case SpecTypeGraphQL:
		result = parseGraphQL(raw)
	default:
		return nil, fmt.Errorf("unknown spec type: %v", specType)
	}
	
	if result == nil {
		return nil, fmt.Errorf("no valid spec found in file")
	}
	
	result.Metadata.Title = result.OpenAPI.Info.Title
	result.Metadata.Version = result.OpenAPI.Info.Version
	
	return result, nil
}

func parseOpenAPI(raw interface{}) *NormalizedSpec {
	var openapi OpenAPISpec
	
	switch v := raw.(type) {
	case map[string]interface{}:
		json.Unmarshal(v, &openapi)
	default:
		return nil
	}
	
	if openapi.Openapi == "" || openapi.Paths == nil {
		return nil
	}
	
	return &NormalizedSpec{
		OpenAPI: &openapi,
		Metadata: Metadata{
			Title:   openapi.Info.Title,
			Version: openapi.Info.Version,
			Type:    SpecTypeOpenAPI,
		},
	}
}

func parseGraphQL(raw interface{}) *NormalizedSpec {
	var graphql GraphQLSpec
	
	switch v := raw.(type) {
	case map[string]interface{}:
		json.Unmarshal(v, &graphql)
	default:
		return nil
	}
	
	if len(graphql.Schema.Types) == 0 && graphql.TypeDefs == "" {
		return nil
	}
	
	return &NormalizedSpec{
		GraphQL: &graphql,
		Metadata: Metadata{
			Type: SpecTypeGraphQL,
		},
	}
}

// ==================== ENDPOINT TRACKER ====================

type Endpoint struct {
	Path          string
	Method        string
	Summary       string
	Description   string
	Tags          []string
	Parameters    []ParameterInfo
	Responses     map[int]ResponseInfo
	RequestBody   *RequestBodyInfo
}

type ParameterInfo struct {
	Name         string
	In           string
	TypeName     string
	Required     bool
	Description  string
}

type ResponseInfo struct {
	Code       int
	Description string
	Schema     *SchemaRef
}

type RequestBodyInfo struct {
	ContentTypes []string
	Schema       *SchemaRef
}

func (s *OpenAPISpec) ExtractEndpoints() ([]Endpoint, error) {
	var endpoints []Endpoint
	
	for path, item := range s.Paths {
		endpoint := Endpoint{
			Path:    path,
			Method:  "",
			Summary: item.Get.Summary,
			Tags:    item.Get.Tags,
		}
		
		if item.Get.Description != "" {
			endpoint.Description = item.Get.Description
		}
		
		for _, op := range []struct{ Method string; Op Operation }{
			{"GET", item.Get},
			{"POST", item.Post},
			{"PUT", item.Put},
			{"DELETE", item.Delete},
			{"PATCH", item.Patch},
			{"OPTIONS", item.Options},
			{"HEAD", item.Head},
		} {
			if op.Op.Summary != "" || op.Op.Description != "" {
				endpoint.Method = op.Method
				endpoint.Summary = op.Op.Summary
				endpoint.Description = op.Op.Description
				
				// Process parameters
				for _, param := range op.Op.Parameters {
					paramInfo := ParameterInfo{
						Name:      param.Name,
						In:        param.In,
						TypeName:  extractTypeName(param.Schema.$ref),
						Required:  param.Required,
						Description: param.Description,
					}
					endpoint.Parameters = append(endpoint.Parameters, paramInfo)
				}
				
				// Process responses
				for code, resp := range op.Op.Responses {
					respInfo := ResponseInfo{
						Code:       code,
						Description: resp.Description,
					}
					if resp.Schema != nil {
						respInfo.Schema = resp.Schema
					}
					endpoint.Responses[code] = respInfo
				}
				
				break // Only one method per path item for simplicity
			}
		}
		
		if endpoint.Method != "" {
			endpoints = append(endpoints, endpoint)
		}
	}
	
	return endpoints, nil
}

// ==================== DIFF ENGINE ====================

type DiffResult struct {
	Title       string
	Version     string
	Type        SpecType
	Endpoints   []DiffEndpoint
	Parameters  []DiffParameter
	Types       []DiffType
	TotalChanges int
	Breaking    bool
}

type DiffEndpoint struct {
	Path         string
	Method       string
	Status       EndpointStatus
	OldSummary    string
	NewSummary    string
	AddedParams   int
	RemovedParams int
	ChangedParams []string
	AddedResponses []int
	RemovedResponses []int
	ChangedResponses []int
}

type EndpointStatus int

const (
	StatusUnchanged EndpointStatus = iota
	StatusModified
	StatusMoved
	StatusDeprecated
)

func CompareEndpoints(oldSpec, newSpec *OpenAPISpec) ([]DiffEndpoint, error) {
	oldEndpoints, err := oldSpec.ExtractEndpoints()
	if err != nil {
		return nil, err
	}
	
	newEndpoints, err := newSpec.ExtractEndpoints()
	if err != nil {
		return nil, err
	}
	
	var diffs []DiffEndpoint
	
	// Create lookup maps
	oldMap := make(map[string]Endpoint)
	for _, ep := range oldEndpoints {
		key := fmt.Sprintf("%s|%s", ep.Method, ep.Path)
		oldMap[key] = ep
	}
	
	newMap := make(map[string]Endpoint)
	for _, ep := range newEndpoints {
		key := fmt.Sprintf("%s|%s", ep.Method, ep.Path)
		newMap[key] = ep
	}
	
	// Find unchanged endpoints
	changedKeys := make([]string, 0)
	unchangedCount := 0
	
	for key := range oldMap {
		if newEp, exists := newMap[key]; exists && isEndpointUnchanged(oldMap[key], newEp) {
			unchangedCount++
		} else {
			changedKeys = append(changedKeys, key)
		}
	}
	
	for _, key := range changedKeys {
		oldEp := oldMap[key]
		newEp := newMap[key]
		
		status := StatusModified
		
		if oldEp.Summary != "" && !strings.Contains(oldEp.Summary, "deprecated") && 
		   (newEp.Summary == "" || strings.Contains(newEp.Summary, "deprecated")) {
			status = StatusDeprecated
		} else if oldEp.Path != newEp.Path {
			status = StatusMoved
		}
		
		diffs = append(diffs, DiffEndpoint{
			Path:         oldEp.Path,
			Method:       oldEp.Method,
			Status:       status,
			OldSummary:   oldEp.Summary,
			NewSummary:   newEp.Summary,
		})
	}
	
	return diffs, nil
}

func isEndpointUnchanged(oldEp, newEp Endpoint) bool {
	if oldEp.Method != newEp.Method || oldEp.Path != newEp.Path {
		return false
	}
	
	if !strings.EqualFold(oldEp.Summary, newEp.Summary) && 
	   (oldEp.Summary != "" || newEp.Summary != "") {
		return false
	}
	
	return true
}

func CompareParameters(oldSpec, newSpec *OpenAPISpec) ([]DiffParameter, error) {
	oldParams := make(map[string][]ParameterInfo)
	newParams := make(map[string][]ParameterInfo)
	
	for _, ep := range oldSpec.ExtractEndpoints() {
		key := fmt.Sprintf("%s|%s", ep.Method, ep.Path)
		for _, param := range ep.Parameters {
			oldParams[key] = append(oldParams[key], param)
		}
	}
	
	for _, ep := range newSpec.ExtractEndpoints() {
		key := fmt.Sprintf("%s|%s", ep.Method, ep.Path)
		for _, param := range ep.Parameters {
			newParams[key] = append(newParams[key], param)
		}
	}
	
	var diffs []DiffParameter
	
	allKeys := make(map[string]bool)
	for k := range oldParams { allKeys[k] = true }
	for k := range newParams { allKeys[k] = true }
	
	for key := range allKeys {
		oldList, existsOld := oldParams[key]
		newList, existsNew := newParams[key]
		
		if !existsOld && !existsNew {
			continue
		}
		
		oldSet := make(map[string]bool)
		newSet := make(map[string]bool)
		
		for _, p := range oldList {
			oldSet[p.Name] = true
		}
		for _, p := range newList {
			newSet[p.Name] = true
		}
		
		addedParams := 0
		removedParams := 0
		
		for name := range newSet {
			if !oldSet[name] {
				addedParams++
			}
		}
		
		for name := range oldSet {
			if !newSet[name] {
				removedParams++
			}
		}
		
		if addedParams > 0 || removedParams > 0 {
			diffs = append(diffs, DiffParameter{
				Path:       key,
				AddedCount: addedParams,
				RemovedCount: removedParams,
			})
		}
	}
	
	return diffs, nil
}

func CompareTypes(oldSpec, newSpec *OpenAPISpec) ([]DiffType, error) {
	oldSchemas := make(map[string]*SchemaRef)
	newSchemas := make(map[string]*SchemaRef)
	
	for name, schema := range oldSpec.Schemas {
		oldSchemas[name] = &schema
	}
	
	for name, schema := range newSpec.Schemas {
		newSchemas[name] = &schema
	}
	
	var diffs []DiffType
	
	allNames := make(map[string]bool)
	for n := range oldSchemas { allNames[n] = true }
	for n := range newSchemas { allNames[n] = true }
	
	for name := range allNames {
		oldSchema, existsOld := oldSchemas[name]
		newSchema, existsNew := newSchemas[name]
		
		if !existsOld && !existsNew {
			continue
		}
		
		typeChanged := false
		
		if !existsOld && existsNew {
			typeChanged = true
		} else if existsOld && !existsNew {
			typeChanged = true
		} else if oldSchema.Type != newSchema.Type || 
		          (oldSchema.Items != nil && newSchema.Items == nil) ||
		          (oldSchema.Items == nil && newSchema.Items != nil) {
			typeChanged = true
		}
		
		if typeChanged {
			diffs = append(diffs, DiffType{
				Name:       name,
				TypeChanged: typeChanged,
			})
		}
	}
	
	return diffs, nil
}

// ==================== REPORT GENERATOR ====================

type ReportConfig struct {
	Title      string
	Version    string
	Type       SpecType
	Breaking   bool
	Endpoints  []DiffEndpoint
	Parameters []DiffParameter
	Types      []DiffType
}

func GenerateReport(config ReportConfig) (string, error) {
	var buf bytes.Buffer
	
	buf.WriteString("=== API Diff Report ===\n\n")
	
	if config.Title != "" {
		buf.WriteString(fmt.Sprintf("Title: %s\n", config.Title))
	}
	
	if config.Version != "" {
		buf.WriteString(fmt.Sprintf("Version: %s\n", config.Version))
	}
	
	buf.WriteString(fmt.Sprintf("Type: %s\n\n", config.Type))
	
	if len(config.Endpoints) > 0