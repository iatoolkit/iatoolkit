# company.yaml Configuration Reference

This document summarizes all configuration options currently supported by `company.yaml` across:

- `iatoolkit` (core/community)
- `iatoolkit-enterprise` (enterprise runtime extensions)

## 1. File location and loading

`company.yaml` is loaded from:

- `companies/<company_short_name>/config/company.yaml`

Core loader/validator:

- `src/iatoolkit/services/configuration_service.py`

Enterprise uses the same core configuration service, plus additional sections consumed by enterprise services.

## 2. Secret references

Most credential fields store a **secret reference name** (not raw credentials). Resolution is done through the configured `SecretProvider` (env vars in community, DB-backed secrets in enterprise).

You will see two patterns:

- Preferred keys: `*_secret_ref`
- Legacy aliases still supported in many places: `*_env`, `api_key_name`, `api-key`, etc.

## 3. Top-level sections

| Section | Core (`iatoolkit`) | Enterprise (`iatoolkit-enterprise`) | Notes |
|---|---|---|---|
| `id` | Yes | Yes | Required, must match company short name |
| `name` | Yes | Yes | Required |
| `locale` | Yes | Yes | Optional, default language context |
| `llm` | Yes | Yes | Required section |
| `embedding_provider` | Yes | Yes | Optional but commonly used |
| `embedding_providers` | No (ignored by core factory) | Yes | Enterprise extension for multiple text embedding profiles |
| `visual_embedding_provider` | Yes | Yes | Optional |
| `inference_tools` | Yes | Yes | Optional, used mainly with HuggingFace embeddings/inference |
| `data_sources` | Yes | Yes | SQL database registrations |
| `tools` | Yes | YAML sync in enterprise is skipped | Enterprise typically manages tools via DB/UI |
| `prompts` | Yes | YAML sync in enterprise is skipped | Enterprise typically manages prompts via DB/UI |
| `parameters` | Yes | Yes | Generic settings + enterprise router options |
| `branding` | Yes | Yes | UI theme variables |
| `help_files` | Yes | Yes | Referenced config content files |
| `knowledge_base` | Yes | Yes | Parsing and legacy ingestion-source config |
| `web_search` | Yes | Yes | Built-in web search system tool config |
| `mail_provider` | Yes | Yes | Email provider config |
| `connectors` | Yes | Yes | Storage/ingestion connector aliases |
| `storage_provider` | Validation exists | Validation exists | Legacy/compat section; runtime storage uses `connectors` |
| `sso` | No | Yes | Enterprise SSO extension |
| `tasks` | No | Yes | Enterprise async task policy per prompt |
| `payments` | No | Yes | Enterprise billing/payment provider config |

## 4. Detailed reference

## 4.1 `id`, `name`, `locale`

```yaml
id: sample_company
name: Sample Company
locale: en_US
```

- `id` (string, required): must match the company short name.
- `name` (string, required): display name.
- `locale` (string, optional): default locale (example: `en_US`, `es_ES`).

## 4.2 `llm`

```yaml
llm:
  model: gpt-5.2
  available_models:
    - id: gpt-5.2
      label: GPT-5.2
      description: Fast, recommended for most queries.
    - id: llama-3.3-70b-instruct
      label: Llama 3.3 70B Instruct
      description: Open source model served through a dedicated OpenAI-compatible endpoint.
      provider: openai_compatible
  provider_api_keys:
    openai: OPENAI_API_KEY
    gemini: GEMINI_API_KEY
    deepseek: DEEP_SEEK_API_KEY
    openai_compatible: OSS_LLM_API_KEY

  providers:
    openai_compatible:
      base_url_env: OSS_LLM_BASE_URL
      disable_tools: false

  # Attachment defaults (applies to prompt and non-prompt llm_query flows)
  default_attachment_mode: extracted_only
  default_attachment_fallback: extract

  # Optional provider capability overrides for attachment planner
  capabilities_overrides:
    openai:
      supports_native_files: true
      supports_native_images: true
      supported_mime_types: [application/pdf, text/plain]
      preferred_native_mime_types: [application/pdf]
      max_file_size_mb: 20
      max_files_per_request: 10

  # Legacy global key reference (fallback if provider_api_keys missing)
  api-key: OPENAI_API_KEY
```

