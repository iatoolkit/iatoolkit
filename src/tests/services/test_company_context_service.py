# tests/services/test_company_context_service.py

import pytest
from unittest.mock import MagicMock, patch, call
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.common.util import Utility
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.exceptions import IAToolkitException


class TestCompanyContextService:
    """
    Unit tests for the CompanyContextService.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """
        Pytest fixture that runs before each test to create mocks for all dependencies
        and instantiate the CompanyContextService.
        """
        self.mock_sql_service = MagicMock(spec=SqlService)
        self.mock_utility = MagicMock(spec=Utility)
        self.mock_config_service = MagicMock(spec=ConfigurationService)

        self.context_service = CompanyContextService(
            sql_service=self.mock_sql_service,
            utility=self.mock_utility,
            config_service=self.mock_config_service
        )
        self.COMPANY_NAME = 'acme'

    @patch('os.path.exists', return_value=True)
    def test_build_full_context_with_all_sources(self, mock_exists):
        """
        GIVEN all context sources (markdown, yaml schemas, sql) are available
        WHEN build_full_context is called
        THEN it should return a combined string of all contexts separated by '---'.
        """

        # --- Arrange ---
        # 1. Mock static file context (markdown and yaml schemas)
        def get_files_side_effect(directory, ext, **kwargs):
            if 'context' in directory and ext == '.md':
                return ['rules.md']
            if 'schema' in directory and ext == '.yaml':
                return ['api.yaml']
            return []

        self.mock_utility.get_files_by_extension.side_effect = get_files_side_effect
        self.mock_utility.load_markdown_context.return_value = "MARKDOWN_CONTEXT"
        self.mock_utility.generate_context_for_schema.return_value = "YAML_SCHEMA_CONTEXT"

        # 2. Mock SQL context
        mock_db_config = {
            'sql': [{
                'database': 'main_db',
                'description': 'Main database.',
                'tables': [{'table_name': 'users'}]
            }]
        }
        self.mock_config_service.get_company_content.return_value = mock_db_config
        mock_db_manager = MagicMock(spec=DatabaseManager)
        mock_db_manager.get_table_schema.return_value = "SQL_TABLE_SCHEMA"
        self.mock_sql_service.get_database_manager.return_value = mock_db_manager

        # --- Act ---
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # --- Assert ---
        # Check that the final string is correctly assembled
        expected_static_context = "MARKDOWN_CONTEXTYAML_SCHEMA_CONTEXT"
        expected_sql_context = "Main database.\nSQL_TABLE_SCHEMA"
        assert full_context == f"{expected_static_context}\n\n---\n\n{expected_sql_context}"

        # Verify calls for static context

        self.mock_utility.load_markdown_context.assert_called_once()
        self.mock_utility.generate_context_for_schema.assert_called_once()

        # Verify calls for SQL context
        self.mock_config_service.get_company_content.assert_called_once_with(self.COMPANY_NAME, 'data_sources')
        self.mock_sql_service.get_database_manager.assert_called_once_with('main_db')
        mock_db_manager.get_table_schema.assert_called_once_with(table_name='users', schema_name='users',
                                                                 exclude_columns=[])

    def test_build_context_with_only_sql_source(self):
        """
        GIVEN only SQL sources provide context
        WHEN build_full_context is called
        THEN it should return only the SQL context without separators.
        """
        # Arrange: No static files found
        self.mock_utility.get_files_by_extension.return_value = []

        # Arrange: SQL context is available
        mock_db_config = {'sql': [{'database': 'main_db', 'tables': [{'table_name': 'products'}]}]}
        self.mock_config_service.get_company_content.return_value = mock_db_config
        mock_db_manager = MagicMock()
        mock_db_manager.get_table_schema.return_value = "PRODUCTS_SCHEMA"
        self.mock_sql_service.get_database_manager.return_value = mock_db_manager

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == "PRODUCTS_SCHEMA"
        self.mock_utility.load_markdown_context.assert_not_called()

    @patch('os.path.exists')
    def test_build_context_with_only_static_files(self, mock_exists):
        """
        GIVEN only static markdown files provide context
        WHEN build_full_context is called
        THEN it should return only the markdown context.
        """

        # Arrange: Configure the mock to simulate that the 'context' directory
        # exists, but the 'schema' directory does not.
        def exists_side_effect(path):
            if 'context' in path:
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        # Arrange: Utility will find one markdown file.
        self.mock_utility.get_files_by_extension.return_value = ['info.md']
        self.mock_utility.load_markdown_context.return_value = "STATIC_INFO"

        # Arrange: No SQL data_sources are configured for this test.
        self.mock_config_service.get_company_content.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == "STATIC_INFO"

        # Verify that the correct calls were made
        self.mock_utility.get_files_by_extension.assert_called_once_with(
            f'companies/{self.COMPANY_NAME}/context', '.md', return_extension=True
        )
        self.mock_utility.load_markdown_context.assert_called_once()
        self.mock_sql_service.get_database_manager.assert_not_called()


    def test_build_context_when_no_sources_are_available(self):
        """
        GIVEN no context sources are configured or found
        WHEN build_full_context is called
        THEN it should return an empty string.
        """
        # Arrange
        self.mock_utility.get_files_by_extension.return_value = []
        self.mock_config_service.get_company_content.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == ""

    def test_gracefully_handles_db_manager_exception(self):
        """
        GIVEN retrieving a database manager throws an exception
        WHEN build_full_context is called
        THEN it should log a warning and return context from other sources.
        """
        # Arrange
        self.mock_utility.get_files_by_extension.return_value = []  # No static context
        mock_db_config = {'sql': [{'database': 'down_db'}]}
        self.mock_config_service.get_company_content.return_value = mock_db_config
        self.mock_sql_service.get_database_manager.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.DATABASE_ERROR, "DB is down"
        )

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        # The service should fail gracefully and return an empty string as there are no other sources.
        assert full_context == ""
        self.mock_sql_service.get_database_manager.assert_called_once_with('down_db')
