# Demo 05 — Response type change & dropped field

**Where the data came from:** a Billing API. A developer "fixed" the invoice
schema by changing `amountCents` from an integer to a string (to avoid 32-bit
overflow) and dropped the rarely-used `notes` field. Both silently break parsers.

**Changes in this diff:**

1. Response `amountCents` type **changed `integer -> string`** — BREAKING.
   Clients doing arithmetic on the number will throw or compute garbage.
2. Response `notes` property **removed** — BREAKING for readers.

## Run

```bash
python -m apidiff diff demos/05-response-shape-change/openapi.old.json \
                       demos/05-response-shape-change/openapi.new.json
```

## What to expect

Exit code **1**. Highlights:

```
  [BREAKING] GET /invoices/{invoiceId}  response property 'amountCents' type changed: integer -> string
  [BREAKING] GET /invoices/{invoiceId}  response property 'notes' was removed
```

## How to act

Type changes in a response are almost always breaking. Add a *new* field
(`amountCentsStr`) alongside the old one and migrate clients, rather than
mutating an existing field's type in place.
