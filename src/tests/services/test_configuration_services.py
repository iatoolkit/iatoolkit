# tests/services/test_configuration_services.py

import pytest
from unittest.mock import Mock, patch

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
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
        'provider_api_keys': [{'openai': 'TEST_OPENAI_API_KEY'}]
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
            if "SqlService" in str(service_class):  # Nuevo caso
                return mock_sql_service
            return Mock()
        mock_injector.get.side_effect = get_side_effect

        # 1. Simular existencia de archivos
        self.mock_asset_repo.exists.return_value = True

        # 2. Simular contenido de archivos (texto)
        # Nota: aquí no importa el contenido exacto del string, importa lo que devuelva el parser
        self.mock_asset_repo.read_text.return_value = "yaml content"

        # 3. Simular el parser de Utility
        def yaml_parser_side_effect(content):
            # Simulamos que si el repo devolvió contenido, el parser devuelve el dict
            # Podríamos hacer lógica más compleja si necesitamos distinguir company.yaml de onboarding
            # Pero para este test, usaremos el mock global que devuelve MOCK_VALID_CONFIG
            # O mejor, usamos side_effect basado en llamadas previas (complicado).
            # Simplificación: Asumimos que la primera llamada es company.yaml
            return MOCK_VALID_CONFIG

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
        # El código valida si los prompts existen en el repo
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

        # Setup mocks similares al anterior
        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = MOCK_VALID_CONFIG

        # First Call
        result1 = self.service.get_configuration(self.COMPANY_NAME, 'name')
        assert result1 == 'ACME Corp'
        assert self.mock_asset_repo.read_text.call_count >= 1  # Se llamó para cargar

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

        # Configure Injector to return our specific mocks
        def get_side_effect(service_class):
            if "ToolService" in str(service_class):
                return mock_tool_service
            if "PromptService" in str(service_class):
                return mock_prompt_service
            return Mock()

        mock_injector.get.side_effect = get_side_effect

        # --- Arrange Minimal Config ---
        # A minimal configuration without 'tools' or 'prompts' keys
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
            # Note: No 'tools' or 'prompts' keys here
        }

        # 1. Simulate file existence in AssetRepository
        self.mock_asset_repo.exists.return_value = True

        # 2. Simulate reading file content (returns a dummy string)
        self.mock_asset_repo.read_text.return_value = "yaml_content"

        # 3. Simulate parsing that content into our minimal dict
        self.mock_utility.load_yaml_from_string.return_value = minimal_config

        # --- Act ---
        self.service.load_configuration('minimal_co')

        # --- Assert ---
        # Verify ToolService received an empty list (default for missing key)
        mock_tool_service.sync_company_tools.assert_called_once_with('minimal_co', [])

        # Verify PromptService received empty lists for prompts and categories
        mock_prompt_service.sync_company_prompts.assert_called_once_with(
            company_short_name='minimal_co',
            prompts_config=[],
            categories_config=[]
        )

    def test_validation_failure_raises_exception(self):
        # Arrange invalid config
        invalid_config = {'id': self.COMPANY_NAME, 'name': 'Invalid Co'}
        self.mock_asset_repo.exists.return_value = True
        self.mock_asset_repo.read_text.return_value = "yaml"
        self.mock_utility.load_yaml_from_string.return_value = invalid_config

        with pytest.raises(IAToolkitException) as excinfo:
            self.service.load_configuration(self.COMPANY_NAME)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR

