// Rust port of the apidiff OpenAPI breaking-change engine.
// Fast single static binary, ZERO third-party crates (a tiny stdlib JSON
// parser is bundled below). Mirrors the Python reference CLI:
//
//     apidiff diff OLD.json NEW.json [--format table|json]
//
// Exit code 1 when breaking changes are found, else 0 (2 on IO/usage error).
// Passive, read-only, offline.
use std::collections::BTreeMap;
use std::{env, fs, process};

// ------------------------------------------------------------------ JSON ---
#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(BTreeMap<String, Json>),
}

impl Json {
    fn obj(&self) -> Option<&BTreeMap<String, Json>> {
        if let Json::Obj(m) = self { Some(m) } else { None }
    }
    fn get<'a>(&'a self, k: &str) -> Option<&'a Json> {
        self.obj().and_then(|m| m.get(k))
    }
    fn as_str(&self) -> Option<&str> {
        if let Json::Str(s) = self { Some(s) } else { None }
    }
    fn as_bool(&self) -> bool {
        matches!(self, Json::Bool(true))
    }
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn new(s: &'a str) -> Self {
        Parser { b: s.as_bytes(), i: 0 }
    }
    fn ws(&mut self) {
        while self.i < self.b.len() && (self.b[self.i] as char).is_whitespace() {
            self.i += 1;
        }
    }
    fn parse(&mut self) -> Result<Json, String> {
        self.ws();
        let v = self.value()?;
        self.ws();
        Ok(v)
    }
    fn value(&mut self) -> Result<Json, String> {
        self.ws();
        if self.i >= self.b.len() {
            return Err("unexpected end".into());
        }
        match self.b[self.i] as char {
            '{' => self.object(),
            '[' => self.array(),
            '"' => Ok(Json::Str(self.string()?)),
            't' => self.lit("true", Json::Bool(true)),
            'f' => self.lit("false", Json::Bool(false)),
            'n' => self.lit("null", Json::Null),
            _ => self.number(),
        }
    }
    fn lit(&mut self, s: &str, v: Json) -> Result<Json, String> {
        if self.b[self.i..].starts_with(s.as_bytes()) {
            self.i += s.len();
            Ok(v)
        } else {
            Err(format!("invalid literal at {}", self.i))
        }
    }
    fn object(&mut self) -> Result<Json, String> {
        let mut m = BTreeMap::new();
        self.i += 1; // {
        self.ws();
        if self.i < self.b.len() && self.b[self.i] == b'}' {
            self.i += 1;
            return Ok(Json::Obj(m));
        }
        loop {
            self.ws();
            let key = self.string()?;
            self.ws();
            if self.i >= self.b.len() || self.b[self.i] != b':' {
                return Err("expected ':'".into());
            }
            self.i += 1;
            let val = self.value()?;
            m.insert(key, val);
            self.ws();
            match self.b.get(self.i) {
                Some(b',') => self.i += 1,
                Some(b'}') => {
                    self.i += 1;
                    break;
                }
                _ => return Err("expected ',' or '}'".into()),
            }
        }
        Ok(Json::Obj(m))
    }
    fn array(&mut self) -> Result<Json, String> {
        let mut a = Vec::new();
        self.i += 1; // [
        self.ws();
        if self.i < self.b.len() && self.b[self.i] == b']' {
            self.i += 1;
            return Ok(Json::Arr(a));
        }
        loop {
            let v = self.value()?;
            a.push(v);
            self.ws();
            match self.b.get(self.i) {
                Some(b',') => self.i += 1,
                Some(b']') => {
                    self.i += 1;
                    break;
                }
                _ => return Err("expected ',' or ']'".into()),
            }
        }
        Ok(Json::Arr(a))
    }
    fn string(&mut self) -> Result<String, String> {
        if self.b[self.i] != b'"' {
            return Err("expected string".into());
        }
        self.i += 1;
        let mut s = String::new();
        while self.i < self.b.len() {
            let c = self.b[self.i] as char;
            self.i += 1;
            match c {
                '"' => return Ok(s),
                '\\' => {
                    let e = self.b[self.i] as char;
                    self.i += 1;
                    match e {
                        '"' => s.push('"'),
                        '\\' => s.push('\\'),
                        '/' => s.push('/'),
                        'n' => s.push('\n'),
                        't' => s.push('\t'),
                        'r' => s.push('\r'),
                        'b' => s.push('\u{8}'),
                        'f' => s.push('\u{c}'),
                        'u' => {
                            let hex = std::str::from_utf8(&self.b[self.i..self.i + 4]).unwrap_or("0000");
                            self.i += 4;
                            if let Ok(n) = u32::from_str_radix(hex, 16) {
                                if let Some(ch) = char::from_u32(n) {
                                    s.push(ch);
                                }
                            }
                        }
                        _ => s.push(e),
                    }
                }
                _ => s.push(c),
            }
        }
        Err("unterminated string".into())
    }
    fn number(&mut self) -> Result<Json, String> {
        let start = self.i;
        while self.i < self.b.len() {
            let c = self.b[self.i] as char;
            if c.is_ascii_digit() || matches!(c, '-' | '+' | '.' | 'e' | 'E') {
                self.i += 1;
            } else {
                break;
            }
        }
        let raw = std::str::from_utf8(&self.b[start..self.i]).unwrap_or("");
        raw.parse::<f64>().map(Json::Num).map_err(|_| "bad number".into())
    }
}

