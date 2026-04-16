# tests/views/test_embedding_api_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock
import json

# Import the view and service mocks
from iatoolkit.views.embedding_api_view import EmbeddingApiView
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.auth_service import AuthService

# --- Test Constants ---
MOCK_COMPANY_SHORT_NAME = "acme-corp"
MOCK_USER_IDENTIFIER = "user-test-123"
MOCK_TEXT_TO_EMBED = "This is a test sentence."
MOCK_EMBEDDING_B64 = "Abcde12345=="
MOCK_MODEL_NAME = "test-model-v1"


class TestEmbeddingApiView:
    """Test suite for the EmbeddingApiView endpoint."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a clean Flask test environment before each test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()
        self.url = f'/{MOCK_COMPANY_SHORT_NAME}/api/embedding'

        # Create mocks for the injected services
        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_embedding_service = MagicMock(spec=EmbeddingService)

        # Register the view with the Flask app, injecting the mocks
        view_func = EmbeddingApiView.as_view(
            'embedding_api',
            auth_service=self.mock_auth_service,
            embedding_service=self.mock_embedding_service
        )
        self.app.add_url_rule(
            '/<company_short_name>/api/embedding',
            view_func=view_func,
            methods=['POST']
        )

        # Default successful authentication for most tests
        self.mock_auth_service.verify_for_company.return_value = {
            "success": True,
            'user_identifier': MOCK_USER_IDENTIFIER
        }

    def test_generate_embedding_success(self):
        """
        Tests the happy path: user is authenticated, input is valid,
        and the service returns a successful embedding.
        """
        # Arrange: Configure the mock service to return expected values
        self.mock_embedding_service.embed_text.return_value = MOCK_EMBEDDING_B64
        self.mock_embedding_service.get_model_name.return_value = MOCK_MODEL_NAME
        payload = {"text": MOCK_TEXT_TO_EMBED}

        # Act: Make the POST request
        response = self.client.post(self.url, json=payload)

        # Assert: Check the response and service calls
        assert response.status_code == 200
        assert response.json == {
            "embedding": MOCK_EMBEDDING_B64,
            "model": MOCK_MODEL_NAME
        }

        self.mock_auth_service.verify_for_company.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            anonymous=True,
        )
        self.mock_embedding_service.embed_text.assert_called_once_with(
            text=MOCK_TEXT_TO_EMBED,
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            to_base64=True
        )
        self.mock_embedding_service.get_model_name.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)

    def test_generate_embedding_auth_failure(self):
        """
        Tests that the endpoint returns a 401 Unauthorized error
        when the auth service fails verification.
        """
        # Arrange: Override the auth mock to simulate failure
        self.mock_auth_service.verify_for_company.return_value = {
            "success": False,
            "error": "Invalid session",
            "status_code": 401
        }
        payload = {"text": "any text"}

        # Act
        response = self.client.post(self.url, json=payload)

        # Assert
        assert response.status_code == 401
        assert response.json['error'] == "Invalid session"
        self.mock_embedding_service.embed_text.assert_not_called()

    def test_generate_embedding_not_json(self):
        """Tests that the endpoint returns a 400 error if the request body is not JSON."""
        # Act
        response = self.client.post(self.url, data="this is not json")

        # Assert
        assert response.status_code == 400
        assert response.json['error'] == "Request must be JSON"
        self.mock_embedding_service.embed_text.assert_not_called()

    def test_generate_embedding_missing_text_key(self):
        """Tests that the endpoint returns a 400 error if the 'text' key is missing from the JSON payload."""
        # Arrange
        payload = {"wrong_key": "some value"}

        # Act
        response = self.client.post(self.url, json=payload)

        # Assert
        assert response.status_code == 400
        assert response.json['error'] == "The 'text' key is required."
        self.mock_embedding_service.embed_text.assert_not_called()

    def test_generate_embedding_unexpected_service_exception(self):
        """
        Tests that the view returns a 500 internal server error if the
        embedding service raises an unexpected exception.
        """
        # Arrange
        self.mock_embedding_service.embed_text.side_effect = Exception("Model failed to load")
        payload = {"text": MOCK_TEXT_TO_EMBED}

        # Act
        response = self.client.post(self.url, json=payload)

        # Assert
        assert response.status_code == 500
        assert "internal error" in response.json['error']
