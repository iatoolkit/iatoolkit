# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.interfaces.database_provider import DatabaseProvider
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from injector import inject, singleton
from typing import Callable
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

        # Cache for database providers. Key is tuple: (company_short_name, db_name)
        # Value is the abstract interface DatabaseProvider
        self._db_connections: dict[tuple[str, str], DatabaseProvider] = {}

        # Registry of factory functions.
        # Format: {'connection_type': function(config_dict) -> DatabaseProvider}
        self._provider_factories: dict[str, Callable[[dict], DatabaseProvider]] = {}

        # Register the default 'direct' strategy (SQLAlchemy)
        self.register_provider_factory('direct', self._create_direct_connection)

    def register_provider_factory(self, connection_type: str, factory: Callable[[dict], DatabaseProvider]):
        """
        Allows plugins (Enterprise) to register new connection types.
        """
        self._provider_factories[connection_type] = factory

    def _create_direct_connection(self, config: dict) -> DatabaseProvider:
        """Default factory for standard SQLAlchemy connections."""
        uri = config.get('db_uri')
        schema = config.get('schema')
        if not uri:
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     "Missing db_uri for direct connection")
        return DatabaseManager(uri, schema=schema, register_pgvector=False)

    def register_database(self, company_short_name: str, db_name: str, config: dict):
        """
        Creates and caches a DatabaseProvider instance based on the configuration.
        """
        key = (company_short_name, db_name)
        if key in self._db_connections:
            return

        # Determine connection type (default to 'direct')
        conn_type = config.get('connection_type', 'direct')
        logging.info(f"Registering DB '{db_name}' ({conn_type}) for company '{company_short_name}'")

        factory = self._provider_factories.get(conn_type)
        if not factory:
            logging.warning(f"Unknown connection type '{conn_type}' for DB '{db_name}'. Skipping.")
            return

        try:
            # Create the provider using the appropriate factory
            provider_instance = factory(config)
            self._db_connections[key] = provider_instance
        except Exception as e:
            logging.error(f"Failed to register DB '{db_name}': {e}")
            # We don't raise here to allow other DBs to load if one fails

    def get_db_names(self, company_short_name: str) -> list[str]:
        """
        Returns list of logical database names available ONLY for the specified company.
        """
        return [db for (co, db) in self._db_connections.keys() if co == company_short_name]

    def get_database_provider(self, company_short_name: str, db_name: str) -> DatabaseProvider:
        """
        Retrieves a registered DatabaseProvider instance using the composite key.
        Replaces the old 'get_database_manager'.
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
        Executes a raw SQL statement against a registered database provider.
        Delegates the actual execution details to the provider implementation.
        """
        database_name = kwargs.get('database_key')
        query = kwargs.get('query')
        format = kwargs.get('format', 'json')
        commit = kwargs.get('commit')

        if not database_name:
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     'missing database_name in call to exec_sql')

        try:
            # 1. Get the abstract provider (could be Direct or Bridge)
            provider = self.get_database_provider(company_short_name, database_name)

            # 2. Delegate execution
            # The provider returns a clean List[Dict] or Dict result
            result_data = provider.execute_query(query, commit=commit)

            # 3. Handle Formatting (Service layer responsibility)
            if format == 'dict':
                return result_data

            # Serialize the result
            return json.dumps(result_data, default=self.util.serialize)

        except IAToolkitException:
            raise
        except Exception as e:
            # Attempt rollback if supported/needed
            try:
                provider = self.get_database_provider(company_short_name, database_name)
                if provider:
                    provider.rollback()
            except Exception:
                pass

            error_message = str(e)
            if 'timed out' in str(e):
                error_message = self.i18n_service.t('errors.timeout')

            logging.error(f"Error executing SQL statement: {error_message}")
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     error_message) from e

    def commit(self, company_short_name: str, database_name: str):
        """
        Commits the current transaction for a registered database provider.
        """
        provider = self.get_database_provider(company_short_name, database_name)
        try:
            provider.commit()
        except Exception as e:
            # Try rollback
            try:
                provider.rollback()
            except:
                pass
            logging.error(f"Error while committing sql: '{str(e)}'")
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR, str(e)
            )