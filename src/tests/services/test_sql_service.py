# tests/services/test_sql_service.py

import pytest
from unittest.mock import MagicMock, patch
import json
from datetime import datetime

from oauthlib.uri_validate import query

from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.database_provider import DatabaseProvider

# Constants
COMPANY_SHORT_NAME = 'test_company'
DB_NAME_SUCCESS = 'test_db'
DB_NAME_UNREGISTERED = 'unregistered_db'
DUMMY_URI = 'sqlite:///:memory:'


class TestSqlService:
    """
    Unit tests for the refactored SqlService.
    Now verifies that it correctly delegates to DatabaseProviders via the Factory pattern.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """
        Sets up mocks for dependencies and creates a fresh SqlService instance for each test.
        """
        self.util_mock = MagicMock(spec=Utility)
        # Default serialize behavior: just return the object (json.dumps handles basic types)
        self.util_mock.serialize.side_effect = lambda x: x

        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.service = SqlService(util=self.util_mock, i18n_service=self.mock_i18n_service)

    # --- Tests for Factory & Registration ---

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_register_database_direct_creates_manager(self, MockDatabaseManager):
        """
        GIVEN a 'direct' connection config
        WHEN register_database is called
        THEN it should instantiate DatabaseManager with the correct URI and schema.
        """
        # Arrange
        config = {
            'connection_type': 'direct',
            'DATABASE_URI': DUMMY_URI,
            'schema': 'an_schema'
        }

        # Act
        self.service.register_database(COMPANY_SHORT_NAME, DB_NAME_SUCCESS, config)

        # Assert
        MockDatabaseManager.assert_called_once_with(DUMMY_URI, schema='an_schema', register_pgvector=False)

        expected_key = (COMPANY_SHORT_NAME, DB_NAME_SUCCESS)
        assert expected_key in self.service._db_connections
        assert self.service._db_connections[expected_key] == MockDatabaseManager.return_value

    def test_register_custom_provider_factory(self):
        """
        GIVEN a custom provider factory (e.g., for Bridge)
        WHEN register_provider_factory is used and then register_database is called
        THEN it should use the custom factory to create the provider.
        """
        # Arrange
        mock_factory = MagicMock()
        mock_provider = MagicMock(spec=DatabaseProvider)
        mock_factory.return_value = mock_provider

        # Register the custom factory/plugin
        self.service.register_provider_factory('bridge', mock_factory)

        config = {
            'connection_type': 'bridge',
            'bridge_id': 'agent-123'
        }

        # Act
        self.service.register_database(COMPANY_SHORT_NAME, 'bridge_db', config)

        # Assert
        mock_factory.assert_called_once_with(config)
        assert self.service.get_database_provider(COMPANY_SHORT_NAME, 'bridge_db') == mock_provider

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_register_database_not_skips_if_already_exists(self, MockDatabaseManager):
        """
        GIVEN a database is already registered
        WHEN register_database is called again
        THEN it should verify cache hit and NOT create a new instance.
        """
        config = {'connection_type': 'direct', 'DATABASE_URI': DUMMY_URI}

        # Act
        self.service.register_database(COMPANY_SHORT_NAME, DB_NAME_SUCCESS, config)
        self.service.register_database(COMPANY_SHORT_NAME, DB_NAME_SUCCESS, config)  # Second call

        # Assert
        assert MockDatabaseManager.call_count == 2

    # --- Tests for Provider Retrieval ---

    def test_get_database_provider_raises_exception_if_not_found(self):
        """
        GIVEN an empty SqlService
        WHEN get_database_provider is called with unregistered DB
        THEN it should raise IAToolkitException.
        """
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.get_database_provider(COMPANY_SHORT_NAME, DB_NAME_UNREGISTERED)

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert f"Database '{DB_NAME_UNREGISTERED}' is not registered" in str(exc_info.value)

    def test_get_db_names_filters_by_company(self):
        """
        GIVEN multiple registered databases
        WHEN get_db_names is called
        THEN it should return strictly the databases for that company.
        """
        config = {'DATABASE_URI': DUMMY_URI}

        # We assume mocks for the underlying providers since we just check keys here
        with patch('iatoolkit.services.sql_service.DatabaseManager'):
            self.service.register_database('company_A', 'db_sales', config)
            self.service.register_database('company_A', 'db_hr', config)
            self.service.register_database('company_B', 'db_sales', config)

            # Act
        db_names_A = self.service.get_db_names('company_A')

        # Assert
        assert set(db_names_A) == {'db_sales', 'db_hr'}

    # --- Tests for exec_sql (Delegation Logic) ---

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_exec_sql_delegates_to_provider_success(self, MockDatabaseManager):
        """
        GIVEN a registered provider
        WHEN exec_sql is called
        THEN it should call provider.execute_query and serialize the result.
        """
        # Arrange
        mock_provider = MockDatabaseManager.return_value

        # The provider is expected to return a list of dicts directly now (clean interface)
        db_data = [{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}]
        mock_provider.execute_query.return_value = db_data

        config = {'DATABASE_URI': DUMMY_URI, 'schema': 'web_db'}
        self.service.register_database(COMPANY_SHORT_NAME, DB_NAME_SUCCESS, config)

        # Act
        result_json = self.service.exec_sql(company_short_name=COMPANY_SHORT_NAME,
                                            database_key=DB_NAME_SUCCESS,
                                            query="SELECT * FROM users")

        # Assert
        # 1. Verify delegation
        mock_provider.execute_query.assert_called_once_with(
                    db_schema='web_db',
                    query="SELECT * FROM users",
            commit=None)

        # 2. Verify serialization
        expected_json = json.dumps(db_data)
        assert result_json == expected_json

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_exec_sql_with_custom_serialization(self, MockDatabaseManager):
        """
        GIVEN a provider returning complex objects (datetime)
        WHEN exec_sql is called
        THEN it should use util.serialize to handle them.
        """
        # Arrange
        mock_provider = MockDatabaseManager.return_value
        dt = datetime(2024, 1, 1)

        # Mocking the provider response (raw data)
        mock_provider.execute_query.return_value = [{'event_time': dt}]

        # Mocking utility serializer logic
        self.util_mock.serialize.side_effect = lambda obj: obj.isoformat() if isinstance(obj, datetime) else obj

        config = {'DATABASE_URI': DUMMY_URI}
        self.service.register_database(COMPANY_SHORT_NAME, DB_NAME_SUCCESS, config)

        # Act
        result_json = self.service.exec_sql(company_short_name=COMPANY_SHORT_NAME,
                                            database_key=DB_NAME_SUCCESS,
                                            query="SELECT time")

        # Assert
        self.util_mock.serialize.assert_called_with(dt)
        assert '"2024-01-01T00:00:00"' in result_json

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_exec_sql_handles_provider_error(self, MockDatabaseManager):
        """
        GIVEN a provider that raises an exception during execution
        WHEN exec_sql is called
        THEN it should attempt rollback on the provider and re-raise as IAToolkitException.
        """
        # Arrange
        mock_provider = MockDatabaseManager.return_value
        db_error = Exception("Connection lost")
        mock_provider.execute_query.side_effect = db_error

        config = {'DATABASE_URI': DUMMY_URI}
        self.service.register_database(COMPANY_SHORT_NAME, DB_NAME_SUCCESS, config)

        # Act & Assert
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.exec_sql(company_short_name=COMPANY_SHORT_NAME,
                                  database_key=DB_NAME_SUCCESS,
                                  query="SELECT *")

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert "Connection lost" in str(exc_info.value)

        # Verify rollback called on provider
        mock_provider.rollback.assert_called_once()