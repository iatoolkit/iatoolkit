# IAToolkit Database Guide

## 1. Introduction

This guide explains the core data model of **IAToolkit** from a developer’s perspective.  
It is intended to help you:

- Understand how data is organized in the IAToolkit database.
- Safely integrate your own data sources (via `company.yaml` and schema files).
- Extend or query the IAToolkit schema for analytics, debugging, or custom features.

IAToolkit is built on **SQLAlchemy** and typically uses **PostgreSQL** (with optional `pgvector` for semantic search).  
However, the concepts described here apply to any SQL backend supported by SQLAlchemy.

---

## 2. High-Level Overview

At a high level, IAToolkit’s internal database can be thought of in terms of four main domains:

1. **Tenants & Users**
   - Companies
   - Users & Profiles
   - Authentication and sessions

2. **Queries & Conversations**
   - LLM queries and responses
   - Tool calls and execution logs

3. **Documents & Vector Store (RAG)**
   - Uploaded documents and metadata
   - Vector chunks and embeddings

4. **Tasks & Background Jobs**
   - Asynchronous jobs (e.g., document ingestion, long-running analyses)

In addition to the **core IAToolkit schema**, each Company can connect to its **own business database** via the `data_sources.sql` section in `company.yaml`. Those external databases are **not owned** by IAToolkit; instead, they are *described* using YAML schemas in `companies/<company>/schema/`.

---

## 3. Tenant & User Model

### 3.1 Company

**Table (example):** `iat_companies`  
**SQLAlchemy model:** `iatoolkit.repositories.models.Company`

Represents a tenant (a “Company” or project) within IAToolkit.

Typical fields include:

- `id` (PK, integer)
- `short_name` (string): Unique identifier, e.g. `"sample_company"`. Used in URLs and routing.
- `name` (string): Human-readable company name.
- `openai_api_key` (encrypted string, optional): Legacy storage for LLM keys.
- `gemini_api_key` (encrypted string, optional): Legacy storage for Gemini keys.
- `parameters` (JSON): Arbitrary per-company configuration (mirrors part of `company.yaml`).

Although some keys can be stored in the DB, the **recommended** way is to configure LLMs and embeddings via:

- `company.yaml` (under `config/`)
- Environment variables (e.g., `OPENAI_API_KEY`, `GEMINI_API_KEY`)
- `ConfigurationService`

### 3.2 Users and Profiles

**Typical tables (names may vary by version):**

- `iat_users`
- `iat_profiles`

Conceptually:

- The **User** table stores authentication-related data:
  - `id`, `email`, `password_hash`, `is_active`, `created_at`, etc.
- The **Profile** table stores per-user profile information:
  - `user_id`, `company_id`, `role`, `preferences`, etc.

These tables are used by services such as:

- `AuthService` – login, logout, password validation.
- `ProfileService` – loading the current user’s company, roles, and preferences.

---

## 4. Queries, Conversations & Logs

IAToolkit keeps a record of interactions with the LLM and tools to enable auditing, analytics, and cost tracking.

### 4.1 LLM Query Log

**Typical table:** `iat_llm_queries`  
**Model:** `LLMQuery` (in `repositories/llm_query_repo.py`)

Typical fields:

- `id` (PK)
- `company_id` – which tenant this query belongs to
- `user_id` – who initiated the query (if authenticated)
- `input_text` – the user’s question or prompt
- `model` – the LLM model used (e.g., `gpt-4`, `gemini-1.5-pro`)
- `tokens_prompt`, `tokens_completion`, `tokens_total` – cost tracking
- `response_excerpt` – truncated response for quick inspection
- `created_at` – timestamp for the query

The **QueryService** uses this table to:

- Log every interaction.
- Support dashboards and analytics.
- Potentially replay or debug past conversations.

---

## 5. Documents & Vector Store (RAG)

Retrieval-Augmented Generation (RAG) in IAToolkit is backed by two main internal tables:

1. **Document metadata & content** – e.g., `iat_documents`
2. **Vector store entries (chunks + embeddings)** – e.g., `iat_vsdocs`

Together, they allow the system to:

- Store your private documents.
- Chunk them.
- Generate embeddings.
- Search them semantically using `pgvector`.

### 5.1 Document Table: `iat_documents`

Represents a logical document as seen by IAToolkit.

Typical fields:

- `id` (PK)
- `company_id` – which company this document belongs to
- `filename` – original file name
- `content` – extracted text, usually as `TEXT`
- `content_b64` – optional base64-encoded content (for binary or large payloads)
- `meta` – JSON with arbitrary metadata (e.g., `{"type": "supplier_manual", "department": "Sales"}`)
- `created_at`, `updated_at`

This table is mapped to a SQLAlchemy model such as `Document` (see `iatoolkit.repositories.models`).

### 5.2 Vector Store Table: `iat_vsdocs`

Represents **chunks** of documents, each with its own embedding vector.

Typical fields:

- `id` (PK)
- `company_id` – tenant scoping
- `document_id` – FK to `iat_documents.id`
- `text` – the chunk of text used for embedding
- `embedding` – vector type (e.g., `vector(1536)` using `pgvector`)

The `VSRepo` (`iatoolkit.repositories.vs_repo.VSRepo`) manages interactions with this table:

- **Insertion** (`add_document`):
  - Breaks a document into chunks (`VSDoc` instances).
  - For each chunk:
    - Computes an embedding via `EmbeddingService`.
    - Stores the result in `iat_vsdocs.embedding`.
- **Query** (`query`):
  - Computes an embedding for the query text.
  - Executes a similarity search using `ORDER BY embedding <-> CAST(:query_embedding AS vector)`.
  - Joins with `iat_documents` to return document-level results.

---

