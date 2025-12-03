# tests/services/test_configuration_services.py

import pytest
from unittest.mock import Mock, patch, call
from pathlib import Path

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.base_company import BaseCompany
from iatoolkit.repositories.models import Company, PromptCategory
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo

# A complete and valid mock configuration, passing all validation rules.
MOCK_VALID_CONFIG = {
    'id': 'acme',
    'name': 'ACME Corp',
    'locale': 'en_US',
    'llm': {
        'model': 'gpt-5-test',
        'api-key': 'TEST_OPENAI_API_KEY'
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

        self.mock_company_instance = Mock(spec=BaseCompany)
        self.mock_company = Company(id=1, short_name='ACME')
        self.profile_repo.create_company.return_value = self.mock_company
        self.mock_company_instance.company = self.mock_company

        self.service = ConfigurationService(utility=self.mock_utility,
                                            llm_query_repo=self.mock_llm_query_repo,
                                            profile_repo=self.profile_repo)
        self.COMPANY_NAME = 'acme'

    @patch('iatoolkit.current_iatoolkit')
    @patch('pathlib.Path.is_file', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_configuration_happy_path(self, mock_exists, mock_is_file, mock_current_iatoolkit):
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
            if "SqlService" in str(service_class):  # Nuevo caso
                return mock_sql_service
            return Mock()

        mock_injector.get.side_effect = get_side_effect

        # --- Arrange Config Loading ---
        def yaml_side_effect(path):
            if "company.yaml" in str(path):
                return MOCK_VALID_CONFIG
            if "onboarding.yaml" in str(path):
                return MOCK_ONBOARDING_CONFIG
            return {}

        self.mock_utility.load_schema_from_yaml.side_effect = yaml_side_effect

        # --- Act ---
        self.service.load_configuration(self.COMPANY_NAME, self.mock_company_instance)

        # --- Assert ---

        # 2. Verify ToolService delegation
        mock_tool_service.sync_company_tools.assert_called_once_with(
            self.mock_company_instance,
            MOCK_VALID_CONFIG['tools']
        )

        # 3. Verify PromptService delegation
        mock_prompt_service.sync_company_prompts.assert_called_once_with(
            company_instance=self.mock_company_instance,
            prompts_config=MOCK_VALID_CONFIG['prompts'],
            categories_config=MOCK_VALID_CONFIG['prompt_categories']
        )

        # 4. Verify final attributes set
        assert self.mock_company_instance.company_short_name == self.COMPANY_NAME
        assert self.mock_company_instance.company == self.mock_company

    @patch('pathlib.Path.is_file', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_get_configuration_uses_cache_on_second_call(self, mock_path_exists, mock_is_file):
        """
        GIVEN configuration loaded from files
        WHEN get_configuration is called multiple times
        THEN file-reading logic executes only on the first call.
        """

        def yaml_side_effect(path):
            if "company.yaml" in str(path):
                return MOCK_VALID_CONFIG
            return MOCK_ONBOARDING_CONFIG

        self.mock_utility.load_schema_from_yaml.side_effect = yaml_side_effect

        # First Call
        result1 = self.service.get_configuration(self.COMPANY_NAME, 'name')
        assert result1 == 'ACME Corp'
        assert self.mock_utility.load_schema_from_yaml.call_count == 2

        # Second Call
        result2 = self.service.get_configuration(self.COMPANY_NAME, 'id')
        assert result2 == 'acme'
        assert self.mock_utility.load_schema_from_yaml.call_count == 2

    @patch('pathlib.Path.exists', return_value=False)
    def test_load_configuration_raises_file_not_found(self, mock_exists):
        with pytest.raises(FileNotFoundError):
            self.service.load_configuration(self.COMPANY_NAME, self.mock_company_instance)

    @patch('iatoolkit.current_iatoolkit')
    @patch('pathlib.Path.is_file', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_configuration_handles_empty_sections(self, mock_exists, mock_is_file, mock_current_iatoolkit):
        """
        GIVEN missing optional sections (tools, prompts)
        WHEN load_configuration is called
        THEN it delegates empty lists to services.
        """
        # Mocks setup
        mock_injector = Mock()
        mock_current_iatoolkit.return_value.get_injector.return_value = mock_injector
        mock_tool_service = Mock()
        mock_prompt_service = Mock()
        mock_injector.get.side_effect = lambda cls: mock_tool_service if "ToolService" in str(
            cls) else mock_prompt_service

        # Minimal config
        minimal_config = {
            'id': 'minimal_co',
            'name': 'Minimal Co',
            'llm': {'model': 'test', 'api-key': 'TEST'},
            'embedding_provider': {'provider': 'test', 'model': 'test', 'api_key_name': 'TEST'}
        }
        self.mock_utility.load_schema_from_yaml.return_value = minimal_config

        # Act
        self.service.load_configuration('minimal_co', self.mock_company_instance)

        # Assert
        mock_tool_service.sync_company_tools.assert_called_once_with(self.mock_company_instance, [])
        mock_prompt_service.sync_company_prompts.assert_called_once_with(
            company_instance=self.mock_company_instance,
            prompts_config=[],
            categories_config=[]
        )

    def test_validation_failure_raises_exception(self):
        # Arrange invalid config
        invalid_config = {'id': self.COMPANY_NAME, 'name': 'Invalid Co'}
        self.mock_utility.load_schema_from_yaml.return_value = invalid_config

        with patch('pathlib.Path.exists', return_value=True):
            with pytest.raises(IAToolkitException) as excinfo:
                self.service.load_configuration(self.COMPANY_NAME, self.mock_company_instance)

            assert excinfo.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR

    @patch('iatoolkit.current_iatoolkit')
    @patch('pathlib.Path.is_file', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_configuration_service_exception_propagates(self, mock_exists, mock_is_file, mock_current_iatoolkit):
        """
        GIVEN ToolService raises an exception
        WHEN load_configuration is called
        THEN it propagates the exception (ConfigService doesn't catch it).
        """
        # Setup Mocks
        mock_injector = Mock()
        mock_current_iatoolkit.return_value.get_injector.return_value = mock_injector
        mock_tool_service = Mock()
        mock_injector.get.return_value = mock_tool_service

        self.mock_utility.load_schema_from_yaml.return_value = MOCK_VALID_CONFIG

        # Simulate error in ToolService
        mock_tool_service.sync_company_tools.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.DATABASE_ERROR, "DB Error"
        )

        # Act & Assert
        with pytest.raises(IAToolkitException) as excinfo:
            self.service.load_configuration('acme', self.mock_company_instance)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert "DB Error" in str(excinfo.value)