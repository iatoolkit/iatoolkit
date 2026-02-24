# tests/services/test_tool_service.py

import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.tool_service import ToolService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import Company, Tool
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.services.visual_tool_service import VisualToolService
from iatoolkit.services.system_tools import SYSTEM_TOOLS_DEFINITIONS

class TestToolService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.mock_sql_service = MagicMock(spec=SqlService)
        self.mock_excel_service = MagicMock(spec=ExcelService)
        self.mock_mail_service = MagicMock(spec=MailService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.knowledge_base_service = MagicMock(spec=KnowledgeBaseService)
        self.mock_visual_kb_service = MagicMock(spec=VisualKnowledgeBaseService)
        self.mock_visual_tool_service = MagicMock(spec=VisualToolService)
        self.mock_web_search_service = MagicMock()

        self.service = ToolService(
            llm_query_repo=self.mock_llm_query_repo,
            profile_repo=self.mock_profile_repo,
            sql_service=self.mock_sql_service,
            excel_service=self.mock_excel_service,
            mail_service=self.mock_mail_service,
            knowledge_base_service=self.knowledge_base_service,
            visual_kb_service=self.mock_visual_kb_service,
            visual_tool_service=self.mock_visual_tool_service,
            web_search_service=self.mock_web_search_service,
        )

        # Mock del modelo de base de datos (Company Model)
        self.mock_company = MagicMock(spec=Company)
        self.mock_company.id = 1

        # Mock de la instancia de negocio (Company Instance) que tiene .company
        self.company_short_name = 'my_company'
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company


    def test_register_system_tools_success(self):
        """
        GIVEN a call to register_system_tools
        WHEN executed
        THEN it should delete old system tools, create new ones with TYPE_SYSTEM, and commit.
        """
        # Mock the system definitions imported in service
        with patch('iatoolkit.services.tool_service.SYSTEM_TOOLS_DEFINITIONS', [{'function_name': 'sys_1', 'description': 'd', 'parameters': {}}]):
            # Act
            self.service.register_system_tools()

            # Assert
            self.mock_llm_query_repo.delete_system_tools.assert_called_once()
            self.mock_llm_query_repo.create_or_update_tool.assert_called_once()

            # Check args
            created_tool = self.mock_llm_query_repo.create_or_update_tool.call_args[0][0]
            assert created_tool.tool_type == Tool.TYPE_SYSTEM
            assert created_tool.source == Tool.SOURCE_SYSTEM

            self.mock_llm_query_repo.commit.assert_called_once()

    def test_system_tools_required_matches_properties_for_strict_schema(self):
        for tool_def in SYSTEM_TOOLS_DEFINITIONS:
            parameters = tool_def.get("parameters", {})
            properties = parameters.get("properties", {})
            required = parameters.get("required", [])
            assert sorted(required) == sorted(properties.keys())

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

    def test_sync_company_tools_logic(self):
        """
        GIVEN a company config with tools
        WHEN sync_company_tools is executed
        THEN it should create YAML tools as NATIVE/YAML, delete only removed YAML tools, and ignore USER tools.
        """
        # Arrange
        # DB State:
        # 1. 'yaml_keep': From YAML, still in config (Keep & Update)
        # 2. 'yaml_remove': From YAML, removed from config (Delete)
        # 3. 'user_defined': From GUI (Ignore/Keep)

        tool_yaml_keep = MagicMock(spec=Tool)
        tool_yaml_keep.name = 'yaml_keep'
        tool_yaml_keep.source = Tool.SOURCE_YAML

        tool_yaml_remove = MagicMock(spec=Tool)
        tool_yaml_remove.name = 'yaml_remove'
        tool_yaml_remove.source = Tool.SOURCE_YAML

        tool_user = MagicMock(spec=Tool)
        tool_user.name = 'user_defined'
        tool_user.source = Tool.SOURCE_USER

        self.mock_llm_query_repo.get_company_tools.return_value = [tool_yaml_keep, tool_yaml_remove, tool_user]

        # Config defines: 'yaml_keep' (updated) and 'new_yaml' (created)
        tools_config = [
            {'function_name': 'yaml_keep', 'description': 'Updated', 'params': {}},
            {'function_name': 'new_yaml', 'description': 'New', 'params': {}}
        ]

        # Act
        self.service.sync_company_tools(self.company_short_name, tools_config)

        # Assert

        # 1. Upsert Calls
        assert self.mock_llm_query_repo.create_or_update_tool.call_count == 2
        calls = self.mock_llm_query_repo.create_or_update_tool.call_args_list

        # Check 'yaml_keep' update
        tool_keep = calls[0][0][0]
        assert tool_keep.name == 'yaml_keep'
        assert tool_keep.source == Tool.SOURCE_YAML
        assert tool_keep.tool_type == Tool.TYPE_NATIVE

        # Check 'new_yaml' creation
        tool_new = calls[1][0][0]
        assert tool_new.name == 'new_yaml'
        assert tool_new.source == Tool.SOURCE_YAML
        assert tool_new.tool_type == Tool.TYPE_NATIVE

        # 2. Delete Calls
        # Should only delete 'yaml_remove' because source=YAML and not in config
        self.mock_llm_query_repo.delete_tool.assert_called_once_with(tool_yaml_remove)

        # 'user_defined' should NOT be deleted even though it's not in config
        # Verified implicitly by delete_tool called once.

        self.mock_llm_query_repo.commit.assert_called_once()

    def test_sync_company_tools_rollback_on_exception(self):
        """
        GIVEN an exception during sync
        WHEN sync_company_tools is executed
        THEN it should rollback and raise exception.
        """
        self.mock_llm_query_repo.get_company_tools.side_effect = Exception("Sync Error")

        with pytest.raises(IAToolkitException) as excinfo:
            self.service.sync_company_tools(self.company_short_name, [])

        assert excinfo.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        self.mock_llm_query_repo.rollback.assert_called_once()

    def test_get_tools_for_llm_format(self):
        """
        GIVEN a company with tools
        WHEN get_tools_for_llm is called
        THEN it should return a list of tools formatted for OpenAI.
        """
        # Arrange
        tool1 = MagicMock(spec=Tool)
        tool1.name = 'tool1'
        tool1.description = 'desc1'
        tool1.parameters = {'prop': 1}

        self.mock_llm_query_repo.get_company_tools.return_value = [tool1]

        # Act
        result = self.service.get_tools_for_llm(self.mock_company)

        # Assert
        assert len(result) == 1
        assert result[0]['type'] == 'function'
        assert result[0]['name'] == 'tool1'
        assert result[0]['strict'] is True

    # --- CRUD Tests ---

    def test_create_tool_api(self):
        """Test creating a tool via API logic."""
        # Arrange
        tool_data = {
            "name": "api_tool",
            "description": "desc",
            "tool_type": Tool.TYPE_INFERENCE,
            "execution_config": {"url": "http"}
        }
        # Mock no duplication
        self.mock_llm_query_repo.get_tool_definition.return_value = None

        mock_created = MagicMock(spec=Tool)
        mock_created.to_dict.return_value = tool_data
        self.mock_llm_query_repo.add_tool.return_value = mock_created

        # Act
        result = self.service.create_tool(self.company_short_name, tool_data)

        # Assert
        assert result['name'] == 'api_tool'
        self.mock_llm_query_repo.add_tool.assert_called_once()
        args = self.mock_llm_query_repo.add_tool.call_args[0][0]
        assert args.source == Tool.SOURCE_USER
        assert args.tool_type == Tool.TYPE_INFERENCE

    def test_create_http_tool_requires_execution_config(self):
        self.mock_llm_query_repo.get_tool_definition.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.service.create_tool(self.company_short_name, {
                "name": "http_orders",
                "description": "Orders API",
                "tool_type": Tool.TYPE_HTTP
            })

        assert exc.value.error_type == IAToolkitException.ErrorType.MISSING_PARAMETER
        self.mock_llm_query_repo.add_tool.assert_not_called()

    def test_create_http_tool_rejects_non_https_url(self):
        self.mock_llm_query_repo.get_tool_definition.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.service.create_tool(self.company_short_name, {
                "name": "http_orders",
                "description": "Orders API",
                "tool_type": Tool.TYPE_HTTP,
                "execution_config": {
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "http://api.example.com/orders"
                    }
                }
            })

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
        self.mock_llm_query_repo.add_tool.assert_not_called()

    def test_create_http_tool_success(self):
        self.mock_llm_query_repo.get_tool_definition.return_value = None

        mock_created = MagicMock(spec=Tool)
        mock_created.to_dict.return_value = {"name": "http_orders"}
        self.mock_llm_query_repo.add_tool.return_value = mock_created

        result = self.service.create_tool(self.company_short_name, {
            "name": "http_orders",
            "description": "Orders API",
            "tool_type": Tool.TYPE_HTTP,
            "execution_config": {
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/orders",
                    "timeout_ms": 15000
                }
            }
        })

        assert result["name"] == "http_orders"
        args = self.mock_llm_query_repo.add_tool.call_args[0][0]
        assert args.tool_type == Tool.TYPE_HTTP
        assert args.execution_config["request"]["url"] == "https://api.example.com/orders"

    def test_create_http_tool_rejects_invalid_security_allowed_hosts(self):
        self.mock_llm_query_repo.get_tool_definition.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.service.create_tool(self.company_short_name, {
                "name": "http_orders",
                "description": "Orders API",
                "tool_type": Tool.TYPE_HTTP,
                "execution_config": {
                    "version": 1,
                    "request": {"method": "GET", "url": "https://api.example.com/orders"},
                    "security": {"allowed_hosts": "api.example.com"}
                }
            })

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER

    def test_create_http_tool_rejects_allow_private_network_true(self):
        self.mock_llm_query_repo.get_tool_definition.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.service.create_tool(self.company_short_name, {
                "name": "http_orders",
                "description": "Orders API",
                "tool_type": Tool.TYPE_HTTP,
                "execution_config": {
                    "version": 1,
                    "request": {"method": "GET", "url": "https://api.example.com/orders"},
                    "security": {"allow_private_network": True}
                }
            })

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER

    def test_create_tool_duplicate_error(self):
        """Test creating a duplicate tool throws exception."""
        self.mock_llm_query_repo.get_tool_definition.return_value = MagicMock() # Exists

        with pytest.raises(IAToolkitException) as exc:
            self.service.create_tool(self.company_short_name, {"name": "dup", "description": "d"})

        assert exc.value.error_type == IAToolkitException.ErrorType.DUPLICATE_ENTRY

    def test_update_tool_success(self):
        """Test updating a tool."""
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_NATIVE
        existing_tool.execution_config = None
        existing_tool.to_dict.return_value = {}
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        update_data = {"description": "new desc"}
        self.service.update_tool(self.company_short_name, 1, update_data)

        assert existing_tool.description == "new desc"
        self.mock_llm_query_repo.commit.assert_called_once()

    def test_update_tool_switch_to_http_requires_execution_config(self):
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_NATIVE
        existing_tool.execution_config = None
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        with pytest.raises(IAToolkitException) as exc:
            self.service.update_tool(self.company_short_name, 1, {"tool_type": Tool.TYPE_HTTP})

        assert exc.value.error_type == IAToolkitException.ErrorType.MISSING_PARAMETER

    def test_update_http_tool_success_with_existing_execution_config(self):
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_HTTP
        existing_tool.execution_config = {
            "version": 1,
            "request": {"method": "GET", "url": "https://api.example.com/orders"}
        }
        existing_tool.to_dict.return_value = {"id": 1, "description": "updated"}
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        result = self.service.update_tool(self.company_short_name, 1, {"description": "updated"})

        assert result["description"] == "updated"
        self.mock_llm_query_repo.commit.assert_called_once()

    def test_update_http_tool_rejects_invalid_success_status_codes(self):
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_HTTP
        existing_tool.execution_config = {
            "version": 1,
            "request": {"method": "GET", "url": "https://api.example.com/orders"}
        }
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        with pytest.raises(IAToolkitException) as exc:
            self.service.update_tool(self.company_short_name, 1, {
                "execution_config": {
                    "version": 1,
                    "request": {"method": "GET", "url": "https://api.example.com/orders"},
                    "response": {"success_status_codes": [700]}
                }
            })

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER

    def test_update_tool_system_tool_fails(self):
        """Test that system tools cannot be updated."""
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_SYSTEM # System!
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        with pytest.raises(IAToolkitException) as exc:
            self.service.update_tool(self.company_short_name, 1, {})

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION

    def test_update_tool_system_tool_allowed_with_flag(self):
        """Test that system tools can be updated when explicitly authorized."""
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_SYSTEM
        existing_tool.to_dict.return_value = {"id": 1, "description": "updated"}
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        result = self.service.update_tool(
            self.company_short_name,
            1,
            {"description": "updated"},
            allow_system_update=True
        )

        assert existing_tool.description == "updated"
        assert result["description"] == "updated"
        self.mock_llm_query_repo.commit.assert_called_once()

    def test_delete_tool_system_tool_fails(self):
        """Test that system tools cannot be deleted via API."""
        existing_tool = MagicMock(spec=Tool)
        existing_tool.tool_type = Tool.TYPE_SYSTEM
        self.mock_llm_query_repo.get_tool_by_id.return_value = existing_tool

        with pytest.raises(IAToolkitException) as exc:
            self.service.delete_tool(self.company_short_name, 1)

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION

    def test_system_document_search_returns_structured_payload(self):
        self.knowledge_base_service.search.return_value = [{
            "id": 1,
            "document_id": 10,
            "filename": "invoice.pdf",
            "url": "https://signed.example/invoice.pdf",
            "text": "Total amount is 1200",
            "meta": {"type": "invoice"},
            "chunk_meta": {"source_type": "table", "caption_text": "Invoice totals", "table_json": "{\"a\":1}"}
        }]

        handler = self.service.get_system_handler("iat_document_search")
        result = handler(
            company_short_name=self.company_short_name,
            query="total amount",
            collection="invoices",
            metadata_filter=[{"key": "doc.type", "value": "invoice"}]
        )

        assert result["status"] == "success"
        assert result["count"] == 1
        assert isinstance(result["chunks"], list)
        assert isinstance(result["chunks"][0]["chunk_meta"]["table_json"], dict)
        assert result["chunks"][0]["filename_link"] == "[invoice.pdf](https://signed.example/invoice.pdf)"
        assert "serialized_context" in result
        assert "[invoice.pdf](https://signed.example/invoice.pdf)" in result["serialized_context"]
        assert "Total amount is 1200" in result["serialized_context"]
        assert "table_json=" in result["serialized_context"]

    def test_system_image_search_returns_structured_payload(self):
        self.mock_visual_tool_service.image_search.return_value = {"status": "success", "count": 1, "results": [{}]}

        handler = self.service.get_system_handler("iat_image_search")
        result = handler(
            company_short_name=self.company_short_name,
            query="logo",
            collection="brand",
            metadata_filter=[{"key": "image.page", "value": 1}],
            n_results=3
        )

        self.mock_visual_tool_service.image_search.assert_called_once_with(
            company_short_name=self.company_short_name,
            query="logo",
            collection="brand",
            metadata_filter=[{"key": "image.page", "value": 1}],
            request_images=[],
            n_results=3,
            structured_output=True,
        )
        assert result["status"] == "success"

    def test_system_web_search_delegates_to_web_search_service(self):
        self.mock_web_search_service.search.return_value = {
            "status": "success",
            "provider": "brave",
            "count": 1,
            "results": [{"title": "A", "url": "https://example.com"}]
        }

        handler = self.service.get_system_handler("iat_web_search")
        result = handler(
            company_short_name=self.company_short_name,
            query="latest ai news",
            n_results=3,
            recency_days=2,
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
        )

        self.mock_web_search_service.search.assert_called_once_with(
            company_short_name=self.company_short_name,
            query="latest ai news",
            n_results=3,
            recency_days=2,
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
        )
        assert result["status"] == "success"
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
        result = self.service.get_tools_for_llm(self.mock_company)

        # Assert
        assert len(result) == 1
        assert result[0]['type'] == 'function'
        assert result[0]['name'] == 'tool1'
        assert result[0]['description'] == 'desc1'
        assert result[0]['parameters']['prop'] == 1
        assert result[0]['parameters']['additionalProperties'] is False
        assert result[0]['strict'] is True