pub fn parse_json(s: &str) -> Result<Json, String> {
    Parser::new(s).parse()
}

// ----------------------------------------------------------------- engine ---
#[derive(Debug, Clone)]
pub struct Change {
    pub severity: &'static str,
    pub code: String,
    pub location: String,
    pub message: String,
}

const BREAKING: &str = "BREAKING";
const WARNING: &str = "WARNING";
const INFO: &str = "INFO";
const METHODS: [&str; 7] = ["get", "put", "post", "delete", "patch", "head", "options"];

fn empty_obj() -> Json {
    Json::Obj(BTreeMap::new())
}

pub fn diff_openapi(old_doc: &Json, new_doc: &Json) -> Vec<Change> {
    let mut changes: Vec<Change> = Vec::new();
    let eo = empty_obj();
    let old_paths = old_doc.get("paths").unwrap_or(&eo);
    let new_paths = new_doc.get("paths").unwrap_or(&eo);
    let empty = BTreeMap::new();
    let op_map = old_paths.obj().unwrap_or(&empty);
    let np_map = new_paths.obj().unwrap_or(&empty);

    for p in op_map.keys() {
        if !np_map.contains_key(p) {
            changes.push(Change { severity: BREAKING, code: "path.removed".into(), location: p.clone(), message: format!("Path '{}' was removed", p) });
        }
    }
    for p in np_map.keys() {
        if !op_map.contains_key(p) {
            changes.push(Change { severity: INFO, code: "path.added".into(), location: p.clone(), message: format!("Path '{}' was added", p) });
        }
    }

    for p in op_map.keys() {
        if !np_map.contains_key(p) {
            continue;
        }
        let old_item = &op_map[p];
        let new_item = &np_map[p];
        for m in METHODS.iter() {
            let old_op = old_item.get(m);
            let new_op = new_item.get(m);
            let loc = format!("{} {}", m.to_uppercase(), p);
            match (old_op, new_op) {
                (Some(_), None) => changes.push(Change { severity: BREAKING, code: "operation.removed".into(), location: loc.clone(), message: format!("Operation '{}' was removed", loc) }),
                (None, Some(_)) => changes.push(Change { severity: INFO, code: "operation.added".into(), location: loc.clone(), message: format!("Operation '{}' was added", loc) }),
                (Some(o), Some(n)) => diff_operation(&mut changes, &loc, o, n),
                _ => {}
            }
        }
    }
    changes
}

