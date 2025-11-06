# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# database_manager.py
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.engine.url import make_url
from iatoolkit.repositories.models import Base
from injector import inject
from pgvector.psycopg2 import register_vector


class DatabaseManager:
    @inject
    def __init__(self, database_url: str, register_pgvector: bool = True):
        """
        Inicializa el gestor de la base de datos.
        :param database_url: URL de la base de datos.
        :param echo: Si True, habilita logs de SQL.
        """
        self.url = make_url(database_url)
        if database_url.startswith('sqlite'):       # for tests
            self._engine = create_engine(database_url, echo=False)
        else:
            self._engine = create_engine(
                database_url,
                echo=False,
                pool_size=2,  # per worker
                max_overflow=3,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,
                future=True,
            )
        self.SessionFactory = sessionmaker(bind=self._engine,
                                           autoflush=False,
                                           autocommit=False,
                                           expire_on_commit=False)
        self.scoped_session = scoped_session(self.SessionFactory)

        # REGISTRAR pgvector para cada nueva conexión solo en postgres
        if register_pgvector and self.url.get_backend_name() == 'postgresql':
            event.listen(self._engine, 'connect', self.on_connect)

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

    def get_engine(self):
        return self._engine

    def create_all(self):
        Base.metadata.create_all(self._engine)

    def drop_all(self):
        Base.metadata.drop_all(self._engine)

    def remove_session(self):
        self.scoped_session.remove()

    def get_table_schema(self,
                         table_name: str,
                         schema_name: str | None = None,
                         exclude_columns: list[str] | None = None) -> str:
        inspector = inspect(self._engine)

        if table_name not in inspector.get_table_names():
            raise RuntimeError(f"Table '{table_name}' does not exist.")

        if exclude_columns is None:
            exclude_columns = []

        # get all thre table columns
        columns = inspector.get_columns(table_name)

        # construct a json dictionary with the table definition
        json_dict = {
            "table": table_name,
            "description": f"Definición de la tabla {table_name}.",
            "fields": []
        }
        if schema_name:
            json_dict["description"] += f"Los detalles de cada campo están en el objeto **`{schema_name}`**."

        # now add every column to the json dictionary
        for col in columns:
            name = col["name"]

            # omit the excluded columns.
            if name in exclude_columns:
                continue

            json_dict["fields"].append({
                "name": name,
                "type": str(col["type"]),
            })

        return "\n\n" + str(json_dict)
