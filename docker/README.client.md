# Install IAToolkit Community

This kit runs IAToolkit Community, PostgreSQL with pgvector, Redis, and a
populated Northwind database. It uses a versioned image from GitHub Container
Registry: `ghcr.io/iatoolkit/iatoolkit`. No Python installation, source checkout
or image build is needed on your computer.

## Start

Install Docker with Docker Compose. Extract the kit into its own directory:

```sh
sh setup.sh
```

This creates `.env` with a random database password. Add your `OPENAI_API_KEY`
to `.env`, then:

```sh
docker compose -f compose.client.yaml pull
docker compose -f compose.client.yaml up -d --wait
```

Open <http://localhost:8080/sample_company/home> and register your user.
The UI and sample database start without an API key; chat and indexing require
your key and use the provider's API. Email verification is disabled for this
local demo. Only port 8080 is exposed, bound to localhost by default.

On Windows without a POSIX shell/OpenSSL, copy `.env.example` to `.env` and set
`POSTGRES_PASSWORD` to a long random hexadecimal password. Set `OPENAI_API_KEY`
and use the same Compose commands above. Hexadecimal avoids URI escaping.

## Included data and documents

Northwind contains 11 tables and 1,303 rows. The snapshot restores only into
an empty local database. It does not connect to Render or require credentials
from the maintainer. Toolkit users and Northwind use separate databases.

The image includes 18 sample PDF contracts/manuals. To index their text:

```sh
docker compose -f compose.client.yaml exec app python -m distribution.bootstrap load-documents
```

Indexing calls the embedding API. Repeated runs skip documents already loaded.
The basic parser handles these text PDFs; scanned documents and visual search
need additional configuration. Documents are stored in a persistent local volume.

Try “Show me the sample employees” or “Summarize sales by country for 2025”.
After indexing, ask about Julia Bianchi's contract.

## Operations

```sh
docker compose -f compose.client.yaml ps -a
docker compose -f compose.client.yaml logs init app
curl --fail http://localhost:8080/healthz
# Stop, retaining data
docker compose -f compose.client.yaml down
# Start again
docker compose -f compose.client.yaml up -d --wait
```

The Compose file pins an exact image version. Updating is deliberate: obtain
the kit for the new version, preserve your `.env`, review migration instructions,
then run `pull` and `up -d --wait` again. Keep the same Compose project name and
volumes. A restart alone does not switch to a newer version.

Back up the PostgreSQL databases and the `app_data` volume, which contains the
documents and signing/encryption keys. Losing those keys can make encrypted
values unreadable. A database backup can be made with:

```sh
docker compose -f compose.client.yaml exec -T postgres pg_dump -U iatoolkit -Fc iatoolkit > iatoolkit.dump
docker compose -f compose.client.yaml exec -T postgres pg_dump -U iatoolkit -Fc sample_db > sample_db.dump
```

`docker compose -f compose.client.yaml down -v` deletes users, documents, keys
and databases. Use it only for a deliberate reset. Changing the password in
`.env` does not rotate an initialized PostgreSQL password.

For use beyond localhost, place the service behind an HTTPS reverse proxy,
set `SESSION_COOKIE_SECURE=true` and configure an appropriate access/signup
policy. The local demo allows open signup.

## Image access

The published package must be public so installers can pull it without a GitHub
token. If pull returns an authorization error, check the image tag and package
visibility. Publishing and package visibility are maintainer operations;
installation never requires a token with permission to publish images.
