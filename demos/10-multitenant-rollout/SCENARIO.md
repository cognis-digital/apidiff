# Demo 10 — Multi-tenant rollout (mixed severities across many paths)

**Where the data came from:** a Reports API going `3.0.0 -> 4.0.0` as the
product becomes multi-tenant. This is a realistic "big PR" with a mix of
breaking, additive, and safe changes — exactly where a diff tool earns its keep.

**Changes in this diff:**

1. New **required** header `tenantId` on `GET /reports` — BREAKING.
2. `GET /legacy/ping` operation/path **removed** — BREAKING.
3. New optional query param `format` on `GET /reports/{id}/export` — INFO.
4. New operation `POST /reports/{id}/schedule` — INFO.

## Run

```bash
python -m apidiff diff demos/10-multitenant-rollout/openapi.old.json \
                       demos/10-multitenant-rollout/openapi.new.json
```

Machine-readable for triage dashboards:

```bash
python -m apidiff diff demos/10-multitenant-rollout/openapi.old.json \
                       demos/10-multitenant-rollout/openapi.new.json --format json
```

## What to expect

Exit code **1**. The summary line shows the mix, e.g.:

```
changes: 4  breaking: 2  warning: 0  info: 2
  [BREAKING] GET /reports     New required parameter 'tenantId' (in: header) added
  [BREAKING] /legacy/ping     Path '/legacy/ping' was removed
  [INFO    ] GET /reports/{id}/export  New optional parameter 'format' (in: query) added
  [INFO    ] POST /reports/{id}/schedule  Operation 'POST /reports/{id}/schedule' was added
```

## How to act

The two breaking items need attention: provide a transition window where
`tenantId` is optional (inferred from auth), and keep `/legacy/ping` until you
confirm no health-checks depend on it. The INFO items are safe to ship.
