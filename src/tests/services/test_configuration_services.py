# tests/services/test_configuration_services.py

import pytest
from unittest.mock import Mock, patch, call
from pathlib import Path

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit import BaseCompany
from iatoolkit.repositories.models import Company, PromptCategory
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.database_manager import DatabaseManager

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
            'connection_string_env': 'TEST_DB_URI'
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
        self.mock_database_manager = Mock(spec=DatabaseManager)

        self.mock_company_instance = Mock(spec=BaseCompany)
        self.mock_company = Company(id=1, short_name='ACME')
        self.mock_company_instance._create_company.return_value = self.mock_company
        self.mock_company_instance._create_prompt_category.return_value = Mock(spec=PromptCategory)
        self.mock_company_instance.company = self.mock_company

        self.service = ConfigurationService(utility=self.mock_utility,
                                            db_manager=self.mock_database_manager,
                                            llm_query_repo=self.mock_llm_query_repo)
        self.COMPANY_NAME = 'acme'

    @patch('pathlib.Path.is_file', return_value=True)  # For _validate_configuration
    @patch('pathlib.Path.exists', return_value=True)  # For _load_and_merge_configs
    def test_load_configuration_happy_path(self, mock_exists, mock_is_file):
        """
        GIVEN a valid and complete configuration
        WHEN load_configuration is called
        THEN it should succeed and call all registration methods correctly.
        """

        # Arrange
        def yaml_side_effect(path):
            if "company.yaml" in str(path):
                return MOCK_VALID_CONFIG
            if "onboarding.yaml" in str(path):
                return MOCK_ONBOARDING_CONFIG
            return {}

        self.mock_utility.load_schema_from_yaml.side_effect = yaml_side_effect

        # Act
        self.service.load_configuration(self.COMPANY_NAME, self.mock_company_instance)

        # Assert
        # 1. Verify core details were registered
        self.mock_company_instance._create_company.assert_called_once_with(
            short_name='acme',
            name='ACME Corp',
            parameters=MOCK_VALID_CONFIG['parameters']
        )

        # 2. Verify tools were registered
        self.mock_company_instance._create_function.assert_called_once_with(
            function_name='get_stock',
            description='Gets stock price',
            params={'type': 'object'}
        )

        # 3. Verify prompts were registered
        self.mock_company_instance._create_prompt_category.assert_called_once_with(name='General', order=1)
        self.mock_company_instance._create_prompt.assert_called_once_with(
            prompt_name='sales_report',
            description='Generates a sales report',
            order=1,
            category=self.mock_company_instance._create_prompt_category.return_value,
            active=True,
            custom_fields=[]
        )

        # 4. Verify final attributes were set on the instance
        assert self.mock_company_instance.company_short_name == self.COMPANY_NAME
        assert self.mock_company_instance.company == self.mock_company

    @patch('pathlib.Path.is_file', return_value=True)  # Needed for validation if it were called
    @patch('pathlib.Path.exists', return_value=True)
    def test_get_configuration_uses_cache_on_second_call(self, mock_path_exists, mock_is_file):
        """
        GIVEN a configuration that needs to be loaded from files,
        WHEN get_configuration is called multiple times for the same company,
        THEN the file-reading logic should only be executed on the first call.
        """

        # Arrange
        def yaml_side_effect(path):
            if "company.yaml" in str(path):
                return MOCK_VALID_CONFIG
            if "onboarding.yaml" in str(path):
                return MOCK_ONBOARDING_CONFIG
            return {}

        self.mock_utility.load_schema_from_yaml.side_effect = yaml_side_effect

        # --- First Call ---
        # Act
        result1 = self.service.get_configuration(self.COMPANY_NAME, 'name')

        # Assert
        assert result1 == 'ACME Corp'
        # The main config and the onboarding file are read.
        assert self.mock_utility.load_schema_from_yaml.call_count == 2
        expected_calls = [
            call(Path(f'companies/{self.COMPANY_NAME}/config/company.yaml')),
            call(Path(f'companies/{self.COMPANY_NAME}/config/onboarding.yaml'))
        ]
        self.mock_utility.load_schema_from_yaml.assert_has_calls(expected_calls, any_order=True)

        # --- Second Call ---
        # Act
        result2 = self.service.get_configuration(self.COMPANY_NAME, 'id')

        # Assert
        assert result2 == 'acme'
        # CRUCIAL: The call count should not have increased, proving the cache was used.
        assert self.mock_utility.load_schema_from_yaml.call_count == 2

    @patch('pathlib.Path.exists', return_value=False)
    def test_load_configuration_raises_file_not_found(self, mock_exists):
        """
        GIVEN the main company.yaml file does not exist
        WHEN load_configuration is called
        THEN it should raise a FileNotFoundError.
        """
        with pytest.raises(FileNotFoundError):
            self.service.load_configuration(self.COMPANY_NAME, self.mock_company_instance)

    @patch('pathlib.Path.is_file')
    @patch('pathlib.Path.exists')
    def test_load_configuration_handles_empty_sections(self, mock_exists, mock_is_file):
        """
        GIVEN a config file is missing optional sections like 'tools' or 'prompts'
        WHEN load_configuration is called
        THEN it should run without error and not call registration methods for those sections.
        """
        # Arrange
        # This config is minimal but still passes validation.
        minimal_config = {
            'id': 'minimal_co',
            'name': 'Minimal Co',
            'llm': {'model': 'test', 'api-key': 'TEST'},
            'embedding_provider': {'provider': 'test', 'model': 'test', 'api_key_name': 'TEST'},
            # No 'tools', 'prompts', 'data_sources', 'help_files', etc.
        }
        mock_exists.return_value = True
        mock_is_file.return_value = True  # Assume all files exist for validation simplicity
        self.mock_utility.load_schema_from_yaml.return_value = minimal_config

        # Act
        self.service.load_configuration('minimal_co', self.mock_company_instance)

        # Assert
        # Verify the core details were still registered
        self.mock_company_instance._create_company.assert_called_once_with(
            short_name='minimal_co', name='Minimal Co', parameters={}
        )
        # Verify that methods for missing sections were NOT called
        self.mock_company_instance._create_function.assert_not_called()
        self.mock_company_instance._create_prompt.assert_not_called()
        self.mock_company_instance._create_prompt_category.assert_not_called()

    def test_validation_failure_raises_exception(self):
        """
        GIVEN an invalid configuration (e.g., missing 'llm' section)
        WHEN load_configuration is called
        THEN it should raise an IAToolkitException due to validation failure.
        """
        # Arrange
        invalid_config = {
            'id': self.COMPANY_NAME,
            'name': 'Invalid Co'
            # Missing 'llm', 'embedding_provider', etc.
        }
        self.mock_utility.load_schema_from_yaml.return_value = invalid_config

        # Patch `exists` to prevent FileNotFoundError
        with patch('pathlib.Path.exists', return_value=True):
            # Act & Assert
            with pytest.raises(IAToolkitException) as excinfo:
                self.service.load_configuration(self.COMPANY_NAME, self.mock_company_instance)

            assert excinfo.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR
            assert "company.yaml validation errors" in str(excinfo.value)

    @patch('pathlib.Path.is_file', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_register_prompts_exception_from_repo(self, mock_exists, mock_is_file):
        """
        GIVEN llm_query_repo raises an exception during delete_all_prompts
        WHEN load_configuration is called
        THEN it should rollback session and raise IAToolkitException
        """
        self.mock_utility.load_schema_from_yaml.return_value = {
            'id': 'acme', 'name': 'ACME Corp', 'llm': {'model': 'm', 'api-key': 'k'},
            'embedding_provider': {'provider': 'p', 'model': 'm', 'api_key_name': 'k'},
            'prompts': [{'name': 'p1', 'category': 'Cat1', 'description': 'd', 'order': 1}],
            'prompt_categories': ['Cat1']
        }

        # Simular error en repo
        self.mock_llm_query_repo.delete_all_prompts.side_effect = Exception("DB Error")

        # Mock session para verificar rollback (asumiendo que self.service.session viene de db_manager)
        mock_session = Mock()
        self.mock_database_manager.get_session.return_value = mock_session
        # Re-instanciar service para que tome el mock session
        service = ConfigurationService(utility=self.mock_utility,
                                       db_manager=self.mock_database_manager,
                                       llm_query_repo=self.mock_llm_query_repo)

        with pytest.raises(IAToolkitException) as excinfo:
            service.load_configuration('acme', self.mock_company_instance)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert "DB Error" in str(excinfo.value)
        mock_session.rollback.assert_called_once()

    @patch('pathlib.Path.is_file', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_register_tools_exception_from_repo(self, mock_exists, mock_is_file):
        """
        GIVEN llm_query_repo raises an exception during delete_all_functions
        WHEN load_configuration is called
        THEN it should rollback session and raise IAToolkitException
        """
        self.mock_utility.load_schema_from_yaml.return_value = {
            'id': 'acme', 'name': 'ACME Corp', 'llm': {'model': 'm', 'api-key': 'k'},
            'embedding_provider': {'provider': 'p', 'model': 'm', 'api_key_name': 'k'},
            'tools': [{'function_name': 'f1', 'description': 'd', 'params': {}}]
        }

        # Simular error en repo
        self.mock_llm_query_repo.delete_all_functions.side_effect = Exception("DB Error Tools")

        mock_session = Mock()
        self.mock_database_manager.get_session.return_value = mock_session
        service = ConfigurationService(utility=self.mock_utility,
                                       db_manager=self.mock_database_manager,
                                       llm_query_repo=self.mock_llm_query_repo)

        with pytest.raises(IAToolkitException) as excinfo:
            service.load_configuration('acme', self.mock_company_instance)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert "DB Error Tools" in str(excinfo.value)
        mock_session.rollback.assert_called_once()