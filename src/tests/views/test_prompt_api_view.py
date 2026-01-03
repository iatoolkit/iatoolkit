# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from flask import Flask
from iatoolkit.views.prompt_api_view import PromptApiView
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.profile_service import ProfileService


class TestPromptView:
    @staticmethod
    def create_app():
        """Creates a Flask app instance for testing."""
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up the test client and mock dependencies for each test."""
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.prompt_service = MagicMock(spec=PromptService)
        self.auth_service = MagicMock(spec=AuthService)
        self.profile_service = MagicMock(spec=ProfileService)
        self.llm_query_repo = MagicMock(spec=LLMQueryRepo)

        self.company_short_name = 'test_company'
        self.base_url = f'/{self.company_short_name}/api/prompts'

        # Default to successful authentication
        self.auth_service.verify.return_value = {'success': True,
                                                 'user_identifier': 'test_user_id',}

        # Register the view with mocked dependencies
        prompt_view = PromptApiView.as_view("prompt",
                                            auth_service=self.auth_service,
                                            prompt_service=self.prompt_service,
                                            llm_query_repo=self.llm_query_repo,
                                            profile_service=self.profile_service,)

        # Route for list
        self.app.add_url_rule('/<company_short_name>/api/prompts',
                              view_func=prompt_view,
                              methods=["GET", "POST"],
                              defaults={'prompt_name': None})

        # Route for details/update
        self.app.add_url_rule('/<company_short_name>/api/prompts/<prompt_name>',
                              view_func=prompt_view,
                              methods=["GET", "PUT", "POST", "DELETE"])

    # --- GET List Tests ---

    def test_get_list_when_auth_error(self):
        """Test list response when authentication fails."""
        self.auth_service.verify.return_value = {
            'success': False,
            'error_message': 'Authentication token is invalid',
            "status_code": 401,
        }

        response = self.client.get(self.base_url)

        assert response.status_code == 401
        assert response.json['error_message'] == 'Authentication token is invalid'
        self.prompt_service.get_user_prompts.assert_not_called()

    def test_get_list_success(self):
        """Test a successful request to retrieve all prompts."""
        mock_response = {
            'message': [
                {'prompt': 'sales_prompt', 'description': 'Sales'}
            ]
        }
        # Check default call
        self.prompt_service.get_user_prompts.return_value = mock_response
        response = self.client.get(self.base_url)
        assert response.status_code == 200
        self.prompt_service.get_user_prompts.assert_called_with(self.company_short_name, include_all=False)

    def test_get_list_admin_all(self):
        """Test retrieving all prompts (admin view)."""
        self.prompt_service.get_user_prompts.return_value = {}
        response = self.client.get(f"{self.base_url}?all=true")
        assert response.status_code == 200
        self.prompt_service.get_user_prompts.assert_called_with(self.company_short_name, include_all=True)

    # --- POST Tests ---
    def test_post_create_prompt(self):
        """Test creating a new prompt via POST."""
        payload = {"name": "new_prompt", "description": "desc"}
        response = self.client.post(self.base_url, json=payload)

        assert response.status_code == 200
        self.prompt_service.save_prompt.assert_called_once_with(
            self.company_short_name, "new_prompt", payload
        )

    # --- DELETE Tests ---
    def test_delete_prompt(self):
        """Test deleting a prompt."""
        response = self.client.delete(f"{self.base_url}/old_prompt")

        assert response.status_code == 200
        self.prompt_service.delete_prompt.assert_called_once_with(
            self.company_short_name, "old_prompt"
        )

    # --- GET Detail Tests ---

    def test_get_detail_success(self):
        """Test retrieving a specific prompt's details and content."""
        prompt_name = "sales_prompt"
        mock_prompt_obj = MagicMock()
        mock_prompt_obj.to_dict.return_value = {"name": prompt_name, "active": True}

        self.llm_query_repo.get_prompt_by_name.return_value = mock_prompt_obj
        self.prompt_service.get_prompt_content.return_value = "Hello {{ name }}"

        response = self.client.get(f"{self.base_url}/{prompt_name}")

        assert response.status_code == 200
        data = response.json
        assert data['meta']['name'] == prompt_name
        assert data['content'] == "Hello {{ name }}"

        self.llm_query_repo.get_prompt_by_name.assert_called_once()
        self.prompt_service.get_prompt_content.assert_called_once()

    # --- PUT Tests ---

    def test_put_success(self):
        """Test updating a prompt successfully."""
        prompt_name = "sales_prompt"
        payload = {
            "content": "New content",
            "description": "New desc",
            "custom_fields": []
        }

        response = self.client.put(f"{self.base_url}/{prompt_name}", json=payload)

        assert response.status_code == 200
        assert response.json['status'] == 'success'

        self.prompt_service.save_prompt.assert_called_once_with(
            self.company_short_name,
            prompt_name,
            payload
        )

    def test_put_auth_error(self):
        """Test that PUT is protected by authentication."""
        self.auth_service.verify.return_value = {"success": False, "status_code": 401}

        response = self.client.put(f"{self.base_url}/any_prompt", json={})

        assert response.status_code == 401
        self.prompt_service.save_prompt.assert_not_called()