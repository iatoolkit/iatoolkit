"""Initialize the bundled database, or explicitly index the example documents."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

DATA = Path(__file__).parent / 'data'
NORTHWIND_TABLES = (
    'categories', 'customers', 'employee_territories', 'employees',
    'order_details', 'orders', 'products', 'regions', 'shippers',
    'suppliers', 'territories',
)


def read_snapshot(directory=DATA):
    manifest = json.loads((directory / 'northwind.manifest.json').read_text())
    archive = (directory / 'northwind.sql.gz').read_bytes()
    if hashlib.sha256(archive).hexdigest() != manifest['archive_sha256']:
        raise RuntimeError('Northwind archive checksum mismatch.')
    payload = gzip.decompress(archive)
    if hashlib.sha256(payload).hexdigest() != manifest['sql_sha256']:
        raise RuntimeError('Northwind SQL checksum mismatch.')
    if set(manifest['tables']) != set(NORTHWIND_TABLES):
        raise RuntimeError('Unexpected Northwind table manifest.')
    return payload.decode(), manifest


def initialize_database():
    payload, manifest = read_snapshot()
    sample_uri = os.environ['SAMPLE_DATABASE_URI']
    sample_dsn = parse_dsn(sample_uri)
    core_dsn = parse_dsn(os.environ['DATABASE_URI'])
    if sample_dsn.get('dbname') == core_dsn.get('dbname'):
        raise RuntimeError('Northwind must use a database separate from the core database.')

    # This command runs only against the local Compose cluster. No source URI
    # or Render credential is part of the image or runtime configuration.
    admin_dsn = dict(core_dsn, dbname='postgres', connect_timeout=10)
    admin = psycopg2.connect(**admin_dsn)
    try:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(748210031)')
            cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (sample_dsn['dbname'],))
            if not cursor.fetchone():
                cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(sample_dsn['dbname'])))
    finally:
        admin.close()

    for uri in (os.environ['DATABASE_URI'], sample_uri):
        with psycopg2.connect(uri, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')

    with psycopg2.connect(sample_uri, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(748210032)')
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            present = {row[0] for row in cursor.fetchall()}
            if set(NORTHWIND_TABLES).issubset(present):
                print('Northwind already exists; preserving all existing data.')
                return
            if present:
                raise RuntimeError('Sample database is not empty. Refusing to overwrite or partially restore it.')
            cursor.execute(payload)
            for table, expected in manifest['tables'].items():
                cursor.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
                if cursor.fetchone()[0] != expected:
                    raise RuntimeError('Northwind row count mismatch for ' + table)
    print(f"Restored Northwind: {len(manifest['tables'])} tables, {sum(manifest['tables'].values())} rows.")


def load_documents():
    if not os.environ.get('OPENAI_API_KEY', '').strip():
        raise RuntimeError('Set OPENAI_API_KEY before indexing documents.')

    from distribution.app import create_app
    from iatoolkit.core import current_iatoolkit
    from iatoolkit.repositories.models import DocumentStatus
    from iatoolkit.services.configuration_service import ConfigurationService
    from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
    from iatoolkit.services.profile_service import ProfileService

    app = create_app()
    # Translation/session helpers used during duplicate detection expect a
    # request context even when ingestion is invoked from a CLI command.
    with app.test_request_context('/sample_company/'):
        injector = current_iatoolkit().get_injector()
        company = injector.get(ProfileService).get_company_by_short_name('sample_company')
        config = injector.get(ConfigurationService).get_configuration('sample_company', 'knowledge_base')
        knowledge = injector.get(KnowledgeBaseService)
        count = 0
        for source in config['document_sources'].values():
            files = sorted(Path(source['path']).glob('*.pdf'))
            if not files:
                raise RuntimeError('No sample PDFs found in ' + source['path'])
            for path in files:
                document = knowledge.ingest_document_sync(
                    company=company, filename=path.name, content=path.read_bytes(),
                    collection=source['collection'],
                )
                if document.status != DocumentStatus.ACTIVE:
                    raise RuntimeError('Document indexing failed: ' + path.name)
                count += 1
        print(f'Indexed or reused {count} documents (duplicates are skipped).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('database', 'load-documents'))
    args = parser.parse_args()
    try:
        initialize_database() if args.command == 'database' else load_documents()
    except Exception as exc:
        # Do not print database connection URLs or credentials on failures.
        if isinstance(exc, psycopg2.Error):
            raise SystemExit('Database initialization failed: ' + (exc.diag.message_primary or type(exc).__name__))
        raise SystemExit(str(exc))
