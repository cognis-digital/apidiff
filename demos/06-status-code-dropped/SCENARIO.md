# Demo 06 — Dropped success status code + removed parameter

**Where the data came from:** a Search API that used to stream partial results
with HTTP `206 Partial Content`. The team removed streaming and also dropped the
`lang` query parameter. The `206` removal is breaking for clients that special-
case it; the parameter removal is a softer warning.

**Changes in this diff:**

1. Success response `206` **removed** — BREAKING (clients handling 206 break).
2. Query parameter `lang` **removed** — WARNING (request still works, but a
   feature consumers relied on is gone).

## Run

```bash
python -m apidiff diff demos/06-status-code-dropped/openapi.old.json \
                       demos/06-status-code-dropped/openapi.new.json
```

## What to expect

Exit code **1** (because of the `206` removal). Highlights:

```
  [BREAKING] GET /search   Success response '206' was removed
  [WARNING ] GET /search   Parameter 'lang' (in: query) was removed
```

Run with `--fail-on warning` to also fail builds on the parameter removal.

## How to act

If any consumer parses `206` responses, restore it or coordinate a deprecation.
Document the removed `lang` parameter in the changelog.
