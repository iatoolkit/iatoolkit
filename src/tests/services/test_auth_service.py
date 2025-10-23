import pytest
from unittest.mock import MagicMock
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import ApiKey, Company
# Import Flask to create a test app context for requests
from flask import Flask


class TestAuthService:
    """Tests for the new centralized AuthService."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a consistent, mocked environment for each test."""
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.service = AuthService(profile_service=self.mock_profile_service)
        # Create a minimal Flask app instance to create request contexts
        self.app = Flask(__name__)
        self.app.testing = True

    def test_verify_success_with_flask_session(self):
        """
        Tests that verify() succeeds and returns user info if a valid Flask session is found.
        It should NOT check for an API Key if a session exists.
        """
        # Arrange
        session_info = {
            "user_identifier": "123",
            "company_short_name": "testco",
            "profile": {"id": 123, "email": "local@user.com"}
        }
        self.mock_profile_service.get_current_session_info.return_value = session_info

        # Act
        # A request context is not strictly needed here, but it's good practice
        with self.app.test_request_context():
            result = self.service.verify()

        # Assert
        assert result['success'] is True
        assert result['user_identifier'] == "123"
        assert result['company_short_name'] == "testco"
        # Crucially, verify that the API Key check was skipped
        self.mock_profile_service.get_active_api_key_entry.assert_not_called()

    def test_verify_success_with_api_key(self):
        """
        Tests that verify() succeeds if no session exists but a valid API key is provided in headers.
        """
        # Arrange
        # No Flask session
        self.mock_profile_service.get_current_session_info.return_value = {}

        # A valid API key is found
        mock_company = Company(id=1, short_name="apico")
        mock_api_key_entry = ApiKey(key="valid-api-key")
        mock_api_key_entry.company = mock_company
        self.mock_profile_service.get_active_api_key_entry.return_value = mock_api_key_entry

        # Act
        # We must wrap the call in a request context to simulate the headers
        with self.app.test_request_context(headers={'Authorization': 'Bearer valid-api-key'}):
            result = self.service.verify()

        # Assert
        assert result['success'] is True
        assert result['company_short_name'] == "apico"
        assert result['user_identifier'] == ""
        self.mock_profile_service.get_active_api_key_entry.assert_called_once_with("valid-api-key")

    def test_verify_fails_with_invalid_api_key(self):
        """
        Tests that verify() fails if the provided API key is invalid.
        """
        # Arrange
        self.mock_profile_service.get_current_session_info.return_value = {}
        self.mock_profile_service.get_active_api_key_entry.return_value = None  # Key not found

        # Act
        with self.app.test_request_context(headers={'Authorization': 'Bearer valid-api-key'}):
            result = self.service.verify()

        # Assert
        assert result['success'] is False
        assert result['status_code'] == 401
        assert "Invalid or inactive API Key" in result['error']

    def test_verify_fails_with_no_credentials(self):
        """
        Tests that verify() fails if no session or API key is provided.
        """
        # Arrange
        self.mock_profile_service.get_current_session_info.return_value = {}

        # Act
        with self.app.test_request_context():  # No headers provided
            result = self.service.verify()

        # Assert
        assert result['success'] is False
        assert result['status_code'] == 401
        assert "No session cookie or API Key provided" in result['error']
