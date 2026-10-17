"""Maintainer utility: read-only export of the eleven allowed Northwind tables.

Run with the repository's uv environment. The source URI is read from an
environment variable, or from --env-file; it is never written to the snapshot.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dotenv import dotenv_values
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

TABLES = (
    'categories', 'customers', 'employee_territories', 'employees',
    'order_details', 'orders', 'products', 'regions', 'shippers',
    'suppliers', 'territories',
)


def export(uri, output):
    dsn = parse_dsn(uri)
    env = os.environ.copy()
    env.update({
        'PGHOST': dsn.get('host', 'localhost'), 'PGPORT': dsn.get('port', '5432'),
        'PGDATABASE': dsn['dbname'], 'PGUSER': dsn['user'],
        'PGPASSWORD': dsn.get('password', ''), 'PGSSLMODE': 'require',
        'PGCONNECT_TIMEOUT': '15',
        'PGOPTIONS': '-c default_transaction_read_only=on -c statement_timeout=60000',
    })
    command = ['docker', 'run', '--rm']
    for key in ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGSSLMODE', 'PGCONNECT_TIMEOUT', 'PGOPTIONS'):
        command.extend(['--env', key])
    command.extend([
        'postgres:18.6-trixie', 'pg_dump', '--format=plain', '--inserts',
        '--column-inserts', '--no-owner', '--no-privileges', '--no-comments',
        '--no-tablespaces', '--quote-all-identifiers', '--strict-names',
    ])
    command.extend('--table=public.' + table for table in TABLES)
    result = subprocess.run(command, env=env, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('pg_dump failed; verify network access and source credentials.')
    # Restore through psycopg2 rather than psql. Only these two known
    # client-side directives may be removed; refuse any unexpected command.
    lines = result.stdout.decode().splitlines(keepends=True)
    lines = [line for line in lines if not line.startswith(('\\restrict ', '\\unrestrict ', '-- Dumped '))]
    if any(line.startswith('\\') for line in lines):
        raise RuntimeError('Unexpected psql command in export.')
    payload = ''.join(lines).encode()
    with psycopg2.connect(uri, sslmode='require', connect_timeout=15, options=env['PGOPTIONS']) as connection:
        with connection.cursor() as cursor:
            counts = {}
            for table in TABLES:
                cursor.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
                counts[table] = cursor.fetchone()[0]
    archive = gzip.compress(payload, mtime=0)
    manifest = {
        'dataset': 'Sample Company Northwind',
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'source_schema': 'public', 'source_postgresql_major': 18,
        'tables': counts,
        'sql_sha256': hashlib.sha256(payload).hexdigest(),
        'archive_sha256': hashlib.sha256(archive).hexdigest(),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / 'northwind.sql.gz').write_bytes(archive)
    (output / 'northwind.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Exported {len(counts)} tables and {sum(counts.values())} rows; no source credentials included.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--uri-env', default='SAMPLE_DATABASE_URI')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    args = parser.parse_args()
    values = dotenv_values(args.env_file) if args.env_file else os.environ
    uri = values.get(args.uri_env)
    if not uri:
        raise SystemExit('Source connection variable is missing: ' + args.uri_env)
    try:
        export(uri, args.output)
    except Exception as exc:
        if isinstance(exc, psycopg2.Error):
            raise SystemExit('Source database connection failed; check access and credentials.')
        raise
