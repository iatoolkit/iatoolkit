# tests/services/test_configuration_services.py

import pytest
from unittest.mock import Mock, patch, call
import copy

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.common.util import Utility
from iatoolkit.base_company import BaseCompany
from iatoolkit.repositories.models import Company
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo

# A complete and valid mock configuration, passing all validation rules.
MOCK_VALID_CONFIG = {
    'id': 'acme',
    'name': 'ACME Corp',
    'locale': 'en_US',
    'llm': {
        'model': 'gpt-5',
        'provider_api_keys': {'openai': 'TEST_OPENAI_API_KEY'}
    },
    'embedding_provider': {
        'provider': 'openai',
        'model': 'text-embedding-test',
        'api_key_name': 'TEST_OPENAI_API_KEY'
    },
    'data_sources': {
        'sql': [{
            'database': 'test_db',
            'connection_string_env': 'TEST_DB_URI',
            'schema': 'sample_db'
        }]
    },
    'tools': [{
        'function_name': 'get_stock',
        'description': 'Gets stock price',
        'params': {'type': 'object'}
    }],
    'prompt_categories': ['General'],
    'prompts': [{
        'category': 'General',
        'name': 'sales_report',
        'description': 'Generates a sales report',
        'order': 1
    }],
    'parameters': {
        'cors_origin': ['https://acme.com'],
        'user_feedback': {
            'channel': 'email',
            'destination': 'feedback@acme.com'
        }
    },
    'mail_provider': {
        'provider': 'brevo_mail',
        'sender_email': 'no-reply@acme.com',
        'sender_name': 'ACME IA',
        'brevo_mail': {'brevo_api': 'TEST_BREVO_API'}
    },
    'help_files': {
        'onboarding_cards': 'onboarding.yaml'
    },
    'knowledge_base': {
        'connectors': {
            'production': {
                'type': 's3',
                'bucket': 'test-bucket',
                'prefix': 'test-prefix',
                'aws_access_key_id_env': 'TEST_AWS_ID',
                'aws_secret_access_key_env': 'TEST_AWS_KEY',
                'aws_region_env': 'TEST_AWS_REGION'
            }
        }
    }
}

# Simula el contenido de onboarding.yaml
MOCK_ONBOARDING_CONFIG = [
    {'icon': 'fas fa-rocket', 'title': 'Welcome!'}
]


