# tests/views/test_help_content_api_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.help_content_api_view import HelpContentApiView
from iatoolkit.services.help_content_service import HelpContentService
from iatoolkit.services.auth_service import AuthService

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "sample-company"
MOCK_USER_IDENTIFIER = "user-test-123"

class TestHelpContentApiView:
    """Tests para la vista HelpContentApiView."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura un entorno de prueba limpio antes de cada test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()
        self.url = f'/{MOCK_COMPANY_SHORT_NAME}/api/help-content'

        # Mocks para los servicios inyectados
        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_help_content_service = MagicMock(spec=HelpContentService)

        # Registrar la vista con las dependencias mockeadas
        view_func = HelpContentApiView.as_view(
            'help_content',
            auth_service=self.mock_auth_service,
            help_content_service=self.mock_help_content_service
        )
        self.app.add_url_rule('/<company_short_name>/api/help-content', view_func=view_func, methods=['POST'])

        # Por defecto, la autenticación es exitosa en los tests
        self.mock_auth_service.verify.return_value = {"success": True, 'user_identifier': MOCK_USER_IDENTIFIER}

    def test_get_content_success(self):
        """
        Prueba el caso exitoso: usuario autenticado y el contenido se obtiene correctamente.
        """
        # Arrange: Simula una respuesta exitosa del servicio de ayuda
        mock_help_response = {
            'example_questions': [{'category': 'Ventas', 'questions': ['Pregunta 1']}]
        }
        self.mock_help_content_service.get_content.return_value = mock_help_response

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 200
        assert response.json == mock_help_response

        # Verifica que se llamó al servicio de autenticación y al de ayuda con los parámetros correctos
        self.mock_auth_service.verify.assert_called_once()
        self.mock_help_content_service.get_content.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME
        )

    def test_get_content_when_auth_error(self):
        """
        Prueba que la vista devuelve un error de autenticación si el servicio de auth falla.
        """
        # Arrange
        self.mock_auth_service.verify.return_value = {"success": False, "error_message": "Token inválido", "status_code": 401}

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 401
        assert "Token inválido" in response.json['error_message']
        self.mock_help_content_service.get_content.assert_not_called()

    def test_get_content_handles_service_error(self):
        """
        Prueba que la vista maneja un error controlado devuelto por el servicio de ayuda.
        """
        # Arrange
        self.mock_help_content_service.get_content.return_value = {
            'error': 'El archivo de contenido está corrupto'
        }

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 400
        assert response.json['error_message'] == 'El archivo de contenido está corrupto'
        self.mock_help_content_service.get_content.assert_called_once()

    def test_get_content_handles_unexpected_exception(self):
        """
        Prueba que la vista devuelve un error 500 si ocurre una excepción inesperada.
        """
        # Arrange
        self.mock_help_content_service.get_content.side_effect = Exception("Fallo crítico de lectura de archivo")

        # Act
        response = self.client.post(self.url)

        # Assert
        assert response.status_code == 500
        assert "error_message" in response.json
        assert "Ha ocurrido un error inesperado en el servidor" in response.json['error_message']