- `model` (string, required).
- `provider_api_keys` (object, required): map `provider -> secret_ref`.
- `available_models` (list, optional): for UI selector (`id`, `label`, `description`). Each entry can also declare `provider` to route models whose provider cannot be inferred reliably from the model id.
- `providers` (object, optional): provider-specific runtime settings. `openai_compatible` currently supports `base_url`, `base_url_env`, or `base_url_secret_ref`. It also supports `disable_tools: true` as a compatibility workaround for endpoints that expose chat completions but do not support automatic tool calling.
- `default_attachment_mode` (optional, default `extracted_only`):
  - `extracted_only`
  - `native_only`
  - `native_plus_extracted`
  - `auto`
- `default_attachment_fallback` (optional, default `extract`):
  - `extract`
  - `fail`
- `capabilities_overrides` (optional): per provider capability override map.
- `api-key` (legacy optional fallback): global API key reference.

## 4.3 `embedding_provider` (default text embeddings)

```yaml
embedding_provider:
  provider: huggingface
  model: sentence-transformers/all-MiniLM-L6-v2
  tool_name: text_embeddings
  api_key_secret_ref: OPENAI_API_KEY   # provider dependent
  api_key_name: OPENAI_API_KEY         # legacy alias
  dimensions: 1536
  class_path: my.module.MyEmbeddingClient
  init_params: {}
```

- `provider` (required when section exists): currently implemented providers:
  - `openai`
  - `huggingface`
  - `custom_class`
- `model` (required by current validator).
- `tool_name` (optional): used for HuggingFace through `inference_tools`.
- `api_key_secret_ref` / `api_key_name` (provider dependent).
- `dimensions` (optional int).
- `class_path`, `init_params` (for `custom_class`).

## 4.4 `embedding_providers` (enterprise extension)

```yaml
embedding_providers:
  routing:
    provider: huggingface
    model: BAAI/bge-m3
    tool_name: routing_embeddings
  text_search:
    provider: huggingface
    model: sentence-transformers/all-MiniLM-L6-v2
    tool_name: text_embeddings
```

- Enterprise-only extension for multiple **text** embedding profiles by `model_type`.
- Each profile uses the same shape as `embedding_provider`.

## 4.5 `visual_embedding_provider`

```yaml
visual_embedding_provider:
  provider: huggingface
  model: openai/clip-vit-base-patch32
  tool_name: clip_embeddings
  dimensions: 512
  class_path: my.module.MyVisualEmbeddingClient
  init_params: {}
```

- `provider` required when section exists.
- `model` required unless provider is `custom_class`.
- Optional: `tool_name`, `dimensions`, `class_path`, `init_params`, API key refs.

## 4.6 `inference_tools`

```yaml
inference_tools:
  _defaults:
    endpoint_url_env: HF_INFERENCE_ENDPOINT_URL
    api_key_name: HF_TOKEN

  text_embeddings:
    model_id: sentence-transformers/all-MiniLM-L6-v2

  clip_embeddings:
    model_id: openai/clip-vit-base-patch32
    model_parameters:
      from_tf: true
```

For each tool config (after `_defaults` merge), supported keys include:

- `endpoint_url` (direct URL)
- `endpoint_url_secret_ref` (preferred secret reference)
- `endpoint_url_env` (legacy/alias pattern)
- `api_key_secret_ref` or `api_key_name`
- `model_id`
- `model_parameters` (object)

## 4.7 `data_sources.sql[]`

```yaml
data_sources:
  sql:
    - database: sample_db
      connection_type: direct
      connection_string_secret_ref: DATABASE_URI
      connection_string_env: DATABASE_URI   # legacy alias
      schema: public
      bridge_id: finance_bridge
      timeout: 60
      description: Main operational database
```

- `database` (required).
- `connection_type` (optional, runtime default `direct`):
  - `direct`
  - `bridge` (enterprise bridge adapter)
- `connection_string_secret_ref` (required for `direct`, preferred).
- `connection_string_env` (legacy alias).
- `bridge_id` (required for `bridge`).
- `schema` (optional, default `public`).
- `timeout` (optional passthrough for provider implementations).
- Additional metadata keys (for example `description`) may be present and used by context generation.

