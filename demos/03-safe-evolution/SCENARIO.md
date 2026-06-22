# Demo 03 — A safe, additive release (zero breaking changes)

**Where the data came from:** an internal Orders API. The `1.4.0 -> 1.5.0`
release only *adds* capability — exactly the kind of change that should sail
through CI without a manual approval.

**Changes in this diff:**

1. New **optional** query parameter `currency` on `GET /orders` — INFO.
2. New response property `currency` — INFO (additive; existing readers ignore it).
3. New operation `POST /orders/{orderId}/refunds` — INFO.

## Run

```bash
python -m apidiff diff demos/03-safe-evolution/openapi.old.json \
                       demos/03-safe-evolution/openapi.new.json
```

## What to expect

Exit code **0** — no breaking changes. This is the "green build" case. With the
default `--fail-on breaking`, CI passes and the PR can auto-merge.

```
changes: 3  breaking: 0  warning: 0  info: 3
```

## How to act

Nothing to do — ship it. If your policy is stricter, `--fail-on warning` would
still pass here since there are no warnings either.
