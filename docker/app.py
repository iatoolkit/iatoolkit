"""Community entry point; independent of the repository's development app.py."""

import os
from pathlib import Path

from flask import jsonify, redirect
from iatoolkit import BaseCompany, IAToolkit, register_company
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.sql_source_service import SqlSourceService
from sqlalchemy import text
from distribution.entrypoint import initialize_state


class DockerSampleCompany(BaseCompany):
    @classmethod
    def get_resource_root(cls):
        return Path(os.environ.get('IATOOLKIT_DEMO_ROOT', '/opt/demo-resources'))

    def handle_request(self, tag, **kwargs):
        return self.unsupported_operation(tag)


def create_app():
    # `docker compose exec` does not inherit variables set by PID 1. Flask CLI
    # commands must resolve the same persisted keys as the web entry point.
    initialize_state(Path(os.environ.get('IATOOLKIT_DATA_DIR', '/var/lib/iatoolkit')))
    register_company('sample_company', DockerSampleCompany)
    toolkit = IAToolkit()
    app = toolkit.create_iatoolkit(start=False)
    config = toolkit.get_injector().get(ConfigurationService)
    # Fail a new distribution early if its checked-in demo config is invalid.
    errors = config.validate_configuration('sample_company')
    if errors:
        raise RuntimeError('Invalid Docker demo configuration: ' + '; '.join(errors))
    # SQL runtime registrations come from the catalog, not directly from YAML.
    # Seed this deployment's catalog once through the public service, preserving
    # any later edits to the persisted source (including deactivation).
    sources = toolkit.get_injector().get(SqlSourceService)
    existing = {item['database'] for item in sources.list_sources('sample_company', include_inactive=True)}
    for source in config.get_configuration('sample_company', 'data_sources')['sql']:
        if source['database'] not in existing:
            sources.create_source('sample_company', source)
    toolkit.register_data_sources()

    @app.get('/')
    def index():
        return redirect('/sample_company/home')

    @app.get('/healthz')
    def health():
        try:
            with toolkit.get_database_manager().get_connection() as connection:
                connection.execute(text('SELECT 1'))
            sql_service = toolkit.get_injector().get(SqlService)
            provider = sql_service.get_database_provider('sample_company', 'sample_db')
            with provider.get_connection() as connection:
                connection.execute(text('SELECT 1 FROM public.orders LIMIT 1'))
            app.config['SESSION_REDIS'].ping()
        except Exception:
            return jsonify(status='unavailable'), 503
        return jsonify(status='ok', edition='community')

    return app