## 4.8 `connectors`

```yaml
connectors:
  iatoolkit_storage:
    type: s3
    bucket: iatoolkit-assets
    prefix: companies/sample_company
    folder: documents
    auth:
      aws_access_key_id: ...
      aws_secret_access_key: ...
      region_name: us-east-1
    auth_env:
      aws_access_key_id_secret_ref: AWS_ACCESS_KEY_ID
      aws_secret_access_key_secret_ref: AWS_SECRET_ACCESS_KEY
      aws_region_secret_ref: AWS_REGION
```

- Map of connector aliases.
- `iatoolkit_storage` alias is required by `StorageService`.
- Supported connector `type`:
  - `s3`
  - `local`
  - `gdrive`
  - `gcs` / `google_cloud_storage`

### Connector-specific keys

- `s3`:
  - required: `bucket`
  - optional: `prefix`, `folder`
  - auth options:
    - `auth` object with direct credentials (`aws_access_key_id`, `aws_secret_access_key`, `region_name`)
    - or `auth_env` with secret/env refs:
      - `aws_access_key_id_secret_ref` or `aws_access_key_id_env`
      - `aws_secret_access_key_secret_ref` or `aws_secret_access_key_env`
      - `aws_region_secret_ref` or `aws_region_env`
- `local`:
  - required: `path`
- `gdrive`:
  - required: `folder_id`
  - optional: `service_account` (default `service_account.json`)
  - optional: `service_account_secret_ref` (secret/env key containing the full service account JSON)
- `gcs` / `google_cloud_storage`:
  - required: `bucket`
  - optional: `service_account_path` (default `service_account.json`)
  - optional: `service_account_secret_ref` (secret/env key containing the full service account JSON)

## 4.9 `tools[]`

```yaml
tools:
  - function_name: document_search
    description: Search across internal documents
    params:
      type: object
      properties:
        query:
          type: string
      required: [query]
```

- In YAML sync, required keys are:
  - `function_name`
  - `description`
  - `params` (object)
- Community mode syncs these into DB.
- Enterprise runtime usually manages tools in DB/UI; YAML sync is skipped there.

## 4.10 `prompts`

Preferred structure:

```yaml
prompts:
  prompt_categories:
    - Sales
    - Finance
  prompt_list:
    - name: sales_report
      description: Sales report
      category: Sales
      order: 1
      active: true
      prompt_type: company
      custom_fields:
        - data_key: start_date
          label: Start date
          type: date

      # Structured output
      output_schema:
        type: object
        properties: {}
      output_schema_mode: best_effort
      output_response_mode: chat_compatible

      # Attachment policy
      attachment_mode: extracted_only
      attachment_fallback: extract

      # Optional request overrides for providers that support them
      llm_model: gpt-5
      llm_request_options:
        reasoning_effort: high
        store: false
        text_verbosity: medium
```

Legacy shape is also accepted (`prompt_categories` top-level + `prompts` list).

Per prompt supported keys:

- `name` (required)
- `description` (required)
- `category` (required for `prompt_type: company`)
- `order` (optional)
- `active` (optional, default `true`)
- `prompt_type` (optional, default `company`): `company` or `agent`
- `custom_fields` (optional list)
- `output_schema` (optional object, JSON Schema)
- `output_schema_mode` (optional, default `best_effort`): `best_effort` or `strict`
- `output_response_mode` (optional, default `chat_compatible`):
  - `chat_compatible`
  - `structured_only`
- `attachment_mode` (optional): `extracted_only`, `native_only`, `native_plus_extracted`, `auto`
- `attachment_fallback` (optional): `extract`, `fail`
- `llm_model` (optional): per-prompt model override
- `llm_request_options` (optional object):
  - `reasoning_effort`: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`
  - `store`: boolean
  - `text_verbosity`: `low`, `medium`, `high`

Important:

- Corresponding prompt file must exist: `prompts/<name>.prompt`.
- Community mode syncs prompt metadata from YAML.
- Enterprise typically manages prompt metadata in DB/UI (YAML sync skipped).

## 4.11 `parameters`

```yaml
parameters:
  verify_account: true
  cors_origin:
    - https://portal.example.com
  external_urls:
    logout_url: https://portal.example.com/logout
  user_feedback:
    channel: email
    destination: support@example.com
  http_tools:
    allowed_hosts:
      - api.example.com
      - "*.partner.com"

  # Enterprise tool-router tuning
  tool_router:
    enabled: false
    shadow_mode: false
    top_k: 8
    top_n: 8
    min_confidence: 0.15
    fallback: all_tools
