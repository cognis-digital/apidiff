# APIDIFF — Usage

A task-oriented guide to the `apidiff` CLI, its output formats, and CI wiring.
Everything here runs offline and read-only.

## Install

```bash
pip install cognis-apidiff                                       # PyPI
pip install "git+https://github.com/cognis-digital/apidiff.git"  # from source
pip install "cognis-apidiff[mcp]"                                # + MCP server extra
```

## Command reference

```
apidiff diff OLD NEW [options]
apidiff mcp
apidiff --version
```

### `diff` options

| Option | Values | Default | Effect |
| --- | --- | --- | --- |
| `--format` | `table`, `json`, `sarif`, `markdown`, `junit` | `table` | Output renderer |
| `--fmt` | `auto`, `openapi`, `graphql` | `auto` | Input format (override auto-detect) |
| `--fail-on` | `breaking`, `warning`, `never` | `breaking` | Severity threshold for a non-zero exit |
| `--ignore-code CODE` | any change code, repeatable | — | Suppress a change from output **and** exit code |
| `--output FILE`, `-o` | path | stdout | Write the report to a file |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No changes at or above the `--fail-on` threshold |
| `1` | Threshold breached (e.g. breaking changes found) |
| `2` | Usage or I/O error (bad path, unreadable file, unwritable `--output`) |

## Output formats

### Table (default)

```bash
apidiff diff openapi.old.json openapi.new.json
```

```text
format: openapi
changes: 4  breaking: 3  warning: 0  info: 1

  [BREAKING] DELETE /pets/{petId}  Operation 'DELETE /pets/{petId}' was removed
  [BREAKING] GET /pets             New required parameter 'tenant' (in: query) added
  [BREAKING] GET /pets             response property 'tag' was removed
  [INFO    ] /pets/{petId}/notes   Path '/pets/{petId}/notes' was added
```

### JSON

Stable schema — `format`, `summary` (counts), and `changes[]`
(`severity`, `code`, `location`, `message`). Pipe it into any tool or agent.

```bash
apidiff diff openapi.old.json openapi.new.json --format json
```

### SARIF 2.1.0

For GitHub code scanning and SARIF-aware IDEs. Each change code becomes a rule;
each change becomes a result. `BREAKING → error`, `WARNING → warning`,
`INFO → note`.

```bash
apidiff diff openapi.old.json openapi.new.json --format sarif -o apidiff.sarif
```

### Markdown

A PR-comment-friendly report: a verdict line, a severity-count table, and a
per-change table sorted most-severe first.

```bash
apidiff diff openapi.old.json openapi.new.json --format markdown -o apidiff.md
```

```markdown
## API diff

**🔴 Breaking changes detected** — format `openapi`

| Severity | Count |
| --- | ---: |
| 🔴 BREAKING | 3 |
| 🟡 WARNING | 0 |
| 🟢 INFO | 1 |
| **Total** | **4** |

| Severity | Code | Location | Message |
| --- | --- | --- | --- |
| 🔴 BREAKING | `operation.removed` | `DELETE /pets/{petId}` | Operation 'DELETE /pets/{petId}' was removed |
| ... |
```

### JUnit XML

For CI test dashboards. Each change is a `<testcase>`; every BREAKING change is a
`<failure>`, so the report goes red exactly when the diff is breaking.

```bash
apidiff diff openapi.old.json openapi.new.json --format junit -o apidiff.xml
```

## Acknowledging accepted changes

Sometimes a "breaking" change is intentional and already coordinated with
consumers. Suppress just that change code — it is removed from the report and no
longer influences the exit code — while every other check keeps failing the build:

```bash
# accept an added enum value and a removed optional param, still gate on the rest
apidiff diff old.json new.json \
  --ignore-code enum.value.added \
  --ignore-code param.removed
```

## CI recipes

### GitHub Actions — gate a PR and attach a Markdown summary

```yaml
- name: API contract check
  run: |
    pip install cognis-apidiff
    apidiff diff "$BASE/openapi.json" openapi.json --format markdown -o apidiff.md
    apidiff diff "$BASE/openapi.json" openapi.json --fail-on breaking
```

### Upload a JUnit report

```yaml
- name: API diff (JUnit)
  run: apidiff diff base.json head.json --format junit -o apidiff.xml --fail-on never
- uses: actions/upload-artifact@v4
  with:
    name: apidiff-junit
    path: apidiff.xml
```

### Publish SARIF to code scanning

```yaml
- run: apidiff diff base.json head.json --format sarif -o apidiff.sarif --fail-on never
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: apidiff.sarif
```

## From code / agents

```python
from apidiff.core import diff_paths, scan

result = diff_paths("old.json", "new.json")     # DiffResult
print(result.to_markdown())                      # or .to_dict(), .to_sarif(), .to_junit()
print("breaking?", result.has_breaking())

payload = scan("old.json", "new.json")           # dict (MCP/agent-friendly)
```

The MCP server exposes the same capability as an `apidiff_diff(old_path,
new_path, fmt)` tool:

```bash
apidiff mcp   # requires the 'mcp' extra
```
