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
        self.url = '/test_company/api/prompts'

        # Default to successful authentication
        self.auth_service.verify.return_value = {'success': True,
                                                 'user_identifier': 'test_user_id',}

        # Register the view with mocked dependencies
        prompt_view = PromptApiView.as_view("prompt",
                                         auth_service=self.auth_service,
                                         prompt_service=self.prompt_service)
        self.app.add_url_rule('/<company_short_name>/api/prompts',
                              view_func=prompt_view,
                              methods=["GET"])

    def test_get_when_auth_error(self):
        """Test response when authentication fails."""
        self.auth_service.verify.return_value = {
            'success': False,
            'error_message': 'Authentication token is invalid',
            "status_code": 401,
        }

        response = self.client.get(self.url)

        assert response.status_code == 401
        assert response.json['error_message'] == 'Authentication token is invalid'
        self.prompt_service.get_user_prompts.assert_not_called()

    def test_get_when_service_returns_error(self):
        """Test response when the prompt service returns a logical error."""
        self.prompt_service.get_user_prompts.return_value = {
            'error': 'Company not configured for prompts'
        }

        response = self.client.get(self.url)

        assert response.status_code == 402
        assert response.json['error_message'] == 'Company not configured for prompts'
        self.auth_service.verify.assert_called_once()
        self.prompt_service.get_user_prompts.assert_called_once_with('test_company')

    def test_get_when_service_raises_exception(self):
        """Test response when the prompt service raises an unhandled exception."""
        self.prompt_service.get_user_prompts.side_effect = Exception('Unexpected database error')

        response = self.client.get(self.url)

        assert response.status_code == 500
        assert response.json['error_message'] == 'Unexpected database error'

    def test_get_success(self):
        """Test a successful request to retrieve prompts."""
        mock_response = {
            'message': [
                {'prompt': 'sales_prompt', 'description': 'A prompt for sales questions'},
                {'prompt': 'support_prompt', 'description': 'A prompt for support inquiries'}
            ]
        }
        self.prompt_service.get_user_prompts.return_value = mock_response

        response = self.client.get(self.url)

        assert response.status_code == 200
        assert response.json == mock_response
        self.auth_service.verify.assert_called_once()
        self.prompt_service.get_user_prompts.assert_called_once_with('test_company')