fn params_index(op: &Json) -> BTreeMap<String, &Json> {
    let mut out = BTreeMap::new();
    if let Some(Json::Arr(arr)) = op.get("parameters") {
        for pr in arr {
            if let Some(name) = pr.get("name").and_then(|v| v.as_str()) {
                let where_ = pr.get("in").and_then(|v| v.as_str()).unwrap_or("query");
                out.insert(format!("{} {}", name, where_), pr);
            }
        }
    }
    out
}

fn required(p: &Json) -> bool {
    p.get("required").map(|v| v.as_bool()).unwrap_or(false)
}

fn diff_operation(changes: &mut Vec<Change>, loc: &str, old_op: &Json, new_op: &Json) {
    let old_params = params_index(old_op);
    let new_params = params_index(new_op);

    for key in old_params.keys() {
        if !new_params.contains_key(key) {
            let (name, where_) = split_key(key);
            changes.push(Change { severity: WARNING, code: "param.removed".into(), location: loc.into(), message: format!("Parameter '{}' (in: {}) was removed", name, where_) });
        }
    }
    for (key, p) in new_params.iter() {
        let (name, where_) = split_key(key);
        match old_params.get(key) {
            None => {
                if required(p) {
                    changes.push(Change { severity: BREAKING, code: "param.added.required".into(), location: loc.into(), message: format!("New required parameter '{}' (in: {}) added", name, where_) });
                } else {
                    changes.push(Change { severity: INFO, code: "param.added".into(), location: loc.into(), message: format!("New optional parameter '{}' (in: {}) added", name, where_) });
                }
            }
            Some(old_p) => {
                if required(p) && !required(old_p) {
                    changes.push(Change { severity: BREAKING, code: "param.required.added".into(), location: loc.into(), message: format!("Parameter '{}' (in: {}) became required", name, where_) });
                } else if required(old_p) && !required(p) {
                    changes.push(Change { severity: INFO, code: "param.required.removed".into(), location: loc.into(), message: format!("Parameter '{}' (in: {}) is no longer required", name, where_) });
                }
            }
        }
    }

    if let (Some(old_body), Some(new_body)) = (body_schema(old_op), body_schema(new_op)) {
        let old_req = string_set(old_body.get("required"));
        let new_req = string_set(new_body.get("required"));
        let mut added: Vec<&String> = new_req.iter().filter(|x| !old_req.contains(*x)).collect();
        added.sort();
        for f in added {
            changes.push(Change { severity: BREAKING, code: "requestBody.required.added".into(), location: loc.into(), message: format!("Request body field '{}' became required", f) });
        }
        let mut removed: Vec<&String> = old_req.iter().filter(|x| !new_req.contains(*x)).collect();
        removed.sort();
        for f in removed {
            changes.push(Change { severity: INFO, code: "requestBody.required.removed".into(), location: loc.into(), message: format!("Request body field '{}' is no longer required", f) });
        }
        diff_props(changes, loc, "requestBody", old_body.get("properties"), new_body.get("properties"), false);
    }

    if let (Some(old_resp), Some(new_resp)) = (success_response_schema(old_op), success_response_schema(new_op)) {
        diff_props(changes, loc, "response", old_resp.get("properties"), new_resp.get("properties"), true);
    }

    if let (Some(oc), Some(nc)) = (old_op.get("responses").and_then(|v| v.obj()), new_op.get("responses").and_then(|v| v.obj())) {
        for code in oc.keys() {
            if !nc.contains_key(code) && code.starts_with('2') {
                changes.push(Change { severity: BREAKING, code: "response.removed".into(), location: loc.into(), message: format!("Success response '{}' was removed", code) });
            }
        }
    }
}