class TestConfigurationService:
    """
    Unit tests for the ConfigurationService.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """
        Pytest fixture that runs before each test to create mocks for all dependencies
        and instantiate the ConfigurationService.
        """
        self.mock_utility = Mock(spec=Utility)
        self.mock_llm_query_repo = Mock(spec=LLMQueryRepo)
        self.profile_repo = Mock(spec=ProfileRepo)
        self.mock_asset_repo = Mock(spec=AssetRepository)

        self.mock_company_instance = Mock(spec=BaseCompany)
        self.mock_company = Company(id=1, short_name='ACME')
        self.profile_repo.create_company.return_value = self.mock_company
        self.mock_company_instance.company = self.mock_company

        self.service = ConfigurationService(utility=self.mock_utility,
                                            llm_query_repo=self.mock_llm_query_repo,
                                            profile_repo=self.profile_repo,
                                            asset_repo=self.mock_asset_repo)
        self.COMPANY_NAME = 'acme'

    @patch('iatoolkit.current_iatoolkit')
    def test_load_configuration_happy_path(self, mock_current_iatoolkit):
        """
        GIVEN a valid configuration
        WHEN load_configuration is called
        THEN it should delegate creation to ToolService and PromptService via lazy loading.
        """
        # --- Mock Lazy Loading of Services ---
        mock_injector = Mock()
        mock_current_iatoolkit.return_value.get_injector.return_value = mock_injector

        mock_tool_service = Mock()
        mock_prompt_service = Mock()
        mock_sql_service = Mock()

        # Simulate injector.get returning correct service based on requested class
        def get_side_effect(service_class):
            if "ToolService" in str(service_class):
                return mock_tool_service
            if "PromptService" in str(service_class):
                return mock_prompt_service
            if "SqlService" in str(service_class):
                return mock_sql_service
            return Mock()
        mock_injector.get.side_effect = get_side_effect

        # 1. Simular existencia de archivos
        self.mock_asset_repo.exists.return_value = True

        # 2. Simular contenido de archivos (texto)
        self.mock_asset_repo.read_text.return_value = "yaml content"

        # 3. Simular el parser de Utility
        def read_text_side_effect(company, asset_type, filename):
            if filename == "company.yaml": return "company_yaml_content"
            if filename == "onboarding.yaml": return "onboarding_yaml_content"
            return ""

        self.mock_asset_repo.read_text.side_effect = read_text_side_effect

        def load_yaml_side_effect(content):
            if content == "company_yaml_content": return MOCK_VALID_CONFIG
            if content == "onboarding_yaml_content": return MOCK_ONBOARDING_CONFIG
            return {}

        self.mock_utility.load_yaml_from_string.side_effect = load_yaml_side_effect

        # --- Act ---
        self.service.load_configuration(self.COMPANY_NAME)

        # --- Assert ---
        # Validar llamadas al repo
        self.mock_asset_repo.exists.assert_any_call(self.COMPANY_NAME, AssetType.CONFIG, "company.yaml")
        self.mock_asset_repo.read_text.assert_any_call(self.COMPANY_NAME, AssetType.CONFIG, "company.yaml")

        # Validar validación de prompts (el paso final)
        self.mock_asset_repo.exists.assert_any_call(self.COMPANY_NAME, AssetType.PROMPT, "sales_report.prompt")

        # 2. Verify ToolService delegation
        mock_tool_service.sync_company_tools.assert_called_once_with(
            self.COMPANY_NAME,
            MOCK_VALID_CONFIG['tools']
        )

        # 3. Verify PromptService delegation
        mock_prompt_service.sync_company_prompts.assert_called_once_with(
            company_short_name=self.COMPANY_NAME,
            prompts_config=MOCK_VALID_CONFIG['prompts'],
            categories_config=MOCK_VALID_CONFIG['prompt_categories']
        )

    def test_get_configuration_uses_cache_on_second_call(self):
        """
        GIVEN configuration loaded from files
        WHEN get_configuration is called multiple times
        THEN file-reading logic executes only on the first call.
        """
        # Setup mocks
        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = MOCK_VALID_CONFIG

        # First Call
        result1 = self.service.get_configuration(self.COMPANY_NAME, 'name')
        assert result1 == 'ACME Corp'
        assert self.mock_asset_repo.read_text.call_count >= 1

        # Reset counts
        self.mock_asset_repo.read_text.reset_mock()

        # Second Call
        result2 = self.service.get_configuration(self.COMPANY_NAME, 'id')
        assert result2 == 'acme'

        # Verify NO calls to repo (cache used)
        self.mock_asset_repo.read_text.assert_not_called()

    @patch('iatoolkit.current_iatoolkit')
    def test_load_configuration_handles_empty_sections(self, mock_current_iatoolkit):
        """
        GIVEN missing optional sections (tools, prompts) in the config file
        WHEN load_configuration is called
        THEN it delegates empty lists to services without errors.
        """
        # --- Mocks setup ---
        mock_injector = Mock()
        mock_current_iatoolkit.return_value.get_injector.return_value = mock_injector

        mock_tool_service = Mock()
        mock_prompt_service = Mock()
        mock_sql_service = Mock()

        def get_side_effect(service_class):
            if "ToolService" in str(service_class):
                return mock_tool_service
            if "PromptService" in str(service_class):
                return mock_prompt_service
            if "SqlService" in str(service_class):
                return mock_sql_service
            return Mock()

        mock_injector.get.side_effect = get_side_effect

        # --- Arrange Minimal Config ---
        minimal_config = {
            'id': 'minimal_co',
            'name': 'Minimal Co',
            'llm': {
                'model': 'test',
                'provider_api_keys': {'openai': 'dummy'}
            },
            'embedding_provider': {
                'provider': 'test',
                'model': 'test',
                'api_key_name': 'TEST'
            },
        }

        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml_content"
        self.mock_utility.load_yaml_from_string.return_value = minimal_config

        # --- Act ---
        self.service.load_configuration('minimal_co')

        # --- Assert ---
        mock_tool_service.sync_company_tools.assert_called_once_with('minimal_co', [])
        mock_prompt_service.sync_company_prompts.assert_called_once_with(
            company_short_name='minimal_co',
            prompts_config=[],
            categories_config=[]
        )

    # --- New Tests for Update and Validation ---

    def test_update_configuration_key_success(self):
        """
        GIVEN a valid update for a configuration key
        WHEN update_configuration_key is called
        THEN it should update the config, dump it to string, and write to asset repo.
        """
        # Arrange
        # 1. Configuración inicial válida (Deep copy para evitar efectos secundarios)
        initial_config = copy.deepcopy(MOCK_VALID_CONFIG)

        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "original_yaml"
        self.mock_utility.load_yaml_from_string.return_value = initial_config
        self.mock_utility.dump_yaml_to_string.return_value = "updated_yaml"

        # Pre-fill cache to verify invalidation
        self.service._loaded_configs[self.COMPANY_NAME] = initial_config

        # Act
        # Update nested key 'llm.model'
        updated_config, errors = self.service.update_configuration_key(self.COMPANY_NAME, "llm.model", "gpt-6")

        # Assert
        assert errors == []
        assert updated_config['llm']['model'] == 'gpt-6'

        # Verify writing back to repo
        self.mock_asset_repo.write_text.assert_called_once_with(
            self.COMPANY_NAME, AssetType.CONFIG, "company.yaml", "updated_yaml"
        )

        # Verify utility calls
        self.mock_utility.load_yaml_from_string.assert_called()
        # Ensure dump was called with the modified config object
        self.mock_utility.dump_yaml_to_string.assert_called()
        args, _ = self.mock_utility.dump_yaml_to_string.call_args
        assert args[0]['llm']['model'] == 'gpt-6'

        # Verify cache invalidation
        assert self.COMPANY_NAME not in self.service._loaded_configs

    def test_update_configuration_key_list_index(self):
        """
        GIVEN a configuration with a list
        WHEN update_configuration_key is called with an index path (e.g. tools.0.description)
        THEN it should update the correct item in the list.
        """
        # Arrange
        initial_config = copy.deepcopy(MOCK_VALID_CONFIG)
        # Ensure we have a list to test against with all required fields (params is required by validation)
        initial_config['tools'] = [
            {'function_name': 'func1', 'description': 'old desc', 'params': {}},
            {'function_name': 'func2', 'description': 'another desc', 'params': {}}
        ]

        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = initial_config
        self.mock_utility.dump_yaml_to_string.return_value = "new_yaml"

        # Act
        updated_config, errors = self.service.update_configuration_key(
            self.COMPANY_NAME,
            "tools.0.description",
            "new description"
        )

        # Assert
        assert errors == []
        assert updated_config['tools'][0]['description'] == "new description"
        assert updated_config['tools'][1]['description'] == "another desc"  # Should remain untouched

    def test_update_configuration_key_invalid_list_index(self):
        """
        GIVEN a list path with invalid index
        WHEN update_configuration_key is called
        THEN it should raise an exception (ValueError).
        """
        initial_config = {'my_list': ['a', 'b']}

        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = initial_config

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid path"):
            self.service.update_configuration_key(self.COMPANY_NAME, "my_list.99", "val")

    def test_add_configuration_key_success(self):
        """
        GIVEN a valid request to add a configuration key under a section
        WHEN add_configuration_key is called
        THEN it should update the config, save it to repo, and invalidate cache.
        """
        # Arrange
        initial_config = copy.deepcopy(MOCK_VALID_CONFIG)

        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "original_yaml"
        self.mock_utility.load_yaml_from_string.return_value = initial_config
        self.mock_utility.dump_yaml_to_string.return_value = "updated_yaml"

        # Pre-fill cache to verify invalidation later
        self.service._loaded_configs[self.COMPANY_NAME] = initial_config

        # Act
        # Add 'max_tokens' under 'llm'
        updated_config, errors = self.service.add_configuration_key(
            self.COMPANY_NAME, "llm", "max_tokens", 2048
        )

        # Assert
        assert errors == []
        assert updated_config['llm']['max_tokens'] == 2048

        # Verify writing back to repo
        self.mock_asset_repo.write_text.assert_called_once_with(
            self.COMPANY_NAME, AssetType.CONFIG, "company.yaml", "updated_yaml"
        )

        # Verify utility dump call
        args, _ = self.mock_utility.dump_yaml_to_string.call_args
        assert args[0]['llm']['max_tokens'] == 2048

        # Verify cache invalidation
        assert self.COMPANY_NAME not in self.service._loaded_configs

    def test_add_configuration_key_root_level(self):
        """
        GIVEN a request to add a key at root level (empty parent_key)
        WHEN add_configuration_key is called
        THEN it should add the key at the top level of the config.
        """
        # Arrange
        initial_config = copy.deepcopy(MOCK_VALID_CONFIG)
        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = initial_config
        self.mock_utility.dump_yaml_to_string.return_value = "new_yaml"

        # Act
        updated_config, errors = self.service.add_configuration_key(
            self.COMPANY_NAME, "", "new_root_feature", True
        )

        # Assert
        assert errors == []
        assert updated_config["new_root_feature"] is True
        self.mock_asset_repo.write_text.assert_called_once()

    def test_add_configuration_key_validation_failure(self):
        """
        GIVEN a change that creates an invalid configuration state
        WHEN add_configuration_key is called
        THEN it should return errors and NOT save to the repository.
        """
        # Arrange
        initial_config = copy.deepcopy(MOCK_VALID_CONFIG)
        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = initial_config

        # Act
        # We try to 'add' (overwrite) a required key with an invalid value
        updated_config, errors = self.service.add_configuration_key(
            self.COMPANY_NAME, "llm", "model", ""
        )

        # Assert
        assert len(errors) > 0
        assert any("Missing required key: 'model'" in e for e in errors)

        # Verify NO write happened
        self.mock_asset_repo.write_text.assert_not_called()

    def test_validate_configuration_success(self):
        """
        GIVEN a valid configuration file
        WHEN validate_configuration is called
        THEN it should return an empty list of errors.
        """
        # Arrange
        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        # Importante: usar deepcopy aquí también
        self.mock_utility.load_yaml_from_string.return_value = copy.deepcopy(MOCK_VALID_CONFIG)

        # Act
        errors = self.service.validate_configuration(self.COMPANY_NAME)

        # Assert
        assert errors == []

    def test_validate_configuration_with_errors(self):
        """
        GIVEN an invalid configuration file
        WHEN validate_configuration is called
        THEN it should return a list of validation errors.
        """
        # Arrange
        invalid_config = copy.deepcopy(MOCK_VALID_CONFIG)
        del invalid_config['name'] # Remove required field

        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = invalid_config

        # Act
        errors = self.service.validate_configuration(self.COMPANY_NAME)

        # Assert
        assert len(errors) > 0
        assert any("Missing required key: 'name'" in e for e in errors)