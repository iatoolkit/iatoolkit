# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# database_manager.py
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine.url import make_url
from iatoolkit.repositories.models import Base
from injector import inject
from pgvector.psycopg2 import register_vector
from iatoolkit.common.interfaces.database_provider import DatabaseProvider
import logging


class DatabaseManager(DatabaseProvider):
    @inject
    def __init__(self,
                 database_url: str,
                 schema: str = 'public',
                 register_pgvector: bool = True):
        """
        Inicializa el gestor de la base de datos.
        :param database_url: URL de la base de datos.
        :param schema: Esquema por defecto para la conexión (search_path).
        :param echo: Si True, habilita logs de SQL.
        """

        self.schema = schema

        # FIX HEROKU: replace postgres:// by postgresql:// for compatibility with SQLAlchemy 1.4+
        if database_url and database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        self.url = make_url(database_url)

        if database_url.startswith('sqlite'):
            self._engine = create_engine(database_url, echo=False)
        else:
            self._engine = create_engine(
                database_url,
                echo=False,
                pool_size=10,  # per worker
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,
                pool_use_lifo=True,
                connect_args={
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5,
                    "connect_timeout": 10,
                },
                future=True,
            )
        self.SessionFactory = sessionmaker(bind=self._engine,
                                           autoflush=False,
                                           autocommit=False,
                                           expire_on_commit=False)
        self.scoped_session = scoped_session(self.SessionFactory)

        # Register pgvector for each new connection
        backend = self.url.get_backend_name()
        if backend == 'postgresql' or backend == 'postgres':
            if register_pgvector:
                event.listen(self._engine, 'connect', self.on_connect)

            # if there is a schema, configure the search_path for each connection
            if self.schema:
                event.listen(self._engine, 'checkout', self.set_search_path)

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
        return self.scoped_session()

    def get_connection(self):
        return self._engine.connect()

    def create_all(self):
        # if there is a schema defined, make sure it exists before creating tables
        backend = self.url.get_backend_name()
        if self.schema and (backend == 'postgresql' or backend == 'postgres'):
            with self._engine.begin() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema}"))

        Base.metadata.create_all(self._engine)

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
        if self.schema:
            session.execute(text(f"SET search_path TO {self.schema}"))

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
        for table in inspector.get_table_names(schema=self.schema):
            columns_data = []

            # get columns
            try:
                columns = inspector.get_columns(table, schema=self.schema)
                # Obtener PKs para marcarlas
                pks = inspector.get_pk_constraint(table, schema=self.schema).get('constrained_columns', [])

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
