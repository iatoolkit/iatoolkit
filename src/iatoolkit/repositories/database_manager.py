# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# database_manager.py
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine.url import make_url
from iatoolkit.repositories.models import Base, ORM_SCHEMA
from injector import inject
from pgvector.psycopg2 import register_vector
from iatoolkit.common.interfaces.database_provider import DatabaseProvider
import logging


class DatabaseManager(DatabaseProvider):
    _POSTGRES_BOOTSTRAP_PATCHES = (
    )
    _DEFAULT_CONNECT_TIMEOUT = 10

    @inject
    def __init__(self,
                 database_url: str,
                 schema: str = 'public',
                 register_pgvector: bool = True,
                 timeout: int | None = None):
        """
        Inicializa el gestor de la base de datos.
        :param database_url: URL de la base de datos.
        :param schema: Esquema por defecto para la conexión (search_path).
        :param echo: Si True, habilita logs de SQL.
        """

        self.schema = schema
        self.timeout = self._normalize_timeout(timeout)

        # FIX HEROKU: replace postgres:// by postgresql:// for compatibility with SQLAlchemy 1.4+
        if database_url and database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        self.url = make_url(database_url)
        self.backend = self.url.get_backend_name()
        self.engine_url = self._build_engine_url()

        if self.backend == 'sqlite':
            raw_engine = create_engine(self.engine_url, echo=False)
        else:
            raw_engine = create_engine(
                self.engine_url,
                echo=False,
                pool_size=10,  # per worker
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,
                pool_use_lifo=True,
                connect_args=self._build_connect_args(),
                future=True,
            )
        translated_schema = self.schema if self._is_postgres() else None
        self._engine = raw_engine.execution_options(
            schema_translate_map={ORM_SCHEMA: translated_schema}
        )
        self.engine = self._engine
        self.SessionFactory = sessionmaker(bind=self._engine,
                                           autoflush=False,
                                           autocommit=False,
                                           expire_on_commit=False)
        self.scoped_session = scoped_session(self.SessionFactory)

        # Register pgvector for each new connection
        if self._is_postgres():
            if register_pgvector:
                event.listen(raw_engine, 'connect', self.on_connect)

            # if there is a schema, configure the search_path for each connection
            if self.schema:
                event.listen(raw_engine, 'checkout', self.set_search_path)

    def _is_postgres(self) -> bool:
        return self.backend in ('postgresql', 'postgres')

    def _is_redshift(self) -> bool:
        return self.backend == 'redshift'

    def _is_mysql(self) -> bool:
        return self.backend == 'mysql'

    @classmethod
    def _normalize_timeout(cls, timeout: int | str | None) -> int:
        if timeout is None:
            return cls._DEFAULT_CONNECT_TIMEOUT

        try:
            normalized = int(timeout)
        except (TypeError, ValueError):
            return cls._DEFAULT_CONNECT_TIMEOUT

        return normalized if normalized > 0 else cls._DEFAULT_CONNECT_TIMEOUT

    def _resolve_timeout(self) -> int:
        if self.timeout != self._DEFAULT_CONNECT_TIMEOUT:
            return self.timeout

        for query_key in ("timeout", "connect_timeout"):
            value = self.url.query.get(query_key)
            if value is None:
                continue
            return self._normalize_timeout(value)

        return self.timeout

    def _build_engine_url(self):
        normalized_url = self.url
        if self._is_redshift():
            normalized_url = self.url.difference_update_query(["timeout", "connect_timeout"])

        return normalized_url.render_as_string(hide_password=False)

    def _build_connect_args(self) -> dict:
        resolved_timeout = self._resolve_timeout()

        if self._is_postgres():
            return {
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
                "connect_timeout": resolved_timeout,
            }
        if self._is_redshift():
            return {
                "timeout": resolved_timeout,
            }
        if self._is_mysql():
            return {
                "connect_timeout": resolved_timeout,
            }
        return {
            "connect_timeout": resolved_timeout,
        }

    def _effective_schema(self) -> str | None:
        if self.backend == 'sqlite':
            return None

        if self._is_postgres():
            return self.schema

        if self._is_redshift():
            normalized = str(self.schema or "").strip()
            return normalized or "public"

        if self._is_mysql():
            normalized = str(self.schema or "").strip()
            if normalized and normalized.lower() != "public":
                return normalized
            return self.url.database

        normalized = str(self.schema or "").strip()
        return normalized or None

    def set_search_path(self, dbapi_connection, connection_record, connection_proxy):
        # Configure the search_path for this connection
        cursor = dbapi_connection.cursor()

        # The defined schema is first, and then public by default
        try:
            cursor.execute(f"SET search_path TO {self.schema}, public")
            cursor.close()

            # commit for persist the change in the session
            dbapi_connection.commit()
        except Exception:
            # if failed, rollback to avoid invalidating the connection
            dbapi_connection.rollback()

    @staticmethod
    def on_connect(dbapi_connection, connection_record):
        """
        Esta función se ejecuta cada vez que se establece una conexión.
        dbapi_connection es la conexión psycopg2 real.
        """
        register_vector(dbapi_connection)

    def get_session(self):
        # Return the scoped_session proxy itself so each operation resolves
        # against the current request/thread-bound Session.
        return self.scoped_session

    def get_connection(self):
        return self._engine.connect()

    def get_dialect(self) -> str:
        return str(self.backend or "").strip().lower()

    def create_all(self):
        # if there is a schema defined, make sure it exists before creating tables
        if self.schema and self._is_postgres():
            with self._engine.begin() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema}"))

        Base.metadata.create_all(self._engine)
        applied_patches = self._apply_bootstrap_patches()
        if applied_patches:
            logging.info(
                "Ensured PostgreSQL bootstrap schema compatibility (%s statements).",
                len(applied_patches),
            )

    def _apply_bootstrap_patches(self) -> list[str]:
        if not self._is_postgres():
            return []

        applied = []
        with self._engine.begin() as conn:
            if self.schema:
                conn.execute(text(f"SET search_path TO {self.schema}, public"))

            for patch_name, statement in self._POSTGRES_BOOTSTRAP_PATCHES:
                conn.execute(text(statement.format(schema=self.schema)))
                applied.append(patch_name)

        return applied

    def drop_all(self):
        Base.metadata.drop_all(self._engine)

    def remove_session(self):
        self.scoped_session.remove()

    # -- execution methods ----

    def execute_query(self, query: str, commit: bool = False) -> list[dict] | dict:
        """
        Implementation for Direct SQLAlchemy connection.
        """
        session = self.get_session()
        if self._is_postgres() and self.schema:
            session.execute(text(f"SET search_path TO {self.schema}"))
        elif self._is_redshift():
            normalized_schema = str(self.schema or "").strip()
            if normalized_schema and normalized_schema.lower() != "public":
                session.execute(text(f"SET search_path TO {normalized_schema}, public"))

        result = session.execute(text(query))
        if commit:
            session.commit()

        if result.returns_rows:
            # Convert SQLAlchemy rows to list of dicts immediately
            cols = result.keys()
            return [dict(zip(cols, row)) for row in result.fetchall()]

        return {'rowcount': result.rowcount}

    def commit(self):
        self.get_session().commit()

    def rollback(self):
        self.get_session().rollback()

    # -- schema methods ----
    def get_database_structure(self) -> dict:
        inspector = inspect(self._engine)
        structure = {}
        effective_schema = self._effective_schema()
        for table in inspector.get_table_names(schema=effective_schema):
            columns_data = []

            # get columns
            try:
                columns = inspector.get_columns(table, schema=effective_schema)
                # Obtener PKs para marcarlas
                pks = inspector.get_pk_constraint(table, schema=effective_schema).get('constrained_columns', [])

                for col in columns:
                    columns_data.append({
                        "name": col['name'],
                        "type": str(col['type']),
                        "nullable": col.get('nullable', True),
                        "pk": col['name'] in pks
                    })
            except Exception as e:
                logging.warning(f"Could not inspect columns for table {table}: {e}")

            structure[table] = {
                "columns": columns_data
            }

        return structure
