# Bundled Northwind snapshot

This snapshot is a read-only export of the maintainer's populated Sample Company
Northwind database on Render, taken on 2026-10-16. It includes only these eleven
tables from `public`: categories, customers, employee_territories, employees,
order_details, orders, products, regions, shippers, suppliers and territories.

The archive contains schema, sequences, constraints and data; no source host,
connection strings, ownership, grants, toolkit users, sessions or credentials.
`northwind.manifest.json` records per-table row counts and checksums of both the
compressed archive and its SQL. Restore checks these before committing.

The source database runs PostgreSQL 18; the distribution uses PostgreSQL 18 with
pgvector. A database is restored only when empty. Subsequent starts preserve it.
No connection to Render is made by the installed application.

Maintainers can refresh the snapshot from the repository root:

```sh
uv run python docker/scripts/export_northwind.py --env-file /path/to/private.env
```

The private file must define `SAMPLE_DATABASE_URI`. The utility uses a PostgreSQL
18 Docker client, read-only source connections and an explicit table allowlist.
Review the exported demo data before committing a refreshed snapshot.