fn diff_props(changes: &mut Vec<Change>, loc: &str, scope: &str, old_props: Option<&Json>, new_props: Option<&Json>, removed_breaking: bool) {
    let empty = BTreeMap::new();
    let op = old_props.and_then(|v| v.obj()).unwrap_or(&empty);
    let np = new_props.and_then(|v| v.obj()).unwrap_or(&empty);
    for name in op.keys() {
        if !np.contains_key(name) {
            let sev = if removed_breaking { BREAKING } else { WARNING };
            changes.push(Change { severity: sev, code: format!("{}.property.removed", scope), location: loc.into(), message: format!("{} property '{}' was removed", scope, name) });
            continue;
        }
        let ot = op[name].get("type").and_then(|v| v.as_str());
        let nt = np[name].get("type").and_then(|v| v.as_str());
        if let (Some(ot), Some(nt)) = (ot, nt) {
            if ot != nt {
                changes.push(Change { severity: BREAKING, code: format!("{}.property.type.changed", scope), location: loc.into(), message: format!("{} property '{}' type changed: {} -> {}", scope, name, ot, nt) });
            }
        }
    }
    for name in np.keys() {
        if !op.contains_key(name) {
            changes.push(Change { severity: INFO, code: format!("{}.property.added", scope), location: loc.into(), message: format!("{} property '{}' was added", scope, name) });
        }
    }
}

fn body_schema(op: &Json) -> Option<&Json> {
    let content = op.get("requestBody")?.get("content")?.obj()?;
    let mut keys: Vec<&str> = content.keys().map(|s| s.as_str()).collect();
    keys.sort();
    let mut ordered: Vec<&str> = vec!["application/json"];
    ordered.extend(keys);
    for ct in ordered {
        if let Some(media) = content.get(ct) {
            if let Some(sch) = media.get("schema") {
                return Some(sch);
            }
        }
    }
    None
}

fn success_response_schema(op: &Json) -> Option<&Json> {
    let responses = op.get("responses")?;
    for code in ["200", "201", "2XX", "default"].iter() {
        if let Some(resp) = responses.get(code) {
            if let Some(sch) = resp.get("content").and_then(|c| c.get("application/json")).and_then(|m| m.get("schema")) {
                return Some(sch);
            }
        }
    }
    None
}

fn split_key(k: &str) -> (&str, &str) {
    match k.rfind(' ') {
        Some(i) => (&k[..i], &k[i + 1..]),
        None => (k, "query"),
    }
}

fn string_set(v: Option<&Json>) -> Vec<String> {
    if let Some(Json::Arr(arr)) = v {
        arr.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect()
    } else {
        Vec::new()
    }
}

pub fn has_breaking(changes: &[Change]) -> bool {
    changes.iter().any(|c| c.severity == BREAKING)
}

pub fn summary(changes: &[Change]) -> (usize, usize, usize, usize) {
    let mut b = 0;
    let mut w = 0;
    let mut i = 0;
    for c in changes {
        match c.severity {
            BREAKING => b += 1,
            WARNING => w += 1,
            INFO => i += 1,
            _ => {}
        }
    }
    (changes.len(), b, w, i)
}

// -------------------------------------------------------------------- CLI ---
fn render_table(changes: &[Change]) -> String {
    let (t, b, w, i) = summary(changes);
    let mut out = String::new();
    out.push_str("format: openapi\n");
    out.push_str(&format!("changes: {}  breaking: {}  warning: {}  info: {}\n\n", t, b, w, i));
    if changes.is_empty() {
        out.push_str("No changes detected.");
        return out;
    }
    let order = |s: &str| match s { BREAKING => 0, WARNING => 1, _ => 2 };
    let mut sorted: Vec<&Change> = changes.iter().collect();
    sorted.sort_by_key(|c| order(c.severity));
    for c in sorted {
        out.push_str(&format!("  [{:<8}] {}  {}\n", c.severity, c.location, c.message));
    }
    out
}

fn esc(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n")
}

fn render_json(changes: &[Change]) -> String {
    let (t, b, w, i) = summary(changes);
    let mut out = String::new();
    out.push_str("{\n");
    out.push_str("  \"format\": \"openapi\",\n");
    out.push_str(&format!("  \"summary\": {{\"total\": {}, \"breaking\": {}, \"warning\": {}, \"info\": {}}},\n", t, b, w, i));
    out.push_str("  \"changes\": [\n");
    for (idx, c) in changes.iter().enumerate() {
        let comma = if idx + 1 < changes.len() { "," } else { "" };
        out.push_str(&format!(
            "    {{\"severity\": \"{}\", \"code\": \"{}\", \"location\": \"{}\", \"message\": \"{}\"}}{}\n",
            c.severity, esc(&c.code), esc(&c.location), esc(&c.message), comma
        ));
    }
    out.push_str("  ]\n}");
    out
}

