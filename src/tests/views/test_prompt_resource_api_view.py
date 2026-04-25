from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.prompt_resource_service import PromptResourceService
from iatoolkit.views.prompt_resource_api_view import PromptResourceApiView


class TestPromptResourceApiView:
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
        self.prompt_resource_service = MagicMock(spec=PromptResourceService)
        self.auth_service.verify_for_company.return_value = {
            "success": True,
            "user_identifier": "owner@example.com",
            "user_role": "owner",
        }

        view = PromptResourceApiView.as_view(
            "prompt_resources_api",
            auth_service=self.auth_service,
            prompt_resource_service=self.prompt_resource_service,
        )
        self.app.add_url_rule(
            "/<string:company_short_name>/api/admin/prompts/<string:prompt_name>/resources",
            view_func=view,
            methods=["GET", "PUT"],
        )

    def test_get_returns_prompt_resources(self):
        self.prompt_resource_service.get_prompt_resource_bindings.return_value = {
            "data": {"items": [{"resource_type": "sql_source", "resource_key": "crm"}]}
        }

        response = self.client.get("/acme/api/admin/prompts/research_agent/resources")

        assert response.status_code == 200
        assert response.json["items"][0]["resource_key"] == "crm"
        self.prompt_resource_service.get_prompt_resource_bindings.assert_called_once_with("acme", "research_agent")

    def test_put_forwards_authenticated_actor(self):
        self.prompt_resource_service.set_prompt_resource_bindings.return_value = {
            "data": {"items": [{"resource_type": "rag_collection", "resource_key": "Legal"}]}
        }

        response = self.client.put(
            "/acme/api/admin/prompts/research_agent/resources",
            json={"items": [{"resource_type": "rag_collection", "resource_key": "Legal"}]},
        )

        assert response.status_code == 200
        self.prompt_resource_service.set_prompt_resource_bindings.assert_called_once_with(
            "acme",
            "research_agent",
            {"items": [{"resource_type": "rag_collection", "resource_key": "Legal"}]},
            actor_identifier="owner@example.com",
        )

    def test_get_requires_admin_role(self):
        self.auth_service.verify_for_company.return_value = {
            "success": True,
            "user_identifier": "user@example.com",
            "user_role": "user",
        }

        response = self.client.get("/acme/api/admin/prompts/research_agent/resources")

        assert response.status_code == 403
        self.prompt_resource_service.get_prompt_resource_bindings.assert_not_called()
