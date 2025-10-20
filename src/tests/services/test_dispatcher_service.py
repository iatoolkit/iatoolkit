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
from iatoolkit.repositories.models import Company, Function
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.mail_service import MailService
from iatoolkit.common.util import Utility


# A mock company class for testing purposes
class MockSampleCompany(BaseCompany):
    def register_company(self): pass

    def get_company_context(self, **kwargs) -> str: return "Company Context for Sample"

    def handle_request(self, tag: str, params: dict) -> dict: return {"result": "sample_company_response"}

    def start_execution(self): pass

    def get_user_info(self, user_identifier: str): pass

    def get_metadata_from_filename(self, filename: str) -> dict: return {}


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


        # Create a mock injector that will be used for instantiation.
        mock_injector = Injector()
        mock_injector.binder.bind(ProfileRepo, to=self.mock_profile_repo)
        mock_injector.binder.bind(LLMQueryRepo, to=self.mock_llm_query_repo)
        mock_injector.binder.bind(PromptService, to=self.mock_prompt_manager)

        # Create a mock IAToolkit instance that returns our injector.
        self.toolkit_mock = MagicMock()
        self.toolkit_mock.get_injector.return_value = mock_injector

        # Patch IAToolkit.get_instance() to return our mock toolkit. This must be active
        # BEFORE any code that depends on the IAToolkit singleton is run.
        self.get_instance_patcher = patch('iatoolkit.iatoolkit.IAToolkit.get_instance',
                                          return_value=self.toolkit_mock)
        self.get_instance_patcher.start()

        # Now we can safely instantiate our mock company.
        self.mock_sample_company_instance = MockSampleCompany()

        # Mock methods that will be called
        self.mock_sample_company_instance.register_company = MagicMock()
        self.mock_sample_company_instance.handle_request = MagicMock(return_value={"result": "sample_company_response"})
        self.mock_sample_company_instance.get_company_context = MagicMock(return_value="Company Context for Sample")
        self.mock_sample_company_instance.start_execution = MagicMock(return_value=True)
        self.mock_sample_company_instance.get_user_info = MagicMock(return_value={"email": "test@user.com"})
        self.mock_sample_company_instance.get_metadata_from_filename = MagicMock(return_value={"meta": "data"})

        # Register the mock company class
        register_company("sample", MockSampleCompany)

        # Bind the mock instance in our injector. When the registry asks for an instance of
        # MockSampleCompany, the injector will return our pre-configured mock instance.
        mock_injector.binder.bind(MockSampleCompany, to=self.mock_sample_company_instance)

        # Instantiate all registered companies. The registry will use our mock_injector.
        registry.instantiate_companies(mock_injector)

        # Initialize the Dispatcher within the patched context
        self.dispatcher = Dispatcher(
            prompt_service=self.mock_prompt_manager,
            profile_service=self.profile_service,
            llmquery_repo=self.mock_llm_query_repo,
            util=self.util,
            excel_service=self.excel_service,
            mail_service=self.mail_service,
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

    def test_get_company_instance(self):
        """Tests that get_company_instance returns the correct company instance."""
        instance = self.dispatcher.get_company_instance("sample")
        assert instance == self.mock_sample_company_instance

        instance_none = self.dispatcher.get_company_instance("non_existent")
        assert instance_none is None

    def test_get_metadata_from_filename_success(self):
        """Tests that get_metadata_from_filename successfully calls the company's method."""
        filename = "test.txt"
        expected_metadata = {"meta": "data"}
        self.mock_sample_company_instance.get_metadata_from_filename.return_value = expected_metadata

        result = self.dispatcher.get_metadata_from_filename("sample", filename)

        self.mock_sample_company_instance.get_metadata_from_filename.assert_called_once_with(filename)
        assert result == expected_metadata

    def test_get_metadata_from_filename_invalid_company(self):
        """Tests get_metadata_from_filename with an invalid company."""
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.get_metadata_from_filename("invalid_company", "test.txt")
        assert "Empresa no configurada: invalid_company" in str(excinfo.value)

    def test_get_metadata_from_filename_company_exception(self):
        """Tests get_metadata_from_filename when the company method raises an exception."""
        self.mock_sample_company_instance.get_metadata_from_filename.side_effect = Exception("Company error")
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.get_metadata_from_filename("sample", "test.txt")
        assert "Error en get_metadata_from_filename de sample" in str(excinfo.value)


    def test_get_user_info_external_user(self):
        """Tests get_user_info for an external user."""
        user_identifier = "ext_user_123"
        expected_user_data = {"email": "external@example.com"}
        self.mock_sample_company_instance.get_user_info.return_value = expected_user_data

        result = self.dispatcher.get_user_info("sample", user_identifier, is_local_user=False)

        self.mock_sample_company_instance.get_user_info.assert_called_once_with(user_identifier)
        assert result["user_email"] == "external@example.com"
        assert not result["is_local"]

    def test_get_user_info_external_user_company_exception(self):
        """Tests get_user_info for an external user when the company method fails."""
        self.mock_sample_company_instance.get_user_info.side_effect = Exception("DB error")
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.get_user_info("sample", "ext_user_123", is_local_user=False)
        assert "Error en get_user_info de sample" in str(excinfo.value)

    def test_get_user_info_local_user(self):
        """Tests get_user_info for a local user from session."""
        user_identifier = "local_user_1"
        session_data = {"email": "local@iatoolkit.com", "user_fullname": "Local User"}
        self.profile_service.get_current_user_profile.return_value = session_data

        result = self.dispatcher.get_user_info("sample", user_identifier, is_local_user=True)

        self.mock_sample_company_instance.get_user_info.assert_not_called()
        assert result["user_email"] == "local@iatoolkit.com"
        assert result["user_fullname"] == "Local User"
        assert result["is_local"]

    def test_get_user_info_invalid_company(self):
        """Tests get_user_info with an invalid company."""
        with pytest.raises(IAToolkitException) as excinfo:
            self.dispatcher.get_user_info("invalid_company", "any_user", is_local_user=False)
        assert "Empresa no configurada: invalid_company" in str(excinfo.value)

    def test_get_company_services(self):
        """Tests that get_company_services returns a correctly formatted list of tools."""
        # Mock Company and Function objects
        mock_company = MagicMock(spec=Company)
        mock_function = MagicMock(spec=Function)
        mock_function.name = "test_function"
        mock_function.description = "A test function"
        mock_function.parameters = {"type": "object", "properties": {}}

        self.mock_llm_query_repo.get_company_functions.return_value = [mock_function]

        tools = self.dispatcher.get_company_services(mock_company)

        self.mock_llm_query_repo.get_company_functions.assert_called_once_with(mock_company)
        assert len(tools) == 1
        tool = tools[0]
        assert tool["type"] == "function"
        assert tool["name"] == "test_function"
        assert tool["description"] == "A test function"
        assert tool["parameters"]["additionalProperties"] is False
        assert tool["strict"] is True

    def test_dispatcher_with_no_companies_registered(self):
        """Tests that the dispatcher works if no company is registered."""
        # Stop the current patch first
        self.get_instance_patcher.stop()

        # Clean registry
        get_company_registry().clear()

        toolkit_mock = MagicMock()
        toolkit_mock.get_injector.return_value = Injector()  # Empty injector

        # Start a new patch for this specific test
        with patch('iatoolkit.iatoolkit.IAToolkit.get_instance', return_value=toolkit_mock):
            dispatcher = Dispatcher(
                prompt_service=self.mock_prompt_manager,
                profile_service=self.profile_service,
                llmquery_repo=self.mock_llm_query_repo,
                util=self.util,
                excel_service=self.excel_service,
                mail_service=self.mail_service,
            )

            assert len(dispatcher.company_instances) == 0

            with pytest.raises(IAToolkitException) as excinfo:
                dispatcher.dispatch("any_company", "some_action")
            assert "Empresa 'any_company' no configurada" in str(excinfo.value)

        # Restart the main patch for subsequent tests
        self.get_instance_patcher.start()