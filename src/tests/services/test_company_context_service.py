# tests/services/test_company_context_service.py

import pytest
from unittest.mock import MagicMock, patch, call
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.asset_storage import AssetRepository, AssetType
from iatoolkit.services.sql_service import SqlService
from iatoolkit.common.util import Utility
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.exceptions import IAToolkitException

# --- Mock Data for different test scenarios ---

# Simulates include_all_tables: true
MOCK_CONFIG_INCLUDE_ALL = {
    'sql': [{
        'database': 'main_db',
        'include_all_tables': True
    }]
}

# Simulates an explicit list of tables
MOCK_CONFIG_EXPLICIT_LIST = {
    'sql': [{
        'database': 'main_db',
        'tables': {
            'products': {},
            'customers': {}
        }
    }]
}

# Simulates include_all_tables with exclusions and overrides
MOCK_CONFIG_COMPLEX = {
    'sql': [{
        'database': 'main_db',
        'include_all_tables': True,
        'exclude_tables': ['logs'],
        'exclude_columns': ['id', 'created_at'],  # Global exclude
        'tables': {
            'users': {
                'exclude_columns': ['password_hash']  # Local override
            },
            'user_profiles': {
                'schema_name': 'profiles'  # Schema override
            }
        }
    }]
}


class TestCompanyContextService:
    """
    Unit tests for the CompanyContextService, updated for the new data_sources schema.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up mocks for all dependencies and instantiate the service."""
        self.mock_sql_service = MagicMock(spec=SqlService)
        self.mock_utility = MagicMock(spec=Utility)
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_asset_repo = MagicMock(spec=AssetRepository) # <--- Mock Repo

        # Setup a default mock for the DatabaseManager
        self.mock_db_manager = MagicMock(spec=DatabaseManager)
        self.mock_db_manager.schema = 'public'
        self.mock_sql_service.get_database_manager.return_value = self.mock_db_manager

        self.context_service = CompanyContextService(
            sql_service=self.mock_sql_service,
            utility=self.mock_utility,
            config_service=self.mock_config_service,
            asset_repo=self.mock_asset_repo
        )
        self.COMPANY_NAME = 'acme'

    # --- Tests for New SQL Context Logic ---

    def test_sql_context_with_include_all_tables(self):
        """
        GIVEN config has 'include_all_tables: true'
        WHEN _get_sql_schema_context is called
        THEN it should process all tables returned by the db_manager.
        """
        # Arrange
        self.mock_config_service.get_configuration.return_value = MOCK_CONFIG_INCLUDE_ALL
        self.mock_db_manager.get_all_table_names.return_value = ['users', 'products']
        self.mock_db_manager.schema = 'public'

        # Act
        self.context_service._get_sql_schema_context(self.COMPANY_NAME)

        # Assert
        self.mock_db_manager.get_all_table_names.assert_called_once()
        expected_calls = [
            call(table_name='users', db_schema='public', schema_object_name='users', exclude_columns=[]),
            call(table_name='products', db_schema='public', schema_object_name='products', exclude_columns=[])
        ]
        self.mock_db_manager.get_table_schema.assert_has_calls(expected_calls, any_order=True)

    def test_sql_context_with_explicit_table_map(self):
        """
        GIVEN config has an explicit map of tables
        WHEN _get_sql_schema_context is called
        THEN it should only process tables listed in the map.
        """
        # Arrange
        self.mock_config_service.get_configuration.return_value = MOCK_CONFIG_EXPLICIT_LIST

        # Act
        self.context_service._get_sql_schema_context(self.COMPANY_NAME)

        # Assert
        self.mock_db_manager.get_all_table_names.assert_not_called()
        assert self.mock_db_manager.get_table_schema.call_count == 2
        expected_calls = [
            call(table_name='products', db_schema='public', schema_object_name='products', exclude_columns=[]),
            call(table_name='customers', db_schema='public', schema_object_name='customers', exclude_columns=[])
        ]
        self.mock_db_manager.get_table_schema.assert_has_calls(expected_calls, any_order=True)

    def test_sql_context_with_complex_overrides(self):
        """
        GIVEN a complex config with include_all, exclusions, and overrides
        WHEN _get_sql_schema_context is called
        THEN it should apply all rules correctly.
        """
        # Arrange
        self.mock_config_service.get_configuration.return_value = MOCK_CONFIG_COMPLEX
        # DB has 'users', 'user_profiles', and 'logs'. 'logs' should be excluded.
        self.mock_db_manager.get_all_table_names.return_value = ['users', 'user_profiles', 'logs']

        # Act
        self.context_service._get_sql_schema_context(self.COMPANY_NAME)

        # Assert
        # Check call count first
        assert self.mock_db_manager.get_table_schema.call_count == 2

        # Check calls with correct, final parameters
        expected_calls = [
            # 'users' table should use its local exclude_columns override
            call(table_name='users', db_schema='public',  schema_object_name='users', exclude_columns=['password_hash']),
            # 'user_profiles' should use the global exclude_columns and its local schema_object_name override
            call(table_name='user_profiles', db_schema='public', schema_object_name='profiles', exclude_columns=['id', 'created_at'])
        ]
        self.mock_db_manager.get_table_schema.assert_has_calls(expected_calls, any_order=True)

    # --- Existing Tests (can be kept as they test other parts) ---

    def test_build_context_with_only_static_files(self):
        """
        GIVEN only static markdown files provide context in the repo
        WHEN get_company_context is called
        THEN it should return only the markdown context.
        """
        # Arrange
        # 1. Mock Markdown files
        self.mock_asset_repo.list_files.side_effect = lambda company, asset_type, extension: \
            ['info.md'] if asset_type == AssetType.CONTEXT else []

        self.mock_asset_repo.read_text.return_value = "STATIC_INFO"

        # 2. No SQL config
        self.mock_config_service.get_configuration.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert "STATIC_INFO" in full_context

        # Verify repository calls
        self.mock_asset_repo.list_files.assert_any_call(self.COMPANY_NAME, AssetType.CONTEXT, extension='.md')
        self.mock_asset_repo.read_text.assert_any_call(self.COMPANY_NAME, AssetType.CONTEXT, 'info.md')

        # Verify SQL service was NOT called
        self.mock_sql_service.get_database_manager.assert_not_called()

    def test_build_context_with_yaml_schemas(self):
        """
        GIVEN yaml schema files in the repo
        WHEN get_company_context is called
        THEN it should parse them and include them in context.
        """

        # Arrange
        # 1. Mock YAML files
        def list_files_side_effect(company, asset_type, extension):
            if asset_type == AssetType.SCHEMA: return ['orders.yaml']
            return []

        self.mock_asset_repo.list_files.side_effect = list_files_side_effect

        # 2. Mock Content and Parsing
        self.mock_asset_repo.read_text.return_value = "yaml_content"
        self.mock_utility.load_yaml_from_string.return_value = {"orders": {"description": "Order table"}}
        self.mock_utility.generate_schema_table.return_value = "Parsed Order Schema"

        # 3. No SQL config
        self.mock_config_service.get_configuration.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert "Parsed Order Schema" in full_context

        # Verify flow
        self.mock_asset_repo.read_text.assert_called_with(self.COMPANY_NAME, AssetType.SCHEMA, 'orders.yaml')
        self.mock_utility.load_yaml_from_string.assert_called_with("yaml_content")
        self.mock_utility.generate_schema_table.assert_called_with({"orders": {"description": "Order table"}})

    def test_gracefully_handles_repo_exceptions(self):
        """
        GIVEN the repository raises an exception when listing/reading
        WHEN get_company_context is called
        THEN it should log warnings but continue (return empty strings for those parts).
        """
        # Arrange
        self.mock_asset_repo.list_files.side_effect = Exception("Repo Down")
        self.mock_config_service.get_configuration.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == ""  # Should result in empty string, not crash

    def test_gracefully_handles_db_manager_exception(self):
        """
        GIVEN retrieving a database manager throws an exception
        WHEN get_company_context is called
        THEN it should log a warning and return context from other sources.
        """
        # Arrange
        self.mock_utility.get_files_by_extension.return_value = []  # No static context
        self.mock_config_service.get_configuration.return_value = {'sql': [{'database': 'down_db'}]}
        self.mock_sql_service.get_database_manager.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.DATABASE_ERROR, "DB is down"
        )

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == ""
        self.mock_sql_service.get_database_manager.assert_called_once_with(self.COMPANY_NAME, 'down_db')