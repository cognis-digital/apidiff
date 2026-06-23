# Ports of apidiff

The same **OpenAPI breaking-change engine**, ported across languages so you can
drop apidiff into any stack or ship a single static binary. Every port:

- mirrors the reference CLI surface — `diff OLD NEW [--format table|json]`
- emits the **same change codes** (`path.removed`, `operation.removed`,
  `param.added.required`, `response.property.removed`, `response.removed`,
  `requestBody.required.added`, …) and the same JSON shape
  (`{ format, summary, changes[] }`)
- uses the **same exit-code contract**: `1` when breaking changes are found,
  `0` when clean, `2` on IO/usage error
- has **zero third-party dependencies** (the Rust port bundles a tiny stdlib
  JSON parser; Go and Node use only their standard libraries)
- ships a **smoke test** verified in CI on every push (see
  [`.github/workflows/ports.yml`](../.github/workflows/ports.yml))

The Python port is the reference implementation; the JavaScript port is byte-for-byte
verified against it across the OpenAPI [`demos/`](../demos) (identical change sets).

| Language | Path | Run | Test |
|---|---|---|---|
| Python (reference) | [`../apidiff/`](../apidiff) | `apidiff diff old.json new.json` | `python -m pytest` |
| JavaScript / Node | [`javascript/`](javascript) | `node ports/javascript/index.js diff old.json new.json` | `node --test ports/javascript/test.js` |
| Go | [`go/`](go) | `cd ports/go && go run . diff ../../demos/01-basic/openapi.old.json ../../demos/01-basic/openapi.new.json` | `cd ports/go && go test ./...` |
| Rust | [`rust/`](rust) | `cd ports/rust && cargo run -- diff ../../demos/01-basic/openapi.old.json ../../demos/01-basic/openapi.new.json` | `cd ports/rust && cargo test` |

> **Scope.** The ports implement the **OpenAPI 3.x (JSON)** diff surface, which
> is the most common CI use-case. GraphQL SDL diffing currently lives in the
> Python reference port only. The ports are passive and read-only — they open
> two local files and compare them; no network, no active scanning.

## Example — same output, four languages

```bash
$ node ports/javascript/index.js diff demos/01-basic/openapi.old.json demos/01-basic/openapi.new.json
format: openapi
changes: 4  breaking: 3  warning: 0  info: 1

  [BREAKING] DELETE /pets/{petId}  Operation 'DELETE /pets/{petId}' was removed
  [BREAKING] GET /pets             New required parameter 'tenant' (in: query) added
  [BREAKING] GET /pets             response property 'tag' was removed
  [INFO    ] /pets/{petId}/notes   Path '/pets/{petId}/notes' was added
```

Contributions of additional ports (Ruby, C#, Bun, Deno, WASM) are welcome — see
[../CONTRIBUTING.md](../CONTRIBUTING.md). New ports should add a smoke test wired
into `ports.yml` and verify against the OpenAPI demos.
