# test_init_context_view.py

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.init_context_view import InitContextView
from iatoolkit.services.query_service import QueryService
from iatoolkit.common.auth import IAuthentication

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-comp"
MOCK_EXTERNAL_USER_ID = "ext-user-123"


class TestInitContextView:
    """Pruebas para la vista InitContextView."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura un entorno de prueba limpio antes de cada test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para los servicios inyectados
        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_query_service = MagicMock(spec=QueryService)

        # Registrar la vista con los servicios mockeados
        view_func = InitContextView.as_view(
            'init_context',
            iauthentication=self.mock_iauthentication,
            query_service=self.mock_query_service
        )
        self.app.add_url_rule('/<company_short_name>/context/init/<external_user_id>', view_func=view_func, methods=['GET'])

    def test_init_context_success(self):
        """
        Prueba el flujo exitoso: la autenticación es correcta y el contexto se inicializa.
        """
        # Arrange: Configurar mocks para un flujo exitoso
        self.mock_iauthentication.verify.return_value = {"success": True}

        # Act: Realizar la petición GET al endpoint
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/context/init/{MOCK_EXTERNAL_USER_ID}')

        # Assert: Verificar el resultado
        assert response.status_code == 200
        assert response.json == {'status': 'OK'}

        # Verificar que los servicios fueron llamados correctamente
        self.mock_iauthentication.verify.assert_called_once_with(MOCK_COMPANY_SHORT_NAME, MOCK_EXTERNAL_USER_ID)
        self.mock_query_service.llm_init_context.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            external_user_id=MOCK_EXTERNAL_USER_ID
        )

    def test_init_context_auth_failure(self):
        """
        Prueba el flujo de fallo de autenticación: la vista debe devolver 401.
        """
        # Arrange: Configurar el mock de autenticación para que falle
        auth_error = {"success": False, "error": "Credenciales inválidas"}
        self.mock_iauthentication.verify.return_value = auth_error

        # Act: Realizar la petición GET
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/context/init/{MOCK_EXTERNAL_USER_ID}')

        # Assert: Verificar la respuesta de error y que el servicio principal no se llamó
        assert response.status_code == 401
        assert response.json == auth_error
        self.mock_query_service.llm_init_context.assert_not_called()

    def test_init_context_unexpected_error(self):
        """
        Prueba el manejo de un error inesperado en el servicio subyacente.
        """
        # Arrange: La autenticación es exitosa, pero el servicio de query falla
        self.mock_iauthentication.verify.return_value = {"success": True}
        error_message = "Error de conexión con la base de datos"
        self.mock_query_service.llm_init_context.side_effect = Exception(error_message)

        # Act: Realizar la petición GET
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/context/init/{MOCK_EXTERNAL_USER_ID}')

        # Assert: Verificar que se devuelve un error 500 con el mensaje correcto
        assert response.status_code == 500
        assert "error_message" in response.json
        assert response.json["error_message"] == error_message

        # Verificar que ambos servicios fueron intentados
        self.mock_iauthentication.verify.assert_called_once()
        self.mock_query_service.llm_init_context.assert_called_once()
