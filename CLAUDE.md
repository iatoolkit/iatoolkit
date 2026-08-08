# IAToolkit Core

Claude Code entry point for this repo. The working rules and architecture context
are shared across the IAToolkit repos and live in two places:

- `agents.md` — the rules for this repo.
- `/Users/fernando/Documents/software/AGENTS.md` — cross-repo working rules.
- `/Users/fernando/Documents/software/architecture/iatoolkit-architecture.md` —
  architecture context and the full database schema protocol.

**Read those before changing anything.** The rules below are repeated here because
they are the ones that cause damage when missed.

## Non-negotiable

- Database schema: a **new table** needs only a SQLAlchemy model — `create_all()`
  creates it at boot. **Any change to an existing table** (column, index, enum,
  constraint, nullability) needs an idempotent SQL script in
  `iatoolkit-enterprise/migrations/YYYY-MM-DD-slug.sql`, fully qualified as
  `iatoolkit.<table>`, that records itself in `iatoolkit.iat_schema_migrations`
  inside its own transaction. `create_all()` never alters anything, so without the
  script the change reaches no database.
- Never assume a migration was applied. Report which databases still need it, and
  run `flask --app app db-drift` before claiming a schema change is done.
  Full protocol: `architecture/iatoolkit-architecture.md` → Database Schema Changes.

## Environment

- Always use the project virtualenv: `./venv/bin/python`
- `PYTHONPATH=./src`
- Tests: `PYTHONPATH=./src ./venv/bin/python -m pytest`
- Do not create GitHub branches unless Fernando asks.
