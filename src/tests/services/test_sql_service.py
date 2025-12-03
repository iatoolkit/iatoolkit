# tests/services/test_sql_service.py

import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy import text
import json
from datetime import datetime

from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException

# No es necesario importar DatabaseManager aquí, ya que se mockea

# Constantes para nombres de BD para evitar typos
DB_NAME_SUCCESS = 'test_db'
DB_NAME_UNREGISTERED = 'unregistered_db'
DUMMY_URI = 'sqlite:///:memory:'


class TestSqlService:
    """
    Unit tests for the refactored SqlService, which now manages a cache of
    named DatabaseManager instances.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """
        Sets up mocks for dependencies and creates a fresh SqlService instance for each test.
        """
        self.util_mock = MagicMock(spec=Utility)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.service = SqlService(util=self.util_mock, i18n_service=self.mock_i18n_service)

    # --- Tests for Registration and Retrieval ---

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_register_database_creates_and_caches_manager(self, MockDatabaseManager):
        """
        GIVEN an empty SqlService
        WHEN register_database is called with a new name and URI
        THEN it should instantiate DatabaseManager and cache the instance.
        """
        # Act
        self.service.register_database(DUMMY_URI, DB_NAME_SUCCESS, 'an_schema')

        # Assert
        MockDatabaseManager.assert_called_once_with(DUMMY_URI, schema='an_schema',register_pgvector=False)
        assert DB_NAME_SUCCESS in self.service._db_connections
        assert self.service._db_connections[DB_NAME_SUCCESS] == MockDatabaseManager.return_value

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_register_database_skips_if_already_exists(self, MockDatabaseManager):
        """
        GIVEN a database is already registered
        WHEN register_database is called again with the same name
        THEN it should not create a new DatabaseManager instance.
        """
        # Act
        self.service.register_database(DUMMY_URI, DB_NAME_SUCCESS)
        self.service.register_database('another_uri', DB_NAME_SUCCESS)  # Call again

        # Assert
        MockDatabaseManager.assert_called_once()  # Still only called once

    def test_get_database_manager_raises_exception_if_not_found(self):
        """
        GIVEN an empty SqlService
        WHEN get_database_manager is called with an unregistered name
        THEN it should raise an IAToolkitException.
        """
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.get_database_manager(DB_NAME_UNREGISTERED)

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert f"Database '{DB_NAME_UNREGISTERED}' is not registered" in str(exc_info.value)

    # --- Tests for exec_sql ---

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_exec_sql_success_with_simple_data(self, MockDatabaseManager):
        """
        GIVEN a registered database
        WHEN exec_sql is called with simple data
        THEN it should return the correct JSON string.
        """
        # Arrange: Set up mocks for the DB interaction
        mock_db_manager = MockDatabaseManager.return_value
        session_mock = mock_db_manager.get_session.return_value
        mock_result_proxy = session_mock.execute.return_value

        mock_result_proxy.keys.return_value = ['id', 'name']
        mock_result_proxy.fetchall.return_value = [(1, 'Alice'), (2, 'Bob')]

        # Arrange: Register the database
        self.service.register_database(DUMMY_URI, DB_NAME_SUCCESS)

        # Act
        sql_statement = "SELECT id, name FROM users"
        result_json = self.service.exec_sql('temp_company', DB_NAME_SUCCESS, sql_statement)

        # Assert
        mock_db_manager.get_session.assert_called_once()
        session_mock.execute.assert_called_once()
        expected_json = json.dumps([{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}])
        assert result_json == expected_json
        self.util_mock.serialize.assert_not_called()

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_exec_sql_with_custom_serialization(self, MockDatabaseManager):
        """
        GIVEN a registered database returning custom types (datetime)
        WHEN exec_sql is called
        THEN it should use the custom serializer.
        """
        # Arrange
        mock_db_manager = MockDatabaseManager.return_value
        session_mock = mock_db_manager.get_session.return_value
        mock_result_proxy = session_mock.execute.return_value

        original_datetime = datetime(2024, 1, 1)
        self.util_mock.serialize.side_effect = lambda obj: obj.isoformat() if isinstance(obj, datetime) else obj

        mock_result_proxy.keys.return_value = ['event_time']
        mock_result_proxy.fetchall.return_value = [(original_datetime,)]

        self.service.register_database(DUMMY_URI, DB_NAME_SUCCESS )

        # Act
        result_json = self.service.exec_sql('temp_company', DB_NAME_SUCCESS, "SELECT event_time FROM events")

        # Assert
        self.util_mock.serialize.assert_called_once_with(original_datetime)
        expected_json = json.dumps([{'event_time': original_datetime.isoformat()}])
        assert result_json == expected_json

    def test_exec_sql_raises_exception_for_unregistered_database(self):
        """
        GIVEN an unregistered database name
        WHEN exec_sql is called
        THEN it should raise an IAToolkitException.
        """
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.exec_sql('temp_company', DB_NAME_UNREGISTERED, "SELECT 1")

        assert f"Database '{DB_NAME_UNREGISTERED}' is not registered" in str(exc_info.value)

    @patch('iatoolkit.services.sql_service.DatabaseManager')
    def test_exec_sql_handles_db_execution_error(self, MockDatabaseManager):
        """
        GIVEN a registered database
        WHEN the execution of the SQL statement fails
        THEN it should raise an IAToolkitException and attempt a rollback.
        """
        # Arrange
        mock_db_manager = MockDatabaseManager.return_value
        session_mock = mock_db_manager.get_session.return_value
        db_error = Exception("Table not found")
        session_mock.execute.side_effect = db_error

        self.service.register_database(DUMMY_URI, DB_NAME_SUCCESS)

        # Act & Assert
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.exec_sql('temp_company', DB_NAME_SUCCESS, "SELECT * FROM non_existent_table")

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert str(db_error) in str(exc_info.value)
        # Verify rollback was attempted
        session_mock.rollback.assert_called_once()