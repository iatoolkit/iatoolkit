# test_history_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.history_api_view import HistoryApiView
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-company"
MOCK_USER_IDENTIFIER = "user-123"

class TestHistoryView:
    """Tests for the refactored, web-only HistoryView."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a clean test environment before each test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()
        self.url = f'/{MOCK_COMPANY_SHORT_NAME}/api/history'

        # Mocks para los servicios inyectados
        self.mock_auth = MagicMock(spec=AuthService)
        self.mock_history_service = MagicMock(spec=HistoryManagerService)
        self.i8n_service = MagicMock(spec=I18nService)

        self.i8n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        # Registrar la vista con las dependencias correctas
        view_func = HistoryApiView.as_view(
            'history',
            auth_service=self.mock_auth,
            history_service=self.mock_history_service,
            i18n_service=self.i8n_service
        )
        self.app.add_url_rule('/<company_short_name>/api/history', view_func=view_func, methods=['POST'])

        self.mock_auth.verify.return_value = {"success": True, 'user_identifier': MOCK_USER_IDENTIFIER}

    def test_get_full_history_success(self):
        """
        Tests the happy path: user is authenticated, and history is fetched successfully.
        """
        # Simulate a successful response from the history service.
        mock_history_response = {
            'message': 'Historial obtenido correctamente',
            'history': [{'id': 1, 'question': 'What is AI?'}]
        }
        self.mock_history_service.get_full_history.return_value = mock_history_response

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 200
        assert response.json == mock_history_response

        # Verify that the session was checked and the history service was called with the correct user ID.
        self.mock_auth.verify.assert_called_once()
        self.mock_history_service.get_full_history.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_USER_IDENTIFIER
        )


    def test_get_full_history_when_auth_error(self):
        self.mock_auth.verify.return_value = {"success": False, "error_message": "Invalid API Key", "status_code": 401}

        response = self.client.post(self.url)

        assert response.status_code == 401
        assert "Invalid API Key" in response.json['error_message']

    def test_get_full_history_handles_service_error(self):
        self.mock_history_service.get_full_history.return_value = {
            'error': 'Database query failed'
        }

        response = self.client.post(self.url)

        assert response.status_code == 400
        assert response.json['error_message'] == 'Database query failed'
        self.mock_history_service.get_full_history.assert_called_once()

    def test_get_full_history_handles_unexpected_exception(self):
        """
        Tests that the view returns a 500 error if an unexpected exception occurs.
        """
        self.mock_history_service.get_full_history.side_effect = Exception("A critical error occurred")
        response = self.client.post(self.url)

        assert response.status_code == 500
        assert "error_message" in response.json
        assert 'translated:errors.general.unexpected_error' == response.json['error_message']