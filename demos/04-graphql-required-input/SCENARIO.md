# Demo 04 — New required GraphQL input field & argument

**Where the data came from:** a checkout/payments GraphQL service. To make
checkout idempotent the team added a required `idempotencyKey` to
`CheckoutInput` and a required `reason` argument to `cancelOrder`. Both are the
*right* engineering call — but both break every existing client immediately.

**Changes in this diff:**

1. `CheckoutInput.idempotencyKey: String!` **added (required)** — BREAKING.
2. `Mutation.cancelOrder(reason: String!)` **new required argument** — BREAKING.

## Run

```bash
python -m apidiff diff demos/04-graphql-required-input/schema.old.graphql \
                       demos/04-graphql-required-input/schema.new.graphql
```

## What to expect

Exit code **1**. Highlights:

```
  [BREAKING] CheckoutInput.idempotencyKey  New required input field 'CheckoutInput.idempotencyKey' was added
  [BREAKING] Mutation.cancelOrder          New required argument 'reason: String!' on 'Mutation.cancelOrder'
```

## How to act

Make the new field/argument **nullable** first, ship clients that send it, then
flip to required in a later major version. apidiff lets you gate this in CI so
the required-by-default change can't merge silently.