fn run(args: &[String]) -> i32 {
    if args.len() < 3 || args[0] != "diff" {
        eprintln!("usage: apidiff diff OLD NEW [--format table|json]");
        return 2;
    }
    let mut format = "table";
    let mut idx = 0;
    while idx < args.len() {
        if args[idx] == "--format" && idx + 1 < args.len() {
            format = &args[idx + 1];
        }
        idx += 1;
    }
    let old_text = match fs::read_to_string(&args[1]) {
        Ok(t) => t,
        Err(e) => { eprintln!("error: {}", e); return 2; }
    };
    let new_text = match fs::read_to_string(&args[2]) {
        Ok(t) => t,
        Err(e) => { eprintln!("error: {}", e); return 2; }
    };
    let old_doc = match parse_json(&old_text) { Ok(d) => d, Err(e) => { eprintln!("error: {}", e); return 2; } };
    let new_doc = match parse_json(&new_text) { Ok(d) => d, Err(e) => { eprintln!("error: {}", e); return 2; } };
    let changes = diff_openapi(&old_doc, &new_doc);
    if format == "json" {
        println!("{}", render_json(&changes));
    } else {
        println!("{}", render_table(&changes));
    }
    if has_breaking(&changes) { 1 } else { 0 }
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    process::exit(run(&args));
}

// ------------------------------------------------------------------ tests ---
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_json_roundtrip() {
        let j = parse_json(r#"{"a": 1, "b": [true, "x"], "c": {"d": null}}"#).unwrap();
        assert_eq!(j.get("a"), Some(&Json::Num(1.0)));
        assert_eq!(j.get("b").unwrap(), &Json::Arr(vec![Json::Bool(true), Json::Str("x".into())]));
        assert!(j.get("c").unwrap().get("d").is_some());
    }

    fn diff(o: &str, n: &str) -> Vec<Change> {
        diff_openapi(&parse_json(o).unwrap(), &parse_json(n).unwrap())
    }

    #[test]
    fn test_removed_path_is_breaking() {
        let c = diff(r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}"#, r#"{"openapi":"3.0.0","paths":{}}"#);
        assert!(has_breaking(&c));
        assert!(c.iter().any(|x| x.code == "path.removed"));
    }

    #[test]
    fn test_new_required_param_is_breaking() {
        let o = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[],"responses":{}}}}}"#;
        let n = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[{"name":"q","in":"query","required":true}],"responses":{}}}}}"#;
        assert!(diff(o, n).iter().any(|x| x.code == "param.added.required"));
    }

    #[test]
    fn test_added_optional_param_not_breaking() {
        let o = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[],"responses":{}}}}}"#;
        let n = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[{"name":"q","in":"query","required":false}],"responses":{}}}}}"#;
        assert!(!has_breaking(&diff(o, n)));
    }

    #[test]
    fn test_response_property_removal_is_breaking() {
        let o = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{"content":{"application/json":{"schema":{"properties":{"x":{"type":"string"}}}}}}}}}}"#;
        let n = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{"content":{"application/json":{"schema":{"properties":{}}}}}}}}}"#;
        assert!(diff(o, n).iter().any(|x| x.code == "response.property.removed"));
    }

    #[test]
    fn test_identical_no_changes() {
        let d = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}"#;
        assert_eq!(diff(d, d).len(), 0);
    }

    #[test]
    fn test_status_code_dropped_is_breaking() {
        let o = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{},"206":{}}}}}}"#;
        let n = r#"{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{}}}}}}"#;
        assert!(diff(o, n).iter().any(|x| x.code == "response.removed"));
    }
}
