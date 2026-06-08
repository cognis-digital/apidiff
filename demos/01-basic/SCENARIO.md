# Demo 01 — Catching an OpenAPI breaking change in CI

A team maintains a `petstore` REST API described by OpenAPI 3.0. Between two
commits they make several changes to `openapi.old.json` -> `openapi.new.json`:

1. **Removed** the `DELETE /pets/{petId}` operation — BREAKING (clients calling
   it will start getting 404s).
2. **Added a new required query parameter** `tenant` to `GET /pets` — BREAKING
   (existing callers don't send it).
3. **Removed** the `tag` property from the `Pet` response body — BREAKING
   (clients reading `tag` will get `undefined`).
4. **Added** a new optional `POST /pets/{petId}/notes` operation — INFO (safe).

Run the detector:

```bash
python -m apidiff diff demos/01-basic/openapi.old.json \
                        demos/01-basic/openapi.new.json
```

Get machine-readable output for CI gating:

```bash
python -m apidiff diff demos/01-basic/openapi.old.json \
                        demos/01-basic/openapi.new.json --format json
```

The process exits **1** because breaking changes were found, so the CI step
fails and the change is caught before release. Use `--fail-on never` to report
without failing the build, or `--fail-on warning` to be stricter.

Expected (table) highlights:

```
  [BREAKING] DELETE /pets/{petId}   Operation 'DELETE /pets/{petId}' was removed
  [BREAKING] GET /pets              New required parameter 'tenant' (in: query) added
  [BREAKING] GET /pets              response property 'tag' was removed
  [INFO    ] POST /pets/{petId}/notes  Operation 'POST /pets/{petId}/notes' was added
```
