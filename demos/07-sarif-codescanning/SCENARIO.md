# Demo 07 — SARIF output for GitHub code scanning

**Where the data came from:** an Accounts API going from `4.2.0` to `5.0.0`.
This demo focuses on the `--format sarif` output so the findings show up in the
GitHub **Security → Code scanning** tab (or any SARIF-aware viewer).

**Changes in this diff:**

1. `DELETE /v1/accounts/{id}` **removed** — BREAKING.
2. New **required** query parameter `region` on `GET /v1/accounts/{id}` — BREAKING.
3. Response property `legacyToken` **removed** — BREAKING.

## Run — emit SARIF 2.1.0

```bash
python -m apidiff diff demos/07-sarif-codescanning/openapi.old.json \
                       demos/07-sarif-codescanning/openapi.new.json \
                       --format sarif > apidiff.sarif
```

Then upload it in CI:

```yaml
# .github/workflows/api-contract.yml
- run: apidiff diff openapi.old.json openapi.new.json --format sarif > apidiff.sarif
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: apidiff.sarif
```

## What to expect

A valid SARIF log: one `tool.driver.rules` entry per change `code`, one
`results` entry per change, with `level` `error` (BREAKING), `warning`, or
`note` (INFO). The CLI still exits **1** so the job fails the gate too.

## How to act

Triage the breaking findings directly in the code-scanning UI, then deprecate
rather than remove (`legacyToken`), or coordinate the major bump (`region`,
deleted operation) with consumers.
