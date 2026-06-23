// Go port of the apidiff OpenAPI breaking-change engine.
// Single static binary, zero third-party deps. Mirrors the Python reference CLI:
//
//	apidiff-go diff OLD.json NEW.json [--format table|json]
//
// Exit code 1 when breaking changes are found, else 0 (2 on IO/usage error).
// Passive, read-only, offline.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

const (
	Breaking = "BREAKING"
	Warning  = "WARNING"
	Info     = "INFO"
)

var methods = []string{"get", "put", "post", "delete", "patch", "head", "options"}

// Change is a single classified API change.
type Change struct {
	Severity string `json:"severity"`
	Code     string `json:"code"`
	Location string `json:"location"`
	Message  string `json:"message"`
}

type doc map[string]any

func asMap(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return nil
}

// DiffOpenAPI compares two decoded OpenAPI documents and returns the changes.
func DiffOpenAPI(oldDoc, newDoc map[string]any) []Change {
	var changes []Change
	add := func(sev, code, loc, msg string) {
		changes = append(changes, Change{sev, code, loc, msg})
	}

	oldPaths := asMap(oldDoc["paths"])
	newPaths := asMap(newDoc["paths"])
	if oldPaths == nil {
		oldPaths = map[string]any{}
	}
	if newPaths == nil {
		newPaths = map[string]any{}
	}

	for _, p := range sortedKeys(oldPaths) {
		if _, ok := newPaths[p]; !ok {
			add(Breaking, "path.removed", p, fmt.Sprintf("Path '%s' was removed", p))
		}
	}
	for _, p := range sortedKeys(newPaths) {
		if _, ok := oldPaths[p]; !ok {
			add(Info, "path.added", p, fmt.Sprintf("Path '%s' was added", p))
		}
	}

	for _, p := range sortedKeys(oldPaths) {
		if _, ok := newPaths[p]; !ok {
			continue
		}
		oldItem := asMap(oldPaths[p])
		newItem := asMap(newPaths[p])
		for _, m := range methods {
			oldOp := asMap(oldItem[m])
			newOp := asMap(newItem[m])
			loc := strings.ToUpper(m) + " " + p
			if oldOp != nil && newOp == nil {
				add(Breaking, "operation.removed", loc, fmt.Sprintf("Operation '%s' was removed", loc))
				continue
			}
			if newOp != nil && oldOp == nil {
				add(Info, "operation.added", loc, fmt.Sprintf("Operation '%s' was added", loc))
				continue
			}
			if oldOp == nil || newOp == nil {
				continue
			}
			diffOperation(&changes, loc, oldOp, newOp)
		}
	}
	return changes
}

func paramsIndex(op map[string]any) map[string]map[string]any {
	out := map[string]map[string]any{}
	if raw, ok := op["parameters"].([]any); ok {
		for _, pr := range raw {
			if pm := asMap(pr); pm != nil {
				if name, ok := pm["name"].(string); ok {
					where, _ := pm["in"].(string)
					if where == "" {
						where = "query"
					}
					out[name+" "+where] = pm
				}
			}
		}
	}
	return out
}

func isRequired(m map[string]any) bool {
	b, _ := m["required"].(bool)
	return b
}

func diffOperation(changes *[]Change, loc string, oldOp, newOp map[string]any) {
	add := func(sev, code, msg string) { *changes = append(*changes, Change{sev, code, loc, msg}) }
	oldParams := paramsIndex(oldOp)
	newParams := paramsIndex(newOp)

	for _, key := range sortedParamKeys(oldParams) {
		if _, ok := newParams[key]; !ok {
			name, where := splitKey(key)
			add(Warning, "param.removed", fmt.Sprintf("Parameter '%s' (in: %s) was removed", name, where))
		}
	}
	for _, key := range sortedParamKeys(newParams) {
		name, where := splitKey(key)
		p := newParams[key]
		if oldP, ok := oldParams[key]; !ok {
			if isRequired(p) {
				add(Breaking, "param.added.required", fmt.Sprintf("New required parameter '%s' (in: %s) added", name, where))
			} else {
				add(Info, "param.added", fmt.Sprintf("New optional parameter '%s' (in: %s) added", name, where))
			}
		} else if isRequired(p) && !isRequired(oldP) {
			add(Breaking, "param.required.added", fmt.Sprintf("Parameter '%s' (in: %s) became required", name, where))
		} else if isRequired(oldP) && !isRequired(p) {
			add(Info, "param.required.removed", fmt.Sprintf("Parameter '%s' (in: %s) is no longer required", name, where))
		}
	}

	if oldBody, newBody := bodySchema(oldOp), bodySchema(newOp); oldBody != nil && newBody != nil {
		oldReq := stringSet(oldBody["required"])
		newReq := stringSet(newBody["required"])
		for _, f := range sortedSetDiff(newReq, oldReq) {
			add(Breaking, "requestBody.required.added", fmt.Sprintf("Request body field '%s' became required", f))
		}
		for _, f := range sortedSetDiff(oldReq, newReq) {
			add(Info, "requestBody.required.removed", fmt.Sprintf("Request body field '%s' is no longer required", f))
		}
		diffProps(changes, loc, "requestBody", asMap(oldBody["properties"]), asMap(newBody["properties"]), false)
	}

	if oldResp, newResp := successResponseSchema(oldOp), successResponseSchema(newOp); oldResp != nil && newResp != nil {
		diffProps(changes, loc, "response", asMap(oldResp["properties"]), asMap(newResp["properties"]), true)
	}

	oldCodes := asMap(oldOp["responses"])
	newCodes := asMap(newOp["responses"])
	for _, code := range sortedKeys(oldCodes) {
		if _, ok := newCodes[code]; !ok && strings.HasPrefix(code, "2") {
			add(Breaking, "response.removed", fmt.Sprintf("Success response '%s' was removed", code))
		}
	}
}

