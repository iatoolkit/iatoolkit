# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.interfaces.database_provider import DatabaseProvider
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from injector import inject, singleton
from typing import Callable
import json
import logging
import re


@singleton
class SqlService:
    """
    Manages database connections and executes SQL statements.
    It maintains a cache of named DatabaseManager instances to avoid reconnecting.
    """
    MAX_QUERY_ROWS = 1000
    _ALLOWED_QUERY_PREFIXES = ("SELECT", "WITH")
    _BLOCKED_SQL_PATTERN = re.compile(
        r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|CALL|COPY|GRANT|REVOKE|"
        r"BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|VACUUM|ANALYZE|CLUSTER|REFRESH|"
        r"EXEC(?:UTE)?|DO|SET|RESET|USE|PRAGMA|ATTACH|DETACH|REINDEX|LOCK|UNLOCK|INTO)\b",
        re.IGNORECASE,
    )
    _SINGLE_QUOTED_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
    _DOUBLE_QUOTED_LITERAL_RE = re.compile(r'"(?:""|[^"])*"')
    _BACKTICK_LITERAL_RE = re.compile(r"`[^`]*`")
    _BRACKET_LITERAL_RE = re.compile(r"\[[^\]]*\]")
    _BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
    _LINE_COMMENT_RE = re.compile(r"--[^\r\n]*")

    @inject
    def __init__(self,
                 util: Utility,
                 i18n_service: I18nService):
        self.util = util
        self.i18n_service = i18n_service

        # Cache for database providers. Key is tuple: (company_short_name, db_name)
        # Value is the abstract interface DatabaseProvider
        self._db_connections: dict[tuple[str, str], DatabaseProvider] = {}

        # cache for database schemas. Key is tuple: (company_short_name, db_name)
        self._db_schemas: dict[tuple[str, str], str] = {}

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
        uri = config.get('db_uri') or config.get('DATABASE_URI')
        schema = config.get('schema')
        timeout = config.get('timeout')
        if not uri:
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     "Missing db_uri for direct connection")
        return DatabaseManager(uri, schema=schema, register_pgvector=False, timeout=timeout)

    def register_database(self, company_short_name: str, db_name: str, config: dict):
        """
        Creates and caches a DatabaseProvider instance based on the configuration.
        """
        key = (company_short_name, db_name)

        # Determine connection type (default to 'direct')
        conn_type = config.get('connection_type', 'direct')
        logging.info(f"Registering DB '{db_name}' ({conn_type}) for company '{company_short_name}'")

        factory = self._provider_factories.get(conn_type)
        if not factory:
            logging.error(f"Unknown connection type '{conn_type}' for DB '{db_name}'. Skipping.")
            return

        try:
            # Create the provider using the appropriate factory
            provider_instance = factory(config)
            self._db_connections[key] = provider_instance

            # save the db_schema
            self._db_schemas[key] = config.get('schema', 'public')
        except Exception as e:
            logging.error(f"Failed to register DB '{db_name}': {e}")
            # We don't raise here to allow other DBs to load if one fails

    def clear_company_connections(self, company_short_name: str):
        keys_to_clear = [key for key in self._db_connections if key[0] == company_short_name]
        for key in keys_to_clear:
            provider = self._db_connections.pop(key, None)
            self._db_schemas.pop(key, None)
            # Release resources for providers backed by SQLAlchemy engines.
            try:
                engine = getattr(provider, "engine", None)
                if engine and hasattr(engine, "dispose"):
                    engine.dispose()
            except Exception:
                logging.debug("Failed to dispose SQL engine for key=%s", key)

    def get_db_names(self, company_short_name: str) -> list[str]:
        """
        Returns list of logical database names available ONLY for the specified company.
        """
        return [db for (co, db) in self._db_connections.keys() if co == company_short_name]

    def get_database_dialect(self, company_short_name: str, db_name: str) -> str:
        provider = self.get_database_provider(company_short_name, db_name)
        dialect = getattr(provider, "get_dialect", None)
        if callable(dialect):
            value = dialect()
            if isinstance(value, str):
                return value.strip().lower()
        return ""

    def _hydrate_database_from_catalog(self, company_short_name: str, db_name: str) -> bool:
        try:
            from iatoolkit.core import current_iatoolkit
            from iatoolkit.services.sql_source_service import SqlSourceService

            injector = current_iatoolkit().get_injector()
            sql_source_service = injector.get(SqlSourceService)
            return bool(sql_source_service.ensure_runtime_registration(company_short_name, db_name))
        except Exception as e:
            logging.debug(
                "Unable to hydrate SQL source '%s' for '%s' from catalog: %s",
                db_name,
                company_short_name,
                e,
            )
            return False

    def get_database_provider(self, company_short_name: str, db_name: str) -> DatabaseProvider:
        """
        Retrieves a registered DatabaseProvider instance using the composite key.
        Replaces the old 'get_database_manager'.
        """
        key = (company_short_name, db_name)
        provider = self._db_connections.get(key)
        if provider is not None:
            return provider

        if self._hydrate_database_from_catalog(company_short_name, db_name):
            provider = self._db_connections.get(key)
            if provider is not None:
                return provider

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

    @classmethod
    def _sanitize_sql_for_validation(cls, query: str) -> str:
        sanitized = str(query or "")
        for pattern in (
            cls._SINGLE_QUOTED_LITERAL_RE,
            cls._DOUBLE_QUOTED_LITERAL_RE,
            cls._BACKTICK_LITERAL_RE,
            cls._BRACKET_LITERAL_RE,
        ):
            sanitized = pattern.sub(" ", sanitized)
        sanitized = cls._BLOCK_COMMENT_RE.sub("", sanitized)
        sanitized = cls._LINE_COMMENT_RE.sub("", sanitized)
        return re.sub(r"\s+", " ", sanitized).strip()

    def _assert_read_only_query(self, query: str) -> str:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                "SQL query is required.",
            )

        sanitized = self._sanitize_sql_for_validation(normalized_query)
        if not sanitized:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                "SQL query is required.",
            )
        sanitized_without_trailing_semicolon = re.sub(r";+\s*$", "", sanitized).strip()
        if not sanitized_without_trailing_semicolon:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                "SQL query is required.",
            )
        if ";" in sanitized_without_trailing_semicolon:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                "Only a single read-only SQL statement is allowed.",
            )

        upper_sanitized = sanitized_without_trailing_semicolon.upper()
        blocked_match = self._BLOCKED_SQL_PATTERN.search(upper_sanitized)
        if blocked_match:
            blocked_keyword = blocked_match.group(0).upper()
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                f"Blocked SQL keyword detected: {blocked_keyword}.",
            )

        if not upper_sanitized.startswith(self._ALLOWED_QUERY_PREFIXES):
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                "Only read-only SELECT statements are allowed.",
            )
        if upper_sanitized.startswith("WITH") and not re.search(r"\bSELECT\b", upper_sanitized):
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                "WITH queries must resolve to a read-only SELECT statement.",
            )

        return normalized_query

    def _enforce_result_row_limit(self, result_data):
        if isinstance(result_data, list) and len(result_data) > self.MAX_QUERY_ROWS:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                f"Query returned more than {self.MAX_QUERY_ROWS} rows. Refine the query with filters or LIMIT.",
            )

    @staticmethod
    def _cleanup_provider_execution(provider: DatabaseProvider):
        remove_session = getattr(provider, "remove_session", None)
        if callable(remove_session):
            try:
                remove_session()
                return
            except Exception as exc:
                logging.debug("Failed to remove SQL provider session: %s", exc)

        rollback = getattr(provider, "rollback", None)
        if callable(rollback):
            try:
                rollback()
            except Exception as exc:
                logging.debug("Failed to rollback SQL provider session: %s", exc)

    def exec_sql(self, company_short_name: str, **kwargs):
        """
        Executes a raw SQL statement against a registered database provider.
        Delegates the actual execution details to the provider implementation.
        """
        database_name = kwargs.get('database_key')
        query = kwargs.get('query')
        format = kwargs.get('format', 'json')
        params = kwargs.get('params')
        provider = None
        cleanup_required = False

        if not database_name:
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     'missing database_name in call to exec_sql')
        if kwargs.get('commit'):
            logging.warning("Ignoring commit=True for read-only SQL execution against '%s'.", database_name)

        try:
            # 1. Get the abstract provider (could be Direct or Bridge)
            provider = self.get_database_provider(company_short_name, database_name)
            safe_query = self._assert_read_only_query(query)

            # 2. Delegate execution
            # The provider returns a clean List[Dict] or Dict result
            execute_kwargs = {
                "query": safe_query,
                "commit": False,
            }
            if params is not None:
                execute_kwargs["params"] = params
            cleanup_required = True
            result_data = provider.execute_query(**execute_kwargs)
            self._enforce_result_row_limit(result_data)

            # 3. Handle Formatting (Service layer responsibility)
            if format == 'dict':
                return result_data

            # Serialize the result
            return json.dumps(result_data, default=self.util.serialize)

        except IAToolkitException:
            raise
        except Exception as e:
            error_message = str(e)
            if 'timed out' in str(e):
                error_message = self.i18n_service.t('errors.timeout')

            logging.error(f"Error executing SQL statement: {error_message}")
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                                     error_message) from e
        finally:
            if provider is not None and cleanup_required:
                self._cleanup_provider_execution(provider)

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

    def get_database_structure(self, company_short_name: str, db_name: str) -> dict:
        """
        Introspects the specified database and returns its structure (Tables & Columns).
        Used for the Schema Editor 2.0
        """
        try:
            provider = self.get_database_provider(company_short_name, db_name)
            return provider.get_database_structure()
        except IAToolkitException:
            raise
        except Exception as e:
            logging.error(f"Error introspecting database '{db_name}': {e}")
            raise IAToolkitException(
                IAToolkitException.ErrorType.DATABASE_ERROR,
                f"Failed to introspect database: {str(e)}"
            )
