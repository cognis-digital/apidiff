# APIDIFF — Architecture

> Breaking-change detector for OpenAPI / GraphQL across commits.

`apidiff` is intentionally small: a single, dependency-free engine that reads two
API definition files, walks them structurally, classifies each difference by who
it hurts, and renders the result in the format your workflow speaks. There is no
plugin system, no config file, and no network path.

## Pipeline

```
OLD file ─┐
          ├─▶ detect_format ─▶ diff walker ─▶ classify ─▶ DiffResult ─▶ renderer ─▶ stdout / --output
NEW file ─┘                    (openapi |     (BREAKING/                (table | json |
                                graphql)      WARNING/INFO)              sarif | markdown | junit)
```

1. **Read** — the CLI opens the two paths you name (`apidiff/cli.py`). The
   embedding entry points `diff_paths()` / `scan()` do the same for MCP and
   scripts. This is the only I/O the engine performs, aside from an optional
   `--output` write.
2. **Detect** — `detect_format()` decides `openapi` vs `graphql` from the
   document text (JSON with an `openapi`/`swagger` key → OpenAPI; an SDL type
   keyword → GraphQL; deterministic fallbacks otherwise). `--fmt` overrides it.
3. **Diff** — one of two structural walkers runs:
   - `diff_openapi()` compares paths, operations, parameters, request-body
     required fields and property types, response schema properties, and success
     status codes.
   - `diff_graphql()` parses a pragmatic SDL subset (`_parse_graphql`) into a
     type map and compares types, fields, arguments, enum values, and
     nullability — **direction-aware**: loosening an output field breaks readers,
     tightening an input field breaks callers.
4. **Classify** — every difference is recorded on a `DiffResult` as a `Change`
   with a `Severity` (`BREAKING` / `WARNING` / `INFO`) and a **stable change
   code** (e.g. `path.removed`, `param.added.required`, `enum.value.removed`).
   Codes are the tool's public contract and are safe to match on in CI.
5. **Render** — `DiffResult` exposes five renderers, all pure functions of the
   classified changes:

   | Renderer | Method | Purpose |
   | --- | --- | --- |
   | Table | `cli._render_table` | Human-readable terminal output (default) |
   | JSON | `to_dict` | Machine-readable, stable schema |
   | SARIF 2.1.0 | `to_sarif` | GitHub / IDE code-scanning ingestion |
   | Markdown | `to_markdown` | PR-comment friendly verdict + tables |
   | JUnit XML | `to_junit` | CI test-report dashboards (breaking → `<failure>`) |

## Key types

- `Severity(str, Enum)` — `BREAKING` / `WARNING` / `INFO`.
- `SEVERITY_ORDER` / `SEVERITY_ICON` — shared presentation order and emoji
  markers so every renderer sorts and labels changes consistently.
- `Change` — `(severity, code, location, message)`; `to_dict()` for JSON.
- `DiffResult` — the collected changes plus:
  - `add()`, `breaking`, `warnings`, `has_breaking()`
  - `sorted_changes()` — most-severe first, stable within a severity
  - `filtered(ignore_codes)` — returns a copy with named codes removed (powers
    `--ignore-code`); never mutates the receiver
  - `to_dict()`, `to_sarif()`, `to_markdown()`, `to_junit()`

## Design properties

- **Deterministic** — same inputs → identical bytes out. No timestamps, no
  network, no randomness.
- **Additive-safe** — new renderers and options extend the surface; JSON, SARIF,
  table output, exit codes, and change codes are stable.
- **Zero runtime dependencies** — Python standard library only. The `mcp` and
  `connect` extras are optional and only load on demand.
- **Read-only / offline** — the diff path never opens a socket.

## Extending

Add a rule inside the relevant walker in `apidiff/core.py`, give it a stable
change code, add a test asserting its severity, and add a
`demos/NN-*/SCENARIO.md` that exercises it. New output formats are methods on
`DiffResult` wired into `cli.main`. New language ports live under `ports/` with a
smoke test in `ports.yml`. See [CONTRIBUTING.md](../CONTRIBUTING.md).