```

Core/common keys:

- `verify_account` (bool, default behavior true when absent)
- `cors_origin` (list of origins for CORS)
- `external_urls.logout_url` (optional redirect URL)
- `user_feedback`:
  - `channel` (used values: `email`, `google_chat`)
  - `destination` (required when `channel: email`)
- `http_tools.allowed_hosts` (optional list of host patterns used as HTTP-tool allowlist)

Enterprise keys:

- `tool_router`:
  - `enabled` (bool, default `false`)
  - `shadow_mode` (bool, default `false`)
  - `top_k` (int >= 1, default `8`)
  - `top_n` (int >= 1, default `8`)
  - `min_confidence` (float >= 0, default `0.15`)
  - `fallback` (currently only `all_tools`)

## 4.12 `branding`

```yaml
branding:
  header_background_color: "#0D6EFD"
  header_text_color: "#FFFFFF"
  brand_primary_color: "#0D6EFD"
  brand_secondary_color: "#6C757D"
  brand_text_on_primary: "#FFFFFF"
  brand_text_on_secondary: "#FFFFFF"
```

Commonly used keys:

- `header_background_color`, `header_text_color`
- `brand_primary_color`, `brand_secondary_color`
- `brand_text_on_primary`, `brand_text_on_secondary`

Additional supported styling keys are consumed by `BrandingService` defaults, including font weights/sizes, info/danger palette, prompt-assistant colors, and button colors.

## 4.13 `help_files`

```yaml
help_files:
  onboarding_cards: onboarding_cards.yaml
  help_content: help_content.yaml
```

- Map of logical content key -> filename in `config/` assets.
- Each referenced file must exist.

## 4.14 `knowledge_base`

```yaml
knowledge_base:
  parsing_provider: auto
  collections:
    - name: supplier_manual
      parser_provider: docling
  docling:
    do_ocr: false
  connectors:
    production:
      type: s3
      bucket: my-bucket
      prefix: company-prefix
      aws_access_key_id_secret_ref: AWS_ACCESS_KEY_ID
      aws_secret_access_key_secret_ref: AWS_SECRET_ACCESS_KEY
      aws_region_secret_ref: AWS_REGION
  document_sources:
    manuals:
      collection: supplier_manual
      path: companies/sample_company/sample_data/manuals
      folder: manuals
      metadata: {}
```

Supported keys:

- `parsing_provider` (optional): `auto`, `docling`, `basic`.
- `collections` (optional list):
  - string form (legacy), or
  - object form `{ name, parser_provider }`
- `docling.do_ocr` (optional bool)
- `connectors` and `document_sources` are still supported for legacy source sync workflows.

Validation currently enforces for `knowledge_base.connectors.production.type: s3`:

- required: `bucket`, `prefix`
- required credentials (preferred + legacy aliases):
  - `aws_access_key_id_secret_ref` or `aws_access_key_id_env`
  - `aws_secret_access_key_secret_ref` or `aws_secret_access_key_env`
  - `aws_region_secret_ref` or `aws_region_env`

## 4.15 `web_search`

```yaml
web_search:
  enabled: true
  provider: brave
  max_results: 5
  timeout_ms: 10000
  providers:
    brave:
      secret_ref: BRAVE_SEARCH_API_KEY
      api_base_url: https://api.search.brave.com/res/v1/web/search