func diffProps(changes *[]Change, loc, scope string, oldProps, newProps map[string]any, removedBreaking bool) {
	add := func(sev, code, msg string) { *changes = append(*changes, Change{sev, code, loc, msg}) }
	for _, name := range sortedKeys(oldProps) {
		np, ok := newProps[name]
		if !ok {
			sev := Warning
			if removedBreaking {
				sev = Breaking
			}
			add(sev, scope+".property.removed", fmt.Sprintf("%s property '%s' was removed", scope, name))
			continue
		}
		ot, _ := asMap(oldProps[name])["type"].(string)
		nt, _ := asMap(np)["type"].(string)
		if ot != "" && nt != "" && ot != nt {
			add(Breaking, scope+".property.type.changed", fmt.Sprintf("%s property '%s' type changed: %s -> %s", scope, name, ot, nt))
		}
	}
	for _, name := range sortedKeys(newProps) {
		if _, ok := oldProps[name]; !ok {
			add(Info, scope+".property.added", fmt.Sprintf("%s property '%s' was added", scope, name))
		}
	}
}

func bodySchema(op map[string]any) map[string]any {
	rb := asMap(op["requestBody"])
	if rb == nil {
		return nil
	}
	content := asMap(rb["content"])
	if content == nil {
		return nil
	}
	keys := append([]string{"application/json"}, sortedKeys(content)...)
	for _, ct := range keys {
		if media := asMap(content[ct]); media != nil {
			if sch := asMap(media["schema"]); sch != nil {
				return sch
			}
		}
	}
	return nil
}

func successResponseSchema(op map[string]any) map[string]any {
	responses := asMap(op["responses"])
	for _, code := range []string{"200", "201", "2XX", "default"} {
		if resp := asMap(responses[code]); resp != nil {
			if media := asMap(asMap(resp["content"])["application/json"]); media != nil {
				if sch := asMap(media["schema"]); sch != nil {
					return sch
				}
			}
		}
	}
	return nil
}

// HasBreaking reports whether any change is BREAKING.
func HasBreaking(changes []Change) bool {
	for _, c := range changes {
		if c.Severity == Breaking {
			return true
		}
	}
	return false
}

// Summary counts changes by severity.
func Summary(changes []Change) map[string]int {
	s := map[string]int{"total": len(changes), "breaking": 0, "warning": 0, "info": 0}
	for _, c := range changes {
		switch c.Severity {
		case Breaking:
			s["breaking"]++
		case Warning:
			s["warning"]++
		case Info:
			s["info"]++
		}
	}
	return s
}

// ---- helpers -------------------------------------------------------------
func sortedKeys(m map[string]any) []string {
	if m == nil {
		return nil
	}
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func sortedParamKeys(m map[string]map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func splitKey(k string) (string, string) {
	i := strings.LastIndex(k, " ")
	if i < 0 {
		return k, "query"
	}
	return k[:i], k[i+1:]
}

func stringSet(v any) map[string]bool {
	out := map[string]bool{}
	if arr, ok := v.([]any); ok {
		for _, x := range arr {
			if s, ok := x.(string); ok {
				out[s] = true
			}
		}
	}
	return out
}

func sortedSetDiff(a, b map[string]bool) []string {
	var out []string
	for k := range a {
		if !b[k] {
			out = append(out, k)
		}
	}
	sort.Strings(out)
	return out
}

// ---- CLI -----------------------------------------------------------------
func renderTable(changes []Change) string {
	s := Summary(changes)
	var b strings.Builder
	fmt.Fprintf(&b, "format: openapi\n")
	fmt.Fprintf(&b, "changes: %d  breaking: %d  warning: %d  info: %d\n\n", s["total"], s["breaking"], s["warning"], s["info"])
	if len(changes) == 0 {
		b.WriteString("No changes detected.")
		return b.String()
	}
	order := map[string]int{Breaking: 0, Warning: 1, Info: 2}
	sorted := append([]Change(nil), changes...)
	sort.SliceStable(sorted, func(i, j int) bool { return order[sorted[i].Severity] < order[sorted[j].Severity] })
	for _, c := range sorted {
		fmt.Fprintf(&b, "  [%-8s] %s  %s\n", c.Severity, c.Location, c.Message)
	}
	return b.String()
}

func run(args []string) int {
	if len(args) < 3 || args[0] != "diff" {
		fmt.Fprintln(os.Stderr, "usage: apidiff-go diff OLD NEW [--format table|json]")
		return 2
	}
	format := "table"
	for i, a := range args {
		if a == "--format" && i+1 < len(args) {
			format = args[i+1]
		}
	}
	oldBytes, err := os.ReadFile(args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	newBytes, err := os.ReadFile(args[2])
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	var oldDoc, newDoc map[string]any
	if err := json.Unmarshal(oldBytes, &oldDoc); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	if err := json.Unmarshal(newBytes, &newDoc); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	changes := DiffOpenAPI(oldDoc, newDoc)
	if format == "json" {
		out, _ := json.MarshalIndent(map[string]any{"format": "openapi", "summary": Summary(changes), "changes": changes}, "", "  ")
		fmt.Println(string(out))
	} else {
		fmt.Println(renderTable(changes))
	}
	if HasBreaking(changes) {
		return 1
	}
	return 0
}

func main() { os.Exit(run(os.Args[1:])) }
