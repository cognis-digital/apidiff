# Demo 08 — GraphQL enum churn + argument made required

**Where the data came from:** a Notifications GraphQL API. The team retired the
`WEBHOOK` channel in favor of `SLACK`, and made the `limit` argument mandatory
to stop unbounded queries. Both are breaking.

**Changes in this diff:**

1. Enum value `Channel.WEBHOOK` **removed** — BREAKING (existing requests using
   it become invalid).
2. Enum value `Channel.SLACK` **added** — WARNING (new value clients may not
   handle on the read side).
3. Argument `limit` on `Query.notifications` changed `Int -> Int!`
   (became required) — BREAKING.

## Run

```bash
python -m apidiff diff demos/08-graphql-enum-and-args/schema.old.graphql \
                       demos/08-graphql-enum-and-args/schema.new.graphql
```

## What to expect

Exit code **1**. Highlights:

```
  [BREAKING] Channel              Enum value 'Channel.WEBHOOK' was removed
  [BREAKING] Query.notifications  Argument 'limit' on 'Query.notifications' became required
  [WARNING ] Channel              Enum value 'Channel.SLACK' was added
```

## How to act

Removing enum values is breaking — deprecate `WEBHOOK` with `@deprecated` first.
Give `limit` a server-side default instead of making it required, or stage the
required change behind a major version.
