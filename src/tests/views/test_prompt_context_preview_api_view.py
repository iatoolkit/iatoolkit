from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.query_service import QueryService
from iatoolkit.views.prompt_context_preview_api_view import PromptContextPreviewApiView


class TestPromptContextPreviewApiView:
    @staticmethod
    def create_app():
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.auth_service = MagicMock(spec=AuthService)
        self.query_service = MagicMock(spec=QueryService)
        self.auth_service.verify_for_company.return_value = {
            "success": True,
            "user_identifier": "owner@example.com",
            "user_role": "owner",
        }

        view = PromptContextPreviewApiView.as_view(
            "prompt_context_preview_api",
            auth_service=self.auth_service,
            query_service=self.query_service,
        )
        self.app.add_url_rule(
            "/<string:company_short_name>/api/admin/prompts/<string:prompt_name>/context-preview",
            view_func=view,
            methods=["POST"],
        )

    def test_post_returns_context_preview(self):
        self.query_service.preview_prompt_context.return_value = {
            "prompt_name": "research_agent",
            "execution_mode": "agentic",
            "tool_names": ["iat_sql_query"],
            "runtime_context": "Agent runtime context",
            "final_input_preview": "### Agent Runtime Context\nAgent runtime context",
            "selected_system_prompt_keys": ["core_identity", "sql_core"],
        }

        response = self.client.post(
            "/acme/api/admin/prompts/research_agent/context-preview",
            json={"client_data": {"topic": "ventas"}},
        )

        assert response.status_code == 200
        assert response.json["execution_mode"] == "agentic"
        assert response.json["tool_names"] == ["iat_sql_query"]
        self.query_service.preview_prompt_context.assert_called_once_with(
            company_short_name="acme",
            user_identifier="owner@example.com",
            prompt_name="research_agent",
            client_data={"topic": "ventas"},
            question="",
        )

    def test_post_requires_admin_role(self):
        self.auth_service.verify_for_company.return_value = {
            "success": True,
            "user_identifier": "user@example.com",
            "user_role": "user",
        }

        response = self.client.post("/acme/api/admin/prompts/research_agent/context-preview", json={})

        assert response.status_code == 403
        self.query_service.preview_prompt_context.assert_not_called()

    def test_post_forwards_preview_errors(self):
        self.query_service.preview_prompt_context.return_value = {
            "error": True,
            "status_code": 400,
            "error_message": "Agent prompt 'research_agent' has tool 'iat_sql_query' enabled but no SQL sources are bound.",
        }

        response = self.client.post("/acme/api/admin/prompts/research_agent/context-preview", json={})

        assert response.status_code == 400
        assert "iat_sql_query" in response.json["error"]
