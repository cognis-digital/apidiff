# APIDIFF — Roadmap

This roadmap describes direction, not commitments. Change codes, the JSON/SARIF
schemas, exit codes, and the table output are treated as a stable public contract
— new work is **additive** and must not break them. Open an issue or PR to shape
priorities; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Shipped

- Structural diff for **OpenAPI 3.x / Swagger 2.0** (JSON) and **GraphQL SDL**.
- Severity model **BREAKING / WARNING / INFO** with **stable change codes**.
- Output renderers: **table · JSON · SARIF 2.1.0 · Markdown · JUnit XML**.
- CI gate via exit codes + `--fail-on breaking|warning|never`.
- `--ignore-code CODE` (repeatable) to acknowledge accepted changes, and
  `--output FILE` to write reports as artifacts.
- **MCP server** (`apidiff mcp`) and `apidiff-emit` forwarder (cognis-connect).
- Polyglot ports (JavaScript / Go / Rust) verified against the OpenAPI demos.
- CI across Linux/macOS/Windows and Python 3.10–3.12, plus a lint job.

## Near-term

- **YAML input**: read OpenAPI directly from YAML (optional dependency, JSON path
  unchanged) so users skip the manual convert step.
- **`$ref` resolution**: follow local `#/components/...` references before
  diffing so component-level schema changes are detected at every use site.
- **Baseline / suppression file**: an `apidiff.toml` (or `--ignore-file`) that
  records accepted change codes and locations, complementing `--ignore-code`.
- **Deprecation awareness**: treat OpenAPI `deprecated: true` and the GraphQL
  `@deprecated` directive as first-class signals (grace-period WARNING before a
  removal is scored BREAKING).
- **Richer GraphQL coverage**: `interface`/`union` membership changes, directive
  changes, and default-value changes on arguments and input fields.

## Mid-term

- **Config-driven severity policy**: let teams promote/demote specific codes
  (e.g. treat `enum.value.added` as INFO for their consumers) via config, without
  code changes.
- **Multi-version / changelog mode**: diff a chain of N revisions and emit a
  consolidated, human-readable API changelog.
- **HTML report renderer**: a self-contained, shareable report artifact.
- **gRPC / Protobuf** front-end reusing the same severity model and codes.
- **Pre-commit hook** and a first-class GitHub Action wrapper.

## Long-term

- **Consumer-impact analysis**: given recorded client usage, rank breaking
  changes by how many consumers each one actually affects.
- **Plugin API** for custom detectors and renderers, with a stable extension
  contract and a conformance test kit.
- **PyPI GA (v1.0)** with semantic-versioning guarantees on codes and schemas,
  plus commercial support (licensing@cognis.digital).

## Non-goals

- Calling or actively scanning live APIs — apidiff stays passive, read-only, and
  offline by design.
- Heavyweight runtime dependencies in the core — the standard-library-only
  guarantee is a feature.
