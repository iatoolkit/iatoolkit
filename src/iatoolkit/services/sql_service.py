# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.util import Utility
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from injector import inject, singleton
import json
import logging


@singleton
class SqlService:
    """
    Manages database connections and executes SQL statements.
    It maintains a cache of named DatabaseManager instances to avoid reconnecting.
    """

    @inject
    def __init__(self,
                 util: Utility,
                 i18n_service: I18nService):
        self.util = util
        self.i18n_service = i18n_service

        # Cache for database connections. Key is tuple: (company_short_name, db_name)
        self._db_connections: dict[tuple[str, str], DatabaseManager] = {}

    def register_database(self, company_short_name: str, db_uri: str, db_name: str, schema: str | None = None):
        """
        Creates and caches a DatabaseManager instance for a given company, database name and URI.
        Composite key avoids collisions between companies using the same logical db name.
        """
        key = (company_short_name, db_name)

        if key in self._db_connections:
            return

        logging.info(f"Registering DB '{db_name}' for company '{company_short_name}' (schema: {schema})")

        # Create the database connection and save it on the cache
        db_manager = DatabaseManager(db_uri, schema=schema, register_pgvector=False)
        self._db_connections[key] = db_manager

    def get_db_names(self, company_short_name: str) -> list[str]:
        """
        Returns list of logical database names available ONLY for the specified company.
        This is used to populate the tool definition enum for the LLM.
        """
        return [db for (co, db) in self._db_connections.keys() if co == company_short_name]

    def get_database_manager(self, company_short_name: str, db_name: str) -> DatabaseManager:
        """
        Retrieves a registered DatabaseManager instance using the composite key.
        """
        key = (company_short_name, db_name)
        try:
            return self._db_connections[key]
        except KeyError:
            logging.error(
                f"Attempted to access unregistered database: '{db_name}' for company '{company_short_name}'"
            )
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                f"Database '{db_name}' is not registered for this company."
            )

    def exec_sql(self, company_short_name: str, **kwargs):
        """
        Executes a raw SQL statement against a registered database.

        Args:
            company_short_name: The company identifier (for logging/context).
            database: The logical name of the database to query.
            query: The SQL statement to execute.
            format: The output format ('json' or 'dict'). Only relevant for SELECT queries.
            commit: Whether to commit the transaction immediately after execution.
                    Use True for INSERT/UPDATE/DELETE statements.

        Returns:
            - A JSON string or list of dicts for SELECT queries.
            - A dictionary {'rowcount': N} for non-returning statements (INSERT/UPDATE) if not using RETURNING.
        """
        database_name = kwargs.get('database_key')
        query = kwargs.get('query')
        format = kwargs.get('format', 'json')
        commit = kwargs.get('commit')

        if not database_name:
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     'missing database_name in call to exec_sql')


        try:
            # 1. Get the database manager from the cache
            db_manager = self.get_database_manager(company_short_name, database_name)
            session = db_manager.get_session()

            # 2. Execute the SQL statement
            result = session.execute(text(query))

            # 3. Handle Commit
            if commit:
                session.commit()

            # 4. Process Results
            # Check if the query returns rows (e.g., SELECT or INSERT ... RETURNING)
            if result.returns_rows:
                cols = result.keys()
                rows_context = [dict(zip(cols, row)) for row in result.fetchall()]

                if format == 'dict':
                    return rows_context

                # serialize the result
                return json.dumps(rows_context, default=self.util.serialize)

            # For statements that don't return rows (standard UPDATE/DELETE)
            return {'rowcount': result.rowcount}

        except IAToolkitException:
            # Re-raise exceptions from get_database_manager to preserve the specific error
            raise
        except Exception as e:
            # Attempt to rollback if a session was active
            try:
                db_manager = self.get_database_manager(company_short_name, database_name)
                if db_manager:
                    db_manager.get_session().rollback()
            except Exception:
                pass            # Ignore rollback errors during error handling


            error_message = str(e)
            if 'timed out' in str(e):
                error_message = self.i18n_service.t('errors.timeout')

            logging.error(f"Error executing SQL statement: {error_message}")
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     error_message) from e

    def commit(self, company_short_name: str, database_name: str):
        """
        Commits the current transaction for a registered database (scoped to company).
        """
        db_manager = self.get_database_manager(company_short_name, database_name)
        try:
            db_manager.get_session().commit()
        except SQLAlchemyError as db_error:
            db_manager.get_session().rollback()
            logging.error(f"Database error: {str(db_error)}")
            raise db_error
        except Exception as e:
            logging.error(f"Error while commiting sql: '{str(e)}'")
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR, str(e)
            )