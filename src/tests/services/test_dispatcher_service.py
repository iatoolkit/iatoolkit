# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
from injector import Injector
from iatoolkit.base_company import BaseCompany
from iatoolkit.company_registry import get_company_registry, register_company
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.tool_service import ToolService
from iatoolkit.common.util import Utility


# A mock company class for testing purposes
class MockSampleCompany(BaseCompany):
    def handle_request(self, tag: str, params: dict) -> dict: return {"result": "sample_company_response"}

    def register_cli_commands(self, app): pass


class TestDispatcher:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up mocks, registry, and the Dispatcher for tests."""
        # Clean up the registry before each test to prevent interference
        registry = get_company_registry()
        registry.clear()

        # Mocks for services that are injected into the Dispatcher
        self.mock_prompt_manager = MagicMock(spec=PromptService)
        self.profile_service = MagicMock(spec=ProfileService)
        self.mock_llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.excel_service = MagicMock(spec=ExcelService)
        self.mail_service = MagicMock(spec=MailService)
        self.util = MagicMock(spec=Utility)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_tool_service = MagicMock(spec=ToolService)

        # Create a mock injector that will be used for instantiation.
        mock_injector = Injector()
        mock_injector.binder.bind(ProfileRepo, to=self.mock_profile_repo)
        mock_injector.binder.bind(LLMQueryRepo, to=self.mock_llm_query_repo)
        mock_injector.binder.bind(PromptService, to=self.mock_prompt_manager)
        mock_injector.binder.bind(ToolService, to=self.mock_tool_service)  # Bind ToolService

        # Create a mock IAToolkit instance that returns our injector.
        self.toolkit_mock = MagicMock()
        self.toolkit_mock.get_injector.return_value = mock_injector

        # Patch IAToolkit.get_instance() to return our mock toolkit. This must be active
        # BEFORE any code that depends on the IAToolkit singleton is run.
        self.get_instance_patcher = patch('iatoolkit.core.IAToolkit.get_instance',
                                          return_value=self.toolkit_mock)
        self.get_instance_patcher.start()

        # Now we can safely instantiate our mock company.
        self.mock_sample_company_instance = MockSampleCompany()

        # Mock methods that will be called
        self.mock_sample_company_instance.register_company = MagicMock()
        self.mock_sample_company_instance.handle_request = MagicMock(return_value={"result": "sample_company_response"})
        self.mock_sample_company_instance.get_company_context = MagicMock(return_value="Company Context for Sample")
        self.mock_sample_company_instance.get_metadata_from_filename = MagicMock(return_value={"meta": "data"})

        # Register the mock company class
        register_company("sample", MockSampleCompany)

        # Bind the mock instance in our injector. When the registry asks for an instance of
        # MockSampleCompany, the injector will return our pre-configured mock instance.
        mock_injector.binder.bind(MockSampleCompany, to=self.mock_sample_company_instance)

        # Instantiate all registered companies. The registry will use our mock_injector.
        registry.instantiate_companies(mock_injector)

        self.mock_config_service.load_configuration.return_value = {"sample": {"key": "value"}}, []

        # Initialize the Dispatcher within the patched context
        self.dispatcher = Dispatcher(
            config_service=self.mock_config_service,
            prompt_service=self.mock_prompt_manager,
            llmquery_repo=self.mock_llm_query_repo,
            util=self.util,
        )

    def teardown_method(self, method):
        """Clean up patches after each test."""
        if hasattr(self, 'get_instance_patcher'):
            self.get_instance_patcher.stop()

        # Clean up the registry
        registry = get_company_registry()
        registry.clear()

    def test_dispatch_sample_company(self):
        """Tests that dispatch works correctly for a valid company."""
        # Ensure tool service says it's NOT a system tool
        self.mock_tool_service.is_system_tool.return_value = False

        result = self.dispatcher.dispatch("sample", "some_data", key='a value')

        self.mock_sample_company_instance.handle_request.assert_called_once_with("some_data", key='a value')
        assert result == {"result": "sample_company_response"}

    def test_dispatch_invalid_company(self):
        """Tests that dispatch raises an exception for an unconfigured company."""
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.dispatch("invalid_company", "some_tag")
        assert "Company 'invalid_company' not configured." in str(excinfo.value)

    def test_dispatch_method_exception(self):
        """Validates that the dispatcher handles exceptions thrown by companies."""
        self.mock_tool_service.is_system_tool.return_value = False
        self.mock_sample_company_instance.handle_request.side_effect = Exception("Method error")

        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.dispatch("sample", "some_data")

        assert "Error in function call 'some_data'" in str(excinfo.value)
        assert "Method error" in str(excinfo.value)

    def test_dispatch_system_function(self):
        """Tests that dispatch correctly handles system functions via ToolService."""
        # Setup mocks for system tool detection
        self.mock_tool_service.is_system_tool.return_value = True

        # Mock handler returned by ToolService
        mock_handler = MagicMock(return_value={"file": "test.xlsx"})
        self.mock_tool_service.get_system_handler.return_value = mock_handler

        result = self.dispatcher.dispatch("sample", "iat_generate_excel", filename="test.xlsx")

        # Assertions
        self.mock_tool_service.is_system_tool.assert_called_once_with("iat_generate_excel")
        self.mock_tool_service.get_system_handler.assert_called_once_with("iat_generate_excel")
        mock_handler.assert_called_once_with("sample", filename="test.xlsx")

        # Ensure company handler was NOT called
        self.mock_sample_company_instance.handle_request.assert_not_called()
        assert result == {"file": "test.xlsx"}

    def test_get_company_instance(self):
        """Tests that get_company_instance returns the correct company instance."""
        instance = self.dispatcher.get_company_instance("sample")
        assert instance == self.mock_sample_company_instance

        instance_none = self.dispatcher.get_company_instance("non_existent")
        assert instance_none is None

    def test_dispatcher_with_no_companies_registered(self):
        """Tests that the dispatcher works if no company is registered."""

        # 1. Clear the global registry (simulating no companies registered)
        registry = get_company_registry()
        registry.clear()

        # 2. Reset the internal cache of the dispatcher instance created in setup()
        # This forces it to re-fetch from the (now empty) registry on next access property access
        self.dispatcher._company_instances = None

        # 3. Verify state
        assert len(self.dispatcher.company_instances) == 0

        # 4. Execute dispatch and expect error
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.dispatch("any_company", "some_action")

        assert "Company 'any_company' not configured" in str(excinfo.value)

    def test_setup_iatoolkit_system_success(self):
        """Test successful setup of system functions and prompts."""
        # Call the method under test
        self.dispatcher.setup_iatoolkit_system()

        # Verify ToolService called
        self.mock_tool_service.register_system_tools.assert_called_once()


    def test_setup_iatoolkit_system_exception(self):
        """Test that setup_iatoolkit_system handles exceptions and rolls back."""
        # Configure mock to raise an exception in ToolService
        self.mock_tool_service.register_system_tools.side_effect = Exception("DB Error")

        # Configure repo rollback mock
        self.mock_llm_query_repo.rollback = MagicMock()

        # Verify exception is raised and wrapped in IAToolkitException
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.setup_iatoolkit_system()

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        assert "DB Error" in str(excinfo.value)

        # Verify rollback was called
        self.mock_llm_query_repo.rollback.assert_called_once()

    def test_load_company_configs_success(self):
        """Test load_company_configs loads configuration for all companies."""
        # Dispatcher uses self.company_instances which is populated by registry.
        # We have "sample" registered in setup()

        # Mock setup_iatoolkit_system
        self.dispatcher.setup_iatoolkit_system = MagicMock()

        # Call method under test
        result = self.dispatcher.load_company_configs()

        # Assertions
        self.dispatcher.setup_iatoolkit_system.assert_called_once()

        # Verify config_service.load_configuration called for "sample"
        self.mock_config_service.load_configuration.assert_called_once_with(
            "sample"
        )

        assert result is True

    def test_load_company_configs_handles_exception(self):
        """Test load_company_configs raises exception on failure."""
        self.dispatcher.setup_iatoolkit_system = MagicMock()

        # Simulate error during configuration loading
        self.mock_config_service.load_configuration.side_effect = Exception("Config Error")

        with pytest.raises(Exception) as excinfo:
            self.dispatcher.load_company_configs()

        assert "Config Error" in str(excinfo.value)
