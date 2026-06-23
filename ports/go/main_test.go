package main

import (
	"encoding/json"
	"testing"
)

func mustParse(t *testing.T, s string) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		t.Fatalf("parse: %v", err)
	}
	return m
}

func diff(t *testing.T, o, n string) []Change {
	return DiffOpenAPI(mustParse(t, o), mustParse(t, n))
}

func hasCode(cs []Change, code string) bool {
	for _, c := range cs {
		if c.Code == code {
			return true
		}
	}
	return false
}

func TestRemovedPathIsBreaking(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}`,
		`{"openapi":"3.0.0","paths":{}}`)
	if !HasBreaking(c) || !hasCode(c, "path.removed") {
		t.Fatalf("expected breaking path.removed, got %+v", c)
	}
}

func TestNewRequiredParamIsBreaking(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[],"responses":{}}}}}`,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[{"name":"q","in":"query","required":true}],"responses":{}}}}}`)
	if !hasCode(c, "param.added.required") {
		t.Fatalf("expected param.added.required, got %+v", c)
	}
}

func TestAddedOptionalParamNotBreaking(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[],"responses":{}}}}}`,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[{"name":"q","in":"query","required":false}],"responses":{}}}}}`)
	if HasBreaking(c) {
		t.Fatalf("expected no breaking, got %+v", c)
	}
}

func TestResponsePropertyRemovalIsBreaking(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{"content":{"application/json":{"schema":{"properties":{"x":{"type":"string"}}}}}}}}}}`,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{"content":{"application/json":{"schema":{"properties":{}}}}}}}}}`)
	if !hasCode(c, "response.property.removed") {
		t.Fatalf("expected response.property.removed, got %+v", c)
	}
}

func TestIdenticalNoChanges(t *testing.T) {
	d := `{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}`
	if c := diff(t, d, d); len(c) != 0 {
		t.Fatalf("expected 0 changes, got %+v", c)
	}
}

func TestStatusCodeDroppedIsBreaking(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{},"206":{}}}}}}`,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{}}}}}}`)
	if !hasCode(c, "response.removed") {
		t.Fatalf("expected response.removed, got %+v", c)
	}
}

func TestAddedPathIsInfoOnly(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}`,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}},"/b":{"get":{"responses":{}}}}}`)
	if HasBreaking(c) || !hasCode(c, "path.added") {
		t.Fatalf("expected info path.added, got %+v", c)
	}
}

func TestSummaryCounts(t *testing.T) {
	c := diff(t,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}},"/gone":{"get":{"responses":{}}}}}`,
		`{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}},"/new":{"get":{"responses":{}}}}}`)
	s := Summary(c)
	if s["breaking"] < 1 || s["info"] < 1 {
		t.Fatalf("expected at least 1 breaking and 1 info, got %v", s)
	}
}
