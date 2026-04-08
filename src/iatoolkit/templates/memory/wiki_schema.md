# Memory Wiki Schema

This wiki is maintained by the LLM on behalf of the user. The user curates sources and asks questions; the LLM updates the wiki.

## Core Model

- `raw sources` are immutable inputs such as notes, links, files, photos, and saved chat messages
- `memory pages` are compiled markdown pages maintained by the LLM
- `index.md` is the catalog of all memory pages
- `log.md` is the chronological record of ingest and query activity

## Page Rules

- prefer updating an existing relevant page over creating a duplicate
- create a new page only when the capture introduces a clearly distinct topic
- page titles should be short, human-readable, and stable over time
- page summaries should be concise and practical
- key points should capture durable facts or ideas, not raw copies of the source
- decisions, open questions, and next steps should be used only when supported by the sources
- related pages should be added when there is a meaningful conceptual connection
- every page must keep traceability to the raw source items that support it

## Ingest Workflow

When a new capture is ingested:

1. read the raw source items
2. check `index.md` to find likely existing pages
3. read the most relevant pages
4. decide whether to update, create, or skip
5. update the target page in markdown
6. refresh `index.md`
7. append an event to `log.md`

## Query Workflow

When answering from memory:

1. read `index.md` first
2. identify the most relevant pages
3. read those pages
4. synthesize the answer from compiled knowledge first
5. use raw source items only when needed for verification or direct retrieval

## Logging Rules

- `log.md` is append-only
- each entry should use a clear operation type such as `ingest` or `query`
- include enough detail to understand what changed or what was asked

## Maintenance Rules

- avoid duplicate pages that represent the same concept
- prefer canonical links and filenames in sources
- do not repeat the same information across summary, key points, and sources unless necessary
- keep the wiki useful for future sessions, not just the current chat
