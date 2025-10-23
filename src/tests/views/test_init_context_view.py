import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.init_context_api_view import InitContextApiView
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.user_session_context_service import UserSessionContextService

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-comp"
MOCK_EXTERNAL_USER_ID = "api-user-123"
MOCK_LOCAL_USER_ID = "456"


class TestInitContextApiView:
    """
    Tests for the InitContextApiView, which forces a context rebuild.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a clean test environment before each test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks for injected services
        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_profile_service = MagicMock(spec=ProfileService)

        # Create a mock for session_context and attach it to query_service
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_query_service.session_context = self.mock_session_context

        # Register the view with its dependencies
        view_func = InitContextApiView.as_view(
            'init_context_api',
            auth_service=self.mock_auth_service,
            query_service=self.mock_query_service,
            profile_service=self.mock_profile_service
        )
        self.app.add_url_rule('/api/<company_short_name>/init-context', view_func=view_func, methods=['POST'])

    def test_rebuild_for_web_user_with_session(self):
        """
        Tests the flow for a logged-in web user (local or external) clicking the button.
        """
        # Arrange
        # AuthService finds a user in the Flask session.
        self.mock_auth_service.verify.return_value = {
            "success": True,
            "user_identifier": MOCK_LOCAL_USER_ID,
            "company_short_name": MOCK_COMPANY_SHORT_NAME
        }

        # Act
        response = self.client.post(f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context')

        # Assert
        assert response.status_code == 200
        assert response.json['status'] == 'OK'

        # Verify the sequence was called with the user ID from the session.
        self.mock_query_service.session_context.clear_all_context.assert_called_once_with(MOCK_COMPANY_SHORT_NAME,
                                                                                          MOCK_LOCAL_USER_ID)
        self.mock_query_service.prepare_context.assert_called_once_with(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                                                        user_identifier=MOCK_LOCAL_USER_ID)
        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_LOCAL_USER_ID)

    def test_rebuild_for_api_user_with_api_key(self):
        """
        Tests the flow for a pure API call using an API Key.
        """
        # Arrange
        # AuthService finds no session, but authenticates the API Key successfully.
        self.mock_auth_service.verify.return_value = \
            {"success": True,
             "company_short_name": MOCK_COMPANY_SHORT_NAME,
             "user_identifier": MOCK_EXTERNAL_USER_ID}

        # Act
        response = self.client.post(
            f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        # Assert
        assert response.status_code == 200
        assert response.json['status'] == 'OK'

        # Verify the sequence was called with the user ID from the JSON payload.
        self.mock_query_service.session_context.clear_all_context.assert_called_once_with(MOCK_COMPANY_SHORT_NAME,
                                                                                          MOCK_EXTERNAL_USER_ID)
        self.mock_query_service.prepare_context.assert_called_once_with(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                                                        user_identifier=MOCK_EXTERNAL_USER_ID)
        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_EXTERNAL_USER_ID)

    def test_rebuild_fails_if_auth_fails(self):
        """
        Tests that the view returns a 401 if authentication fails.
        """
        # Arrange
        self.mock_auth_service.verify.return_value = {"success": False, "error_message": "Invalid API Key",
                                                      "status_code": 401}

        # Act
        response = self.client.post(f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context', json={'external_user_id': 'any'})

        # Assert
        assert response.status_code == 401
        assert "Invalid API Key" in response.json['error']
        self.mock_query_service.prepare_context.assert_not_called()

    def test_rebuild_fails_if_no_user_is_identified(self):
        """
        Tests that the view returns a 400 if no user can be identified.
        """
        # Arrange
        # Auth succeeds (e.g., valid API key), but no user ID in session or payload.
        self.mock_auth_service.verify.return_value = {"success": True}

        # Act
        response = self.client.post(f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context', json={})  # Empty payload

        # Assert
        assert response.status_code == 400
        assert "Could not identify user" in response.json['error']