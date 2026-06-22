# Demo 02 — GraphQL field removals across a release

**Where the data came from:** a public GraphQL API for a blogging platform.
Between the `v3` and `v4` branches a developer cleaned up the `Post` and
`Author` types — but two of those removals are breaking for existing clients.

**Changes in this diff:**

1. `Post.slug` **removed** — BREAKING. Any client query selecting `slug`
   (e.g. for SEO-friendly URLs) will start getting a validation error.
2. `Author.email` **removed** — BREAKING.
3. `Post.readingMinutes` **added** — INFO (additive, safe).

## Run

```bash
python -m apidiff diff demos/02-graphql-schema/schema.old.graphql \
                       demos/02-graphql-schema/schema.new.graphql
```

Format auto-detects as `graphql`. To force it:

```bash
python -m apidiff diff demos/02-graphql-schema/schema.old.graphql \
                       demos/02-graphql-schema/schema.new.graphql --fmt graphql
```

## What to expect

Exit code **1** (breaking changes found). Highlights:

```
  [BREAKING] Post.slug      Field 'Post.slug' was removed
  [BREAKING] Author.email   Field 'Author.email' was removed
  [INFO    ] Post.readingMinutes  Field 'Post.readingMinutes' was added
```

## How to act

Do not merge as-is. Either keep `slug`/`email` and mark them `@deprecated`
for a release cycle, or coordinate a major-version bump and notify consumers.