```

- `enabled` (bool)
- `provider` (currently `brave`)
- `max_results` (int 1..20)
- `timeout_ms` (int 1..120000)
- `providers.brave.secret_ref` (required)
- `providers.brave.api_base_url` (optional, must be absolute HTTPS URL)

## 4.16 `mail_provider`

```yaml
mail_provider:
  provider: iatoolkit_mail
  sender_email: no-reply@example.com
  sender_name: Example AI

  iatoolkit_mail:
    api_key_secret_ref: BREVO_API_KEY

  smtp:
    host_secret_ref: SMTP_HOST
    port_secret_ref: SMTP_PORT
    username_secret_ref: SMTP_USERNAME
    password_secret_ref: SMTP_PASSWORD
    use_tls_secret_ref: SMTP_USE_TLS
    use_ssl_secret_ref: SMTP_USE_SSL
```

- `provider` optional, defaults to `iatoolkit_mail`
- supported `provider` values: `iatoolkit_mail` or `smtp`
- `sender_email` optional, defaults to `<company_short_name>@iatoolkit.com`
- `sender_name` optional, defaults to company `name`
- Provider-specific blocks as shown above.

## 4.17 `storage_provider` (legacy/compat)

```yaml
storage_provider:
  provider: s3
  bucket: my-bucket
  s3: {}
```

or

```yaml
storage_provider:
  provider: google_cloud_storage
  bucket: my-bucket
  google_cloud_storage:
    service_account_path: service_account.json
```

- Validated by `ConfigurationService`, but current runtime storage path uses top-level `connectors` (especially `connectors.iatoolkit_storage`).

## 4.18 `sso` (enterprise)

```yaml
sso:
  enabled: true
  profile_method: get_user_profile
```

- `enabled` must be true to allow corporate login flow.
- `profile_method` is the method name called on the company runtime class to resolve user profile data.

## 4.19 `tasks` (enterprise)

```yaml
tasks:
  my_prompt_name:
    required_inputs: [customer_id, start_date]
    llm_model: gpt-5.2
    execution:
      timeout_seconds: 300
```

Per prompt-task policy options:

- `required_inputs` (list of required `client_data` keys)
- `llm_model` (model override for that async prompt execution)
- `execution.timeout_seconds` (RQ job timeout override)

All prompt/agent executions from enterprise playground task flow are sent with `ignore_history: true`.

## 4.20 `payments` (enterprise)

```yaml
payments:
  provider: stripe
  stripe:
    api_key_env: STRIPE_API_KEY
    success_url: /billing/success
    cancel_url: /billing/cancel
    webhook_secret_env: STRIPE_WEBHOOK_SECRET
    webhook_secret: whsec_...   # optional direct fallback
```

- `provider` currently supported: `stripe`.
- `stripe.api_key_env` (optional, defaults to `STRIPE_API_KEY`).
- `stripe.success_url`, `stripe.cancel_url` optional (relative or absolute).
- `stripe.webhook_secret_env` optional env-name override for webhook signature verification.
- `stripe.webhook_secret` optional direct fallback value.

## 5. Compatibility notes

- `tools` and `prompts` YAML sync is **community-focused**; enterprise usually manages both through DB/UI.
- Legacy aliases are still accepted in many sections (`*_env`, `api_key_name`, `api-key`, etc.).
- Structured output and attachment policy at prompt level (`output_schema*`, `attachment_*`) are supported in prompt metadata and can be persisted in DB (enterprise GUI), while `company.yaml` still carries company-level defaults.

## 6. Minimal examples

### 6.1 Minimal core-safe config

```yaml
id: sample_company
name: Sample Company

llm:
  model: gpt-5.2
  provider_api_keys:
    openai: OPENAI_API_KEY

connectors:
  iatoolkit_storage:
    type: s3
    bucket: iatoolkit-assets
    auth_env:
      aws_access_key_id_env: AWS_ACCESS_KEY_ID
      aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
      aws_region_env: AWS_REGION

data_sources:
  sql: []

tools: []

prompts:
  prompt_categories: []
  prompt_list: []

help_files:
  onboarding_cards: onboarding_cards.yaml
  help_content: help_content.yaml
```

### 6.2 Minimal enterprise additions

```yaml
# Keep all core sections above, then add:

sso:
  enabled: true
  profile_method: get_user_profile

tasks:
  analyst_prompt:
    required_inputs: [from_date, to_date]
    llm_model: gpt-5.2
    execution:
      timeout_seconds: 600

payments:
  provider: stripe
  stripe:
    api_key_env: STRIPE_API_KEY
```
