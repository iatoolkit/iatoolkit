# tests/services/test_tool_service.py

import pytest
from unittest.mock import MagicMock, ANY
from iatoolkit.services.tool_service import ToolService, _SYSTEM_TOOLS
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import Company, Tool
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.mail_service import MailService


class TestToolService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.mock_sql_service = MagicMock(spec=SqlService)
        self.mock_excel_service = MagicMock(spec=ExcelService)
        self.mock_mail_service = MagicMock(spec=MailService)

        self.service = ToolService(
            llm_query_repo=self.mock_llm_query_repo,
            sql_service=self.mock_sql_service,
            excel_service=self.mock_excel_service,
            mail_service=self.mock_mail_service
        )

        # Mock del modelo de base de datos (Company Model)
        self.mock_company_model = MagicMock(spec=Company)
        self.mock_company_model.id = 1

        # Mock de la instancia de negocio (Company Instance) que tiene .company
        self.mock_company_instance = MagicMock()
        self.mock_company_instance.company = self.mock_company_model


    def test_register_system_tools_success(self):
        """
        GIVEN a call to register_system_tools
        WHEN executed
        THEN it should delete old system tools, create new ones from _SYSTEM_TOOLS constant, and commit.
        """
        # Act
        self.service.register_system_tools()

        # Assert
        self.mock_llm_query_repo.delete_system_tools.assert_called_once()

        # Verify create_or_update_tool called for each system tool
        assert self.mock_llm_query_repo.create_or_update_tool.call_count == len(_SYSTEM_TOOLS)

        # Verify commit
        self.mock_llm_query_repo.commit.assert_called_once()

    def test_register_system_tools_rollback_on_exception(self):
        """
        GIVEN an exception during registration
        WHEN register_system_tools is executed
        THEN it should rollback and raise IAToolkitException.
        """
        # Arrange
        self.mock_llm_query_repo.delete_system_tools.side_effect = Exception("DB Error")

        # Act & Assert
        with pytest.raises(IAToolkitException) as excinfo:
            self.service.register_system_tools()

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        self.mock_llm_query_repo.rollback.assert_called_once()

    def test_sync_company_tools_create_update_delete(self):
        """
        GIVEN a company config with tools
        WHEN sync_company_tools is executed
        THEN it should create new tools, update existing ones, and delete removed ones.
        """
        # Arrange
        # Existing tools in DB: 'existing_keep' (to update), 'existing_remove' (to delete)
        existing_tool_keep = MagicMock(spec=Tool)
        existing_tool_keep.name = 'existing_keep'
        existing_tool_keep.system_function = False

        existing_tool_remove = MagicMock(spec=Tool)
        existing_tool_remove.name = 'existing_remove'
        existing_tool_remove.system_function = False  # Important: ensure it's not a system function

        self.mock_llm_query_repo.get_company_tools.return_value = [existing_tool_keep, existing_tool_remove]

        # Config defines: 'existing_keep' (updated) and 'new_tool' (created)
        tools_config = [
            {'function_name': 'existing_keep', 'description': 'Updated Desc', 'params': {'p': 1}},
            {'function_name': 'new_tool', 'description': 'New Desc', 'params': {'p': 2}}
        ]

        # Act: Pasamos mock_company_instance, no el modelo directamente
        self.service.sync_company_tools(self.mock_company_instance, tools_config)

        # Verificar que se llamó a get_company_tools con el modelo correcto
        self.mock_llm_query_repo.get_company_tools.assert_called_once_with(self.mock_company_model)

        assert self.mock_llm_query_repo.create_or_update_tool.call_count == 2

        # Verify calls arguments
        calls = self.mock_llm_query_repo.create_or_update_tool.call_args_list

        # Call for 'existing_keep'
        args_keep, _ = calls[0]
        func_keep = args_keep[0]
        assert func_keep.name == 'existing_keep'
        assert func_keep.description == 'Updated Desc'

        # Call for 'new_tool'
        args_new, _ = calls[1]
        func_new = args_new[0]
        assert func_new.name == 'new_tool'
        assert func_new.description == 'New Desc'

        # 2. Check DELETE on 'existing_remove'
        # Since implementation iterates dict items, order might vary, but 'existing_remove' is not in config
        self.mock_llm_query_repo.delete_tool.assert_called_once_with(existing_tool_remove)

        # 3. Check Commit
        self.mock_llm_query_repo.commit.assert_called_once()

    def test_sync_company_tools_rollback_on_exception(self):
        """
        GIVEN an exception during sync
        WHEN sync_company_tools is executed
        THEN it should rollback and raise exception.
        """
        self.mock_llm_query_repo.get_company_tools.side_effect = Exception("Sync Error")
        tools_config = [
            {'function_name': 'existing_keep', 'description': 'Updated Desc', 'params': {'p': 1}},
        ]

        with pytest.raises(IAToolkitException) as excinfo:
            self.service.sync_company_tools(self.mock_company_instance, tools_config)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        self.mock_llm_query_repo.rollback.assert_called_once()

    def test_get_tools_for_llm_format(self):
        """
        GIVEN a company with tools
        WHEN get_tools_for_llm is called
        THEN it should return a list of tools formatted for OpenAI (type, function, strict).
        """
        # Arrange
        tool1 = MagicMock(spec=Tool)
        tool1.name = 'tool1'
        tool1.description = 'desc1'
        tool1.parameters = {'prop': 1}

        self.mock_llm_query_repo.get_company_tools.return_value = [tool1]

        # Act
        result = self.service.get_tools_for_llm(self.mock_company_instance)

        # Assert
        assert len(result) == 1
        assert result[0]['type'] == 'function'
        assert result[0]['name'] == 'tool1'
        assert result[0]['description'] == 'desc1'
        assert result[0]['parameters']['prop'] == 1
        assert result[0]['parameters']['additionalProperties'] is False
        assert result[0]['strict'] is True

    def test_get_system_handler(self):
        """
        Test that get_system_handler returns the correct method for a known system tool
        and None for unknown.
        """
        # Known handler
        handler = self.service.get_system_handler("iat_generate_excel")
        assert handler == self.mock_excel_service.excel_generator

        # Unknown handler
        assert self.service.get_system_handler("unknown_tool") is None

    def test_is_system_tool(self):
        """
        Test is_system_tool logic.
        """
        assert self.service.is_system_tool("iat_generate_excel") is True
        assert self.service.is_system_tool("custom_company_tool") is False