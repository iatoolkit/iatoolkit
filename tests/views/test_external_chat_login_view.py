import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from views.external_chat_login_view import ExternalChatLoginView
from services.profile_service import ProfileService
from services.query_service import QueryService
from services.prompt_manager_service import PromptService
from services.jwt_service import JWTService  # <-- Importar JWTService
from common.auth import IAuthentication
from repositories.models import Company


# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-comp"
MOCK_EXTERNAL_USER_ID = "ext-user-123"
MOCK_API_KEY = "super-secret-api-key"
MOCK_JWT_TOKEN = "a-fake-but-valid-jwt-token"


class TestExternalChatLoginView:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura la aplicación Flask y los mocks para cada test."""
        self.app = Flask(__name__)
        self.app.testing = True

        # Mocks de todos los servicios inyectados
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_jwt_service = MagicMock(spec=JWTService)

        # Configurar el mock de la compañía que se devolverá
        self.mock_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.mock_company

        # Registrar la vista en la app de Flask con TODAS las dependencias
        view_func = ExternalChatLoginView.as_view(
            'external_chat_login',
            profile_service=self.mock_profile_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service,
            iauthentication=self.mock_iauthentication,
            jwt_service=self.mock_jwt_service  # <-- 2. Inyectar el mock de JWTService
        )

        self.app.add_url_rule('/<company_short_name>/chat_login', view_func=view_func, methods=['POST'])
        self.client = self.app.test_client()

    def test_login_success(self):
        """
        Prueba el flujo exitoso, incluyendo la generación del JWT.
        """
        # Configurar mocks para el caso de éxito
        self.mock_iauthentication.verify.return_value = {"success": True}
        self.mock_prompt_service.get_user_prompts.return_value = []
        # 3. Configurar el mock para que devuelva un token
        self.mock_jwt_service.generate_chat_jwt.return_value = MOCK_JWT_TOKEN

        with patch('views.external_chat_login_view.render_template') as mock_render:
            mock_render.return_value = "<html>Chat Page</html>"

            response = self.client.post(
                f'/{MOCK_COMPANY_SHORT_NAME}/chat_login',
                headers={'Authorization': f'Bearer {MOCK_API_KEY}'},
                json={'external_user_id': MOCK_EXTERNAL_USER_ID}
            )

        # Verificar que la respuesta es exitosa
        assert response.status_code == 200
        assert response.data == b"<html>Chat Page</html>"

        # Verificar que se llamó a la autenticación
        self.mock_iauthentication.verify.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            body_external_user_id=MOCK_EXTERNAL_USER_ID
        )

        # 4. Verificar que se intentó generar el JWT con los datos correctos
        self.mock_jwt_service.generate_chat_jwt.assert_called_once_with(
            company_id=self.mock_company.id,
            company_short_name=self.mock_company.short_name,
            external_user_id=MOCK_EXTERNAL_USER_ID,
            expires_delta_seconds=3600 * 8
        )

        # Verificar que se inicializó el contexto y se obtuvieron los prompts
        self.mock_query_service.llm_init_context.assert_called_once()
        self.mock_prompt_service.get_user_prompts.assert_called_once()

        # 5. Verificar que se renderizó la plantilla con TODOS los datos correctos
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        assert call_kwargs['company_short_name'] == MOCK_COMPANY_SHORT_NAME
        assert call_kwargs['external_user_id'] == MOCK_EXTERNAL_USER_ID
        assert call_kwargs['auth_method'] == 'jwt'
        assert call_kwargs['session_jwt'] == MOCK_JWT_TOKEN  # <-- Verificar que el token se pasa

    def test_login_fails_if_jwt_generation_fails(self):
        """
        Prueba que la vista maneja un error si el JWTService no puede generar un token.
        """
        self.mock_iauthentication.verify.return_value = {"success": True}
        # Simular fallo en la generación del token
        self.mock_jwt_service.generate_chat_jwt.return_value = None

        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/chat_login',
            headers={'Authorization': f'Bearer {MOCK_API_KEY}'},
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        # La vista debería devolver un error 500
        assert response.status_code == 500
        assert response.is_json
        assert 'Error interno' in response.json['error']

    # ... (el resto de los tests, como el de fallo de autenticación, permanecen igual y deberían seguir funcionando) ...