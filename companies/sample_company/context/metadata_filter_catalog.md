# Metadata Filter Catalog (Tool Calls)

Use this catalog when calling:
- `iat_document_search`
- `iat_image_search`
- `iat_visual_search`

## Required Format in Tool Calls

`metadata_filter` MUST be sent as an array of `{key, value}` objects:

```json
{
  "metadata_filter": [
    {"key": "doc.type", "value": "invoice"},
    {"key": "chunk.source_type", "value": "table"}
  ]
}
```

Do NOT send `metadata_filter` as a plain object in tool calls.

## Prefixes

- `doc.*`: document metadata.
- `chunk.*`: text chunk metadata (valid for `iat_document_search`).
- `image.*`: image metadata (valid for `iat_image_search` and `iat_visual_search`).

## Canonical Keys

### `doc.*`
- `doc.type` (string)
- `doc.category` (string)
- `doc.collection` (string)
- `doc.user_identifier` (string)
- `doc.parser_provider` (string)
- `doc.parser_version` (string)

### `chunk.*` (text search)
- `chunk.source_type` (string): `text` or `table`
- `chunk.source_label` (string)
- `chunk.page` (number)
- `chunk.page_start` (number)
- `chunk.page_end` (number)
- `chunk.section_title` (string)
- `chunk.table_index` (number)
- `chunk.caption_text` (string or null)  # table caption
- `chunk.caption_source` (string): `extracted`, `provided`, `none`

### `image.*` (visual search)
- `image.source_type` (string): `image`
- `image.page` (number)
- `image.image_index` (number)
- `image.width` (number)
- `image.height` (number)
- `image.format` (string)
- `image.mime_type` (string): `image/png` or `image/jpeg`
- `image.color_mode` (string): `rgb`
- `image.caption_text` (string or null)  # image caption
- `image.caption_source` (string): `extracted`, `provided`, `none`

## Tool-specific Rules

- `iat_document_search`: use `doc.*` and `chunk.*`.
- `iat_image_search`: use `doc.*` and `image.*`.
- `iat_visual_search`: use `doc.*` and `image.*`.

Never use `chunk.*` with visual tools.
Never use unknown keys.

## Examples

Only invoices:

```json
{
  "query": "find payment terms",
  "collection": "invoices",
  "metadata_filter": [
    {"key": "doc.type", "value": "invoice"}
  ]
}
```

Only table chunks in text search:

```json
{
  "query": "what is total amount?",
  "collection": "invoices",
  "metadata_filter": [
    {"key": "chunk.source_type", "value": "table"}
  ]
}
```

Only images on page 1:

```json
{
  "query": "company logo",
  "collection": "brand_assets",
  "metadata_filter": [
    {"key": "image.page", "value": 1}
  ]
}
```
