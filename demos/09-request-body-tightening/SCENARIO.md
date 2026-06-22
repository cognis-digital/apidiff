# Demo 09 — Request body field becomes required

**Where the data came from:** a Signup API. Product decided `displayName` should
be mandatory at account creation, so it was added to the request body's
`required` list. Existing clients that omit it will now get a `400`.

**Changes in this diff:**

1. Request body field `displayName` **became required** — BREAKING.

## Run

```bash
python -m apidiff diff demos/09-request-body-tightening/openapi.old.json \
                       demos/09-request-body-tightening/openapi.new.json
```

## What to expect

Exit code **1**. Highlights:

```
  [BREAKING] POST /users   Request body field 'displayName' became required
```

## How to act

Tightening a request contract is breaking. Either keep `displayName` optional
and default it server-side, or roll the requirement out behind a version flag
once clients are updated. The inverse change (making a required field optional)
is reported as INFO — safe.
