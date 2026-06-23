# apidiff — Advanced usage

apidiff compares two API definition files (a baseline and a candidate) and
classifies what changed. It is offline and read-only: there is no server, no
network access, and no active scanning. The CLI surface is:

```text
apidiff diff OLD NEW [--format table|json|sarif] [--fmt auto|openapi|graphql] [--fail-on breaking|warning|never]
apidiff mcp        # MCP stdio server (needs the 'mcp' extra)
apidiff --version
```

## CI gate (fail the build on breaking changes)

Compare the API definition on the PR branch against the one on the base branch.

```yaml
- run: pip install cognis-apidiff
- name: Check API contract
  run: |
    git show "origin/${{ github.base_ref }}:openapi.json" > /tmp/openapi.base.json
    apidiff diff /tmp/openapi.base.json openapi.json --format sarif --fail-on breaking > apidiff.sarif
- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with: { sarif_file: apidiff.sarif }
```

`--fail-on breaking` (default) exits non-zero only on BREAKING changes; use
`--fail-on warning` to also fail on WARNING, or `--fail-on never` to report
without failing the build.

## Pipe into a SIEM / webhook

```bash
apidiff diff openapi.old.json openapi.new.json --format json \
  | python integrations/webhook.py --url "$COGNIS_WEBHOOK_URL"
```

Or forward via cognis-connect (STIX / MISP / Sigma / Splunk / Elastic / Slack):

```bash
apidiff diff openapi.old.json openapi.new.json --format json \
  | apidiff-emit --to slack --url "$WEBHOOK" --dry-run
```

## Drive it from an AI agent (MCP)

```jsonc
// claude_desktop_config.json
{ "mcpServers": { "apidiff": { "command": "apidiff", "args": ["mcp"] } } }
```

The MCP server exposes one tool: `apidiff_diff(old_path, new_path, fmt="auto")`,
which returns the classified changes as JSON. Requires the extra:
`pip install "cognis-apidiff[mcp]"`.

## Run a language port instead of Python

Each port mirrors the `diff OLD NEW [--format table|json]` surface and the same
exit-code contract (1 = breaking, 0 = clean, 2 = error).

```bash
node ports/javascript/index.js diff old.json new.json            # Node
( cd ports/go && go run . diff ../../old.json ../../new.json )    # Go single binary
( cd ports/rust && cargo run -- diff ../../old.json ../../new.json ) # Rust, zero crates
```

## Convert YAML specs first

OpenAPI documents are read as JSON. If your spec is YAML, convert it before
diffing:

```bash
python -c "import sys,yaml,json; json.dump(yaml.safe_load(open(sys.argv[1])), open(sys.argv[2],'w'))" \
  openapi.yaml openapi.json
apidiff diff openapi.base.json openapi.json
```
