# tests/views/test_tool_api_view.py

import pytest
from unittest.mock import MagicMock
from flask import Flask
from iatoolkit.views.tool_api_view import ToolApiView
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.tool_service import ToolService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import Tool
from iatoolkit.common.exceptions import IAToolkitException

class TestToolApiView:
    MOCK_COMPANY = "acme"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.client = self.app.test_client()

        # Mocks
        self.mock_auth = MagicMock(spec=AuthService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_tool_service = MagicMock(spec=ToolService)
        self.mock_dispatcher = MagicMock(spec=Dispatcher)

        # Default Auth Success
        self.mock_auth.verify.return_value = {"success": True, "status_code": 200}

        # View setup
        view = ToolApiView.as_view(
            'tool_api',
            auth_service=self.mock_auth,
            profile_repo=self.mock_profile_repo,
            tool_service=self.mock_tool_service,
            dispatcher=self.mock_dispatcher
        )

        # Route registration for testing
        self.app.add_url_rule(
            '/<company_short_name>/api/tools',
            view_func=view,
            methods=['GET', 'POST']
        )
        self.app.add_url_rule(
            '/<company_short_name>/api/tools/<int:tool_id>',
            view_func=view,
            methods=['GET', 'PUT', 'DELETE']
        )
        self.app.add_url_rule(
            '/<company_short_name>/api/tools/execute',
            view_func=view,
            methods=['POST'],
            defaults={'action': 'execute'}
        )

    # --- GET (List & Detail) ---

    def test_list_tools_success(self):
        """GET /api/tools should return list of tools."""
        expected_tools = [{"id": 1, "name": "tool1"}]
        self.mock_tool_service.list_tools.return_value = expected_tools

        resp = self.client.get(f'/{self.MOCK_COMPANY}/api/tools')

        assert resp.status_code == 200
        assert resp.json == expected_tools
        self.mock_tool_service.list_tools.assert_called_with(self.MOCK_COMPANY)

    def test_get_tool_detail_success(self):
        """GET /api/tools/<id> should return tool detail."""
        expected_tool = {"id": 1, "name": "tool1"}
        self.mock_tool_service.get_tool.return_value = expected_tool

        resp = self.client.get(f'/{self.MOCK_COMPANY}/api/tools/1')

        assert resp.status_code == 200
        assert resp.json == expected_tool
        self.mock_tool_service.get_tool.assert_called_with(self.MOCK_COMPANY, 1)

    def test_get_tool_not_found(self):
        """GET /api/tools/<id> should return 404 if tool missing."""
        self.mock_tool_service.get_tool.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.NOT_FOUND, "Tool not found"
        )

        resp = self.client.get(f'/{self.MOCK_COMPANY}/api/tools/99')
        assert resp.status_code == 404

    def test_list_tools_auth_fail(self):
        """Should return 401 if auth fails."""
        self.mock_auth.verify.return_value = {"success": False, "status_code": 401}

        resp = self.client.get(f'/{self.MOCK_COMPANY}/api/tools')
        assert resp.status_code == 401

    # --- POST (Create) ---

    def test_create_tool_success(self):
        """POST /api/tools should create tool and return 201."""
        payload = {"name": "new_tool", "description": "desc"}
        self.mock_tool_service.create_tool.return_value = {**payload, "id": 5}

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools', json=payload)

        assert resp.status_code == 201
        assert resp.json['id'] == 5
        self.mock_tool_service.create_tool.assert_called_with(self.MOCK_COMPANY, payload)

    def test_create_tool_duplicate(self):
        """POST should return 409 on duplicate."""
        self.mock_tool_service.create_tool.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.DUPLICATE_ENTRY, "Exists"
        )

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools', json={})
        assert resp.status_code == 409

    def test_create_tool_missing_param(self):
        """POST should return 400 on validation error."""
        self.mock_tool_service.create_tool.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.MISSING_PARAMETER, "Missing name"
        )

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools', json={})
        assert resp.status_code == 400

    # --- PUT (Update) ---

    def test_update_tool_success(self):
        """PUT /api/tools/<id> should update and return 200."""
        payload = {"description": "updated"}
        self.mock_tool_service.update_tool.return_value = {"id": 1, "description": "updated"}

        resp = self.client.put(f'/{self.MOCK_COMPANY}/api/tools/1', json=payload)

        assert resp.status_code == 200
        assert resp.json['description'] == "updated"
        self.mock_tool_service.update_tool.assert_called_with(self.MOCK_COMPANY, 1, payload)

    def test_update_system_tool_fails(self):
        """PUT should return 409 if trying to update system tool."""
        self.mock_tool_service.update_tool.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.INVALID_OPERATION, "Cannot modify System Tools"
        )

        resp = self.client.put(f'/{self.MOCK_COMPANY}/api/tools/1', json={})
        assert resp.status_code == 409

    # --- DELETE ---

    def test_delete_tool_success(self):
        """DELETE /api/tools/<id> should return 200."""
        resp = self.client.delete(f'/{self.MOCK_COMPANY}/api/tools/1')

        assert resp.status_code == 200
        assert resp.json['status'] == 'success'
        self.mock_tool_service.delete_tool.assert_called_with(self.MOCK_COMPANY, 1)

    def test_delete_tool_exception(self):
        """DELETE should handle exceptions (e.g. system tool)."""
        self.mock_tool_service.delete_tool.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.INVALID_OPERATION, "No delete"
        )

        resp = self.client.delete(f'/{self.MOCK_COMPANY}/api/tools/1')
        assert resp.status_code == 409

    # --- EXECUTE NATIVE ---

    def test_execute_native_tool_success(self):
        """POST /api/tools/execute should run a NATIVE tool through dispatcher."""
        tool_def = MagicMock()
        tool_def.tool_type = Tool.TYPE_NATIVE
        self.mock_tool_service.get_tool_definition.return_value = tool_def
        self.mock_dispatcher.dispatch.return_value = {"status": "ok"}

        payload = {
            "tool_name": "identity_risk",
            "kwargs": {"document": "abc"}
        }

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools/execute', json=payload)

        assert resp.status_code == 200
        assert resp.json["result"] == "success"
        assert resp.json["tool_name"] == "identity_risk"
        assert resp.json["data"] == {"status": "ok"}
        self.mock_tool_service.get_tool_definition.assert_called_with(self.MOCK_COMPANY, "identity_risk")
        self.mock_dispatcher.dispatch.assert_called_with(
            company_short_name=self.MOCK_COMPANY,
            function_name="identity_risk",
            document="abc"
        )

    def test_execute_requires_tool_name(self):
        """POST /api/tools/execute should return 400 when tool_name is missing."""
        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools/execute', json={"kwargs": {}})
        assert resp.status_code == 400

    def test_execute_requires_native_tool_type(self):
        """POST /api/tools/execute should reject non-native tools."""
        tool_def = MagicMock()
        tool_def.tool_type = Tool.TYPE_SYSTEM
        self.mock_tool_service.get_tool_definition.return_value = tool_def

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools/execute', json={"tool_name": "iat_document_search"})
        assert resp.status_code == 409

    def test_execute_tool_not_found(self):
        """POST /api/tools/execute should return 404 if tool does not exist."""
        self.mock_tool_service.get_tool_definition.return_value = None

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools/execute', json={"tool_name": "missing_tool"})
        assert resp.status_code == 404

    def test_execute_kwargs_must_be_object(self):
        """POST /api/tools/execute should validate kwargs format."""
        tool_def = MagicMock()
        tool_def.tool_type = Tool.TYPE_NATIVE
        self.mock_tool_service.get_tool_definition.return_value = tool_def

        resp = self.client.post(f'/{self.MOCK_COMPANY}/api/tools/execute', json={
            "tool_name": "identity_risk",
            "kwargs": []
        })
        assert resp.status_code == 400
