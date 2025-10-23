# test_history_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.history_api_view import HistoryApiView
from iatoolkit.services.history_service import HistoryService
from iatoolkit.services.profile_service import ProfileService

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
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_history_service = MagicMock(spec=HistoryService)

        # Registrar la vista con las dependencias correctas
        view_func = HistoryApiView.as_view(
            'history',
            profile_service=self.mock_profile_service,
            history_service=self.mock_history_service
        )
        self.app.add_url_rule('/<company_short_name>/api/history', view_func=view_func, methods=['POST'])

    def test_get_history_success(self):
        """
        Tests the happy path: user is authenticated, and history is fetched successfully.
        """
        # Arrange
        # 1. Simulate a valid, authenticated web session.
        self.mock_profile_service.get_current_session_info.return_value = {
            "user_identifier": MOCK_USER_IDENTIFIER
        }
        # 2. Simulate a successful response from the history service.
        mock_history_response = {
            'message': 'Historial obtenido correctamente',
            'history': [{'id': 1, 'question': 'What is AI?'}]
        }
        self.mock_history_service.get_history.return_value = mock_history_response

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 200
        assert response.json == mock_history_response

        # Verify that the session was checked and the history service was called with the correct user ID.
        self.mock_profile_service.get_current_session_info.assert_called_once()
        self.mock_history_service.get_history.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_USER_IDENTIFIER
        )

    def test_get_history_fails_if_not_authenticated(self):
        """
        Tests that the view returns a 401 error if no valid web session is found.
        """
        # Arrange
        # Simulate an empty session (user not logged in).
        self.mock_profile_service.get_current_session_info.return_value = {}

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 401
        assert "Usuario no autenticado" in response.json['error_message']
        self.mock_history_service.get_history.assert_not_called()

    def test_get_history_handles_service_error(self):
        """
        Tests that the view returns a 400 error if the history service itself reports an error.
        """
        # Arrange
        self.mock_profile_service.get_current_session_info.return_value = {
            "user_identifier": MOCK_USER_IDENTIFIER
        }
        self.mock_history_service.get_history.return_value = {
            'error': 'Database query failed'
        }

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 400
        assert response.json['error_message'] == 'Database query failed'
        self.mock_history_service.get_history.assert_called_once()

    def test_get_history_handles_unexpected_exception(self):
        """
        Tests that the view returns a 500 error if an unexpected exception occurs.
        """
        # Arrange
        self.mock_profile_service.get_current_session_info.return_value = {
            "user_identifier": MOCK_USER_IDENTIFIER
        }
        self.mock_history_service.get_history.side_effect = Exception("A critical error occurred")

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 500
        assert "error_message" in response.json
        assert "Ha ocurrido un error inesperado" in response.json['error_message']