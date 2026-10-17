# IAToolkit Community with Docker

A standalone deployment of the open-source framework, Sample Company and the
populated Northwind dataset. Docker files, configuration and initialization live
in this directory. The development `app.py`, root `.env` and local databases are
not used.

## Install a published version

The customer kit uses the same mechanism as `iatoolkit-bridge`: a pinned GHCR
image and four installation files, without source code or local builds.
The kit is prepared here; the first public image has not been published yet.
See [customer instructions](README.client.md) and the maintainer
[release runbook](RELEASING.md).

`compose.client.yaml` uses `ghcr.io/iatoolkit/iatoolkit:X.Y.Z`, pinned to the
core package version. `compose.yaml` remains the local development build.
The installation kit includes `compose.client.yaml`, `.env.example`, `setup.sh`
and the customer README, packaged together under `docker/dist/` by the release
script. Northwind and the sample documents are already inside the image.

## Start from source

Install Docker with Docker Compose, clone this repository, then:

```sh
cd docker
sh setup.sh
# Edit .env and set OPENAI_API_KEY for chat and document indexing.
docker compose up --build -d --wait
```

Open <http://localhost:8080/sample_company/home> and register your own user.
Email verification is disabled for this local demo; no email service is needed.
The UI and SQL dataset start without an API key. AI requests require your own key
and use the provider's API. Northwind is bundled; Render credentials and access
are never needed by users.

`setup.sh` needs a POSIX shell and OpenSSL (available on macOS and most Linux
systems). On Windows, copy `.env.example` to `.env` and set `POSTGRES_PASSWORD`
to a long random **hexadecimal** password, then add `OPENAI_API_KEY`.
Using hexadecimal avoids special characters in the database connection URL.

The first run builds the image locally. `IATOOLKIT_IMAGE` can override the local
image tag in this development Compose only; the build uses this
checkout, Python 3.13 and the committed `uv.lock`, without development extras.

## What starts

| Service | Purpose |
| --- | --- |
| `postgres` | PostgreSQL 18 with pgvector; separate `iatoolkit` and `sample_db` databases. |
| `redis` | Server-side sessions. |
| `init` | One-off creation of the sample database and transactional Northwind restore. |
| `app` | Community web/API, served by Gunicorn after initialization succeeds. |

The Northwind source contained 11 tables and 1,303 rows. The included manifest
records counts and checksums. Initialization refuses a partial/nonempty restore
and never drops existing tables. It does not run the old destructive
`create-sample-db` command.

Only the application port is published, bound to `127.0.0.1` by default. Change
`IATOOLKIT_PORT` if 8080 is busy. The Docker environment contains only the explicit
variables in Compose; the host root `.env` is excluded from the build.

## Documents and RAG

The example PDFs are included, but indexing is explicit because it calls the
embedding API. After configuring the key and recreating the application:

```sh
docker compose up -d --wait
docker compose exec app python -m distribution.bootstrap load-documents
```

Repeated indexing skips already ingested files by their hash and collection.
The demo uses OpenAI `text-embedding-3-small` and the basic parser, storing files
locally in the application volume. S3, Hugging Face endpoints, Docling, OCR,
visual embeddings, email delivery and web search are not required or configured.
Text PDFs are supported; scanned/image-only documents need additional parsing.

Try “Show me the sample employees” or “Summarize sales by country for 2025”.
After indexing, try asking about Julia Bianchi's contract.

Generate an API key for integrations, if needed:

```sh
docker compose exec app flask --app distribution.app:create_app api-key sample_company local-client
```

## Data, updates and backups

Named volumes keep PostgreSQL data (`postgres_data`), Redis data (`redis_data`),
and documents plus generated signing/encryption keys (`app_data`). Secrets are
generated once, stored with restricted permissions, and reused by web and CLI
commands. Back up `app_data` together with PostgreSQL: losing the keys can make
encrypted values unreadable and invalidates signed sessions/links.

```sh
# Stop without deleting data
docker compose down
# Rebuild after updating the checkout; existing data is retained
docker compose up --build -d --wait
# Database backup (repeat with sample_db for the demo database)
docker compose exec -T postgres pg_dump -U iatoolkit -Fc iatoolkit > iatoolkit.dump
```

`docker compose down -v` **deletes all three volumes**, including your users,
documents and keys. Do this only to deliberately reset this installation.
Changing `POSTGRES_PASSWORD` in `.env` does not change an initialized database's
password; rotate it in PostgreSQL first and update the configuration together.
New core tables are created at boot. Rebuilding does not perform migrations of
existing tables; check release instructions before upgrading a deployed version.

For access beyond localhost, configure an HTTPS reverse proxy, set
`SESSION_COOKIE_SECURE=true`, and review signup/access policy for your deployment.
Do not expose the demo's open signup directly as a private business installation.

## Checks and troubleshooting

```sh
docker compose ps -a
docker compose logs init app
curl --fail http://localhost:8080/healthz
# Repository tests for the container distribution (from docker/)
(cd .. && uv run pytest docker/tests)
```

`/healthz` checks the core database, the restored orders table and Redis.
If the init service fails, the web service stays stopped; inspect its logs rather
than deleting the database volume. Unit checks run without Docker or API keys.
`tests/smoke.py` exercises the running stack, signup/login, SQL and persisted
storage without making calls to an LLM. From this directory, pipe it into the
container (test tools are not included in the image):

```sh
docker compose exec -T app python < tests/smoke.py
docker compose exec -T app python < tests/rag_smoke.py
```

The RAG check uses real PDF extraction and pgvector with offline, deterministic
test embeddings; it removes its synthetic document afterwards. This verifies
the integration without charging an API key, not the quality of model answers.
For a persistence check:

```sh
docker compose exec -T app python - --keep-state < tests/smoke.py
docker compose down
docker compose up -d --wait
docker compose exec -T app python < tests/smoke.py
```

The temporary test account is removed on completion. The check also verifies
that the existing login session, signing keys and stored file survive recreation.
