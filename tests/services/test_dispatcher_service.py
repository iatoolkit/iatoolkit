# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
from injector import Injector
from iatoolkit.base_company import BaseCompany
from iatoolkit.company_registry import get_company_registry, register_company
from services.dispatcher_service import Dispatcher
from common.exceptions import IAToolkitException
from repositories.llm_query_repo import LLMQueryRepo
from services.excel_service import ExcelService
from services.mail_service import MailService
from services.api_service import ApiService
from common.util import Utility


# A mock company class for testing purposes
class MockSampleCompany(BaseCompany):
    def init_db(self): pass

    def get_company_context(self, **kwargs) -> str: return "Company Context for Sample"

    def handle_request(self, tag: str, params: dict) -> dict: return {"result": "sample_company_response"}

    def start_execution(self): pass

    def get_metadata_from_filename(self, filename: str) -> dict: return {}


class TestDispatcher:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up mocks, registry, and the Dispatcher for tests."""
        # Clean up the registry before each test to prevent interference
        registry = get_company_registry()
        registry.clear()

        # Mocks for services that are injected into the Dispatcher
        self.mock_prompt_manager = MagicMock()
        self.mock_llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.excel_service = MagicMock(spec=ExcelService)
        self.mail_service = MagicMock(spec=MailService)
        self.api_service = MagicMock(spec=ApiService)
        self.util = MagicMock(spec=Utility)

        # Mock our company class instance
        self.mock_sample_company_instance = MockSampleCompany(
            profile_repo=MagicMock(),
            llm_query_repo=self.mock_llm_query_repo
        )
        # Mock methods that will be called
        self.mock_sample_company_instance.init_db = MagicMock()
        self.mock_sample_company_instance.handle_request = MagicMock(return_value={"result": "sample_company_response"})
        self.mock_sample_company_instance.get_company_context = MagicMock(return_value="Company Context for Sample")
        self.mock_sample_company_instance.start_execution = MagicMock(return_value=True)

        # Register the mock company class
        register_company("sample", MockSampleCompany)

        # --- CONTEXT PATCHING ---
        # Create a mock injector that knows how to provide the mock company instance
        mock_injector = Injector()
        mock_injector.binder.bind(MockSampleCompany, to=self.mock_sample_company_instance)

        # Create a mock IAToolkit instance
        self.toolkit_mock = MagicMock()
        self.toolkit_mock._get_injector.return_value = mock_injector

        # START the patch that will persist throughout the test
        self.current_iatoolkit_patcher = patch('services.dispatcher_service.current_iatoolkit',
                                               return_value=self.toolkit_mock)
        self.current_iatoolkit_patcher.start()

        # Initialize the Dispatcher within the patched context
        self.dispatcher = Dispatcher(
            prompt_service=self.mock_prompt_manager,
            llmquery_repo=self.mock_llm_query_repo,
            util=self.util,
            excel_service=self.excel_service,
            mail_service=self.mail_service,
            api_service=self.api_service
        )

    def teardown_method(self, method):
        """Clean up patches after each test."""
        if hasattr(self, 'current_iatoolkit_patcher'):
            self.current_iatoolkit_patcher.stop()

        # Clean up the registry
        registry = get_company_registry()
        registry.clear()

    def test_init_db_calls_init_db_on_each_company(self):
        """Tests that init_db calls init_db on each registered company."""
        self.dispatcher.init_db()
        self.mock_sample_company_instance.init_db.assert_called_once()

    def test_dispatch_sample_company(self):
        """Tests that dispatch works correctly for a valid company."""
        result = self.dispatcher.dispatch("sample", "some_data", key='a value')
        self.mock_sample_company_instance.handle_request.assert_called_once_with("some_data", key='a value')
        assert result == {"result": "sample_company_response"}

    def test_dispatch_invalid_company(self):
        """Tests that dispatch raises an exception for an unconfigured company."""
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.dispatch("invalid_company", "some_tag")
        assert "Empresa 'invalid_company' no configurada" in str(excinfo.value)

    def test_dispatch_method_exception(self):
        """Validates that the dispatcher handles exceptions thrown by companies."""
        self.mock_sample_company_instance.handle_request.side_effect = Exception("Method error")

        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.dispatch("sample", "some_data")

        assert "Error en function call 'some_data'" in str(excinfo.value)
        assert "Method error" in str(excinfo.value)

    def test_dispatch_system_function(self):
        """Tests that dispatch correctly handles system functions."""
        self.excel_service.excel_generator.return_value = {"file": "test.xlsx"}

        result = self.dispatcher.dispatch("sample", "iat_generate_excel", filename="test.xlsx")

        self.excel_service.excel_generator.assert_called_once_with(filename="test.xlsx")
        self.mock_sample_company_instance.handle_request.assert_not_called()
        assert result == {"file": "test.xlsx"}

    def test_get_company_context(self):
        """Tests that get_company_context works correctly."""
        # Simulate no context files to simplify
        self.util.get_files_by_extension.return_value = []

        params = {"param1": "value1"}
        result = self.dispatcher.get_company_context("sample", **params)

        self.mock_sample_company_instance.get_company_context.assert_called_once_with(**params)
        assert "Company Context for Sample" in result

    def test_start_execution_when_ok(self):
        """Tests that start_execution works correctly."""
        result = self.dispatcher.start_execution()

        assert result is True
        self.mock_sample_company_instance.start_execution.assert_called_once()

    def test_dispatcher_with_no_companies_registered(self):
        """Tests that the dispatcher works if no company is registered."""
        # Stop the current patch first
        self.current_iatoolkit_patcher.stop()

        # Clean registry
        get_company_registry().clear()

        toolkit_mock = MagicMock()
        toolkit_mock._get_injector.return_value = Injector()  # Empty injector

        # Start a new patch for this specific test
        with patch('services.dispatcher_service.current_iatoolkit', return_value=toolkit_mock):
            dispatcher = Dispatcher(
                prompt_service=self.mock_prompt_manager,
                llmquery_repo=self.mock_llm_query_repo,
                util=self.util,
                excel_service=self.excel_service,
                mail_service=self.mail_service,
                api_service=self.api_service
            )

            assert len(dispatcher.company_classes) == 0

            with pytest.raises(IAToolkitException) as excinfo:
                dispatcher.dispatch("any_company", "some_action")
            assert "Empresa 'any_company' no configurada" in str(excinfo.value)

        # Restart the main patch for subsequent tests
        self.current_iatoolkit_patcher = patch('services.dispatcher_service.current_iatoolkit',
                                               return_value=self.toolkit_mock)
        self.current_iatoolkit_patcher.start()