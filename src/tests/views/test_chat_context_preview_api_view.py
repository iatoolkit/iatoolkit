from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.query_service import QueryService
from iatoolkit.views.chat_context_preview_api_view import ChatContextPreviewApiView


class TestChatContextPreviewApiView:
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

        view = ChatContextPreviewApiView.as_view(
            "chat_context_preview_api",
            auth_service=self.auth_service,
            query_service=self.query_service,
        )
        self.app.add_url_rule(
            "/<string:company_short_name>/api/admin/context-preview/chat",
            view_func=view,
            methods=["GET"],
        )

    def test_get_returns_chat_context_preview(self):
        self.query_service.preview_chat_context.return_value = {
            "mode": "chat",
            "execution_mode": "conversational",
            "tool_names": ["crm_lookup"],
            "context": "Chat System Context",
            "selected_system_prompt_keys": ["core_identity"],
        }

        response = self.client.get("/acme/api/admin/context-preview/chat")

        assert response.status_code == 200
        assert response.json["mode"] == "chat"
        self.query_service.preview_chat_context.assert_called_once_with(
            company_short_name="acme",
            user_identifier="owner@example.com",
            question="",
        )

    def test_get_requires_admin_role(self):
        self.auth_service.verify_for_company.return_value = {
            "success": True,
            "user_identifier": "user@example.com",
            "user_role": "user",
        }

        response = self.client.get("/acme/api/admin/context-preview/chat")

        assert response.status_code == 403
        self.query_service.preview_chat_context.assert_not_called()
