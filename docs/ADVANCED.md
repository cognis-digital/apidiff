# apidiff — Advanced usage

## CI gate (fail the build on findings)
```yaml
- run: pip install cognis-apidiff
- run: apidiff scan . --format sarif --out apidiff.sarif --fail-on high
- uses: github/codeql-action/upload-sarif@v3
  with: { sarif_file: apidiff.sarif }
```

## Pipe into a SIEM / webhook
```bash
apidiff scan . --format json | python integrations/webhook.py --url "$COGNIS_WEBHOOK_URL"
```

## Drive it from an AI agent (MCP)
```jsonc
// claude_desktop_config.json
{ "mcpServers": { "apidiff": { "command": "apidiff", "args": ["mcp"] } } }
```

## Run a language port instead of Python
```bash
node ports/javascript/index.js .     # Node
( cd ports/go && go run . .. )        # Go single binary
( cd ports/rust && cargo run -- .. )  # Rust
```

## Ports & services
Default service/forward ports: **8000** (HTTP API), **8080** (alt), **3000** (UI), **9090** (metrics).
