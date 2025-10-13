import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.login_external_id_view import InitiateExternalChatView, ExternalChatLoginView
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.common.auth import IAuthentication
from iatoolkit.repositories.models import Company



# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-comp"
MOCK_EXTERNAL_USER_ID = "ext-user-123"
MOCK_API_KEY = "super-secret-api-key"
MOCK_JWT_TOKEN = "a-fake-but-valid-jwt-token"


class TestInitiateExternalChatView:
    """Pruebas para la vista de inicio rápido (InitiateExternalChatView)."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura la aplicación Flask y los mocks para cada test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para las dependencias de InitiateExternalChatView
        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_profile_service = MagicMock(spec=ProfileService)

        self.mock_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.mock_company
        self.mock_branding_service.get_company_branding.return_value = {}

        # Registrar la vista a probar
        view_func = InitiateExternalChatView.as_view(
            'initiate_external_chat',
            iauthentication=self.mock_iauthentication,
            branding_service=self.mock_branding_service,
            profile_service=self.mock_profile_service
        )
        self.app.add_url_rule('/<company_short_name>/initiate_external_chat', view_func=view_func, methods=['POST'])

        # Registrar endpoint falso para que url_for('external_login') funcione
        @self.app.route('/<company_short_name>/external_login', endpoint='external_login')
        def dummy_external_login(company_short_name): return "OK"

    @patch('iatoolkit.views.login_external_id_view.render_template')
    def test_initiate_success(self, mock_render):
        """Prueba que una iniciación exitosa devuelve la página shell."""
        self.mock_iauthentication.verify.return_value = {"success": True}
        mock_render.return_value = "<html>Shell Page</html>"

        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        assert response.status_code == 200
        assert response.data == b"<html>Shell Page</html>"
        self.mock_iauthentication.verify.assert_called_once()
        self.mock_branding_service.get_company_branding.assert_called_once()

        mock_render.assert_called_once()
        # Corregido: Verificar los nuevos argumentos pasados a render_template
        call_kwargs = mock_render.call_args[1]
        assert 'iframe_src_url' in call_kwargs
        assert MOCK_EXTERNAL_USER_ID in call_kwargs['iframe_src_url']
        assert 'branding' in call_kwargs

    def test_initiate_auth_failure(self):
        """Prueba que una autenticación fallida devuelve un error 401."""
        self.mock_iauthentication.verify.return_value = {"success": False, "error": "Invalid API Key"}

        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        assert response.status_code == 401
        assert response.is_json
        assert 'Invalid API Key' in response.json['error']

    def test_initiate_missing_payload(self):
        """Prueba que una petición sin 'external_user_id' devuelve un error 400."""
        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={}  # Payload vacío
        )
        assert response.status_code == 400
        assert 'Falta external_user_id' in response.json['error']


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
        self.branding_service = MagicMock(spec=BrandingService)

        # Configurar el mock de la compañía que se devolverá
        self.mock_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.mock_company

        # Registrar la vista en la app de Flask con TODAS las dependencias
        view_func = ExternalChatLoginView.as_view(
            'external_login',
            profile_service=self.mock_profile_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service,
            branding_service=self.branding_service,
            iauthentication=self.mock_iauthentication,
            jwt_service=self.mock_jwt_service
        )

        # Corregido: La vista ahora maneja GET, así que la regla debe permitirlo.
        self.app.add_url_rule('/<company_short_name>/external_login', view_func=view_func, methods=['GET'])
        self.client = self.app.test_client()

    def test_login_success(self):
        """
        Prueba el flujo exitoso, incluyendo la generación del JWT.
        """
        # Configurar mocks para el caso de éxito
        self.mock_prompt_service.get_user_prompts.return_value = []
        self.mock_jwt_service.generate_chat_jwt.return_value = MOCK_JWT_TOKEN
        self.branding_service.get_company_branding.return_value = {}

        with patch('iatoolkit.views.login_external_id_view.render_template') as mock_render:
            mock_render.return_value = "<html>Chat Page</html>"

            # Corregido: Llamada GET limpia, sin cuerpo JSON.
            response = self.client.get(
                f'/{MOCK_COMPANY_SHORT_NAME}/external_login?external_user_id={MOCK_EXTERNAL_USER_ID}'
            )

        # Verificar que la respuesta es exitosa
        assert response.status_code == 200
        assert response.data == b"<html>Chat Page</html>"

        # Verificar que se intentó generar el JWT con los datos correctos
        self.mock_jwt_service.generate_chat_jwt.assert_called_once_with(
            company_id=self.mock_company.id,
            company_short_name=self.mock_company.short_name,
            external_user_id=MOCK_EXTERNAL_USER_ID,
            expires_delta_seconds=3600 * 8
        )

        # Verificar que se inicializó el contexto y se obtuvieron los prompts
        self.mock_query_service.llm_init_context.assert_called_once()
        self.mock_prompt_service.get_user_prompts.assert_called_once()

        # Verificar que se renderizó la plantilla con TODOS los datos correctos
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        assert call_kwargs['company_short_name'] == MOCK_COMPANY_SHORT_NAME
        assert call_kwargs['external_user_id'] == MOCK_EXTERNAL_USER_ID
        assert call_kwargs['auth_method'] == 'jwt'
        assert call_kwargs['session_jwt'] == MOCK_JWT_TOKEN

    def test_login_fails_if_jwt_generation_fails(self):
        """
        Prueba que la vista maneja un error si el JWTService no puede generar un token.
        """
        # Simular fallo en la generación del token
        self.mock_jwt_service.generate_chat_jwt.return_value = None

        # Corregido: La llamada ahora es un GET
        response = self.client.get(
            f'/{MOCK_COMPANY_SHORT_NAME}/external_login?external_user_id={MOCK_EXTERNAL_USER_ID}'
        )

        # La vista debería devolver un error 500
        assert response.status_code == 500
        assert response.is_json
        assert 'Error interno' in response.json['error']

    # ... (el resto de los tests, como el de fallo de autenticación, permanecen igual y deberían seguir funcionando) ...