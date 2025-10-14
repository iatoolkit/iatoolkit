import pytest
from flask import Flask
from unittest.mock import MagicMock, patch, call
from iatoolkit.views.login_external_id_view import InitiateExternalChatView, ExternalChatLoginView
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService
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

        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_onboarding_service = MagicMock(spec=OnboardingService)

        self.mock_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.mock_company
        self.mock_branding_service.get_company_branding.return_value = {}

        view_func = InitiateExternalChatView.as_view(
            'initiate_external_chat',
            iauthentication=self.mock_iauthentication,
            branding_service=self.mock_branding_service,
            profile_service=self.mock_profile_service,
            onboarding_service=self.mock_onboarding_service
        )
        self.app.add_url_rule('/<company_short_name>/initiate_external_chat', view_func=view_func, methods=['POST'])

        @self.app.route('/<company_short_name>/external_login', endpoint='external_login')
        def dummy_external_login(company_short_name): return "OK"

    @patch('iatoolkit.views.login_external_id_view.render_template')
    @patch('iatoolkit.views.login_external_id_view.SessionManager')
    def test_initiate_success(self, mock_session_manager, mock_render):
        """Prueba que una iniciación exitosa guarda el estado en sesión y devuelve el shell."""
        self.mock_iauthentication.verify.return_value = {"success": True}
        self.mock_onboarding_service.get_onboarding_cards.return_value = [{'title': 'Card'}]
        mock_render.return_value = "<html>Shell Page</html>"

        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        assert response.status_code == 200
        # Verificar que se estableció la sesión temporal
        mock_session_manager.set.assert_has_calls([
            call('external_user_id', MOCK_EXTERNAL_USER_ID),
            call('is_external_auth_complete', True)
        ], any_order=True)

        # Verificar que se renderizó la plantilla con la URL limpia
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        assert 'iframe_src_url' in call_kwargs
        assert MOCK_EXTERNAL_USER_ID not in call_kwargs['iframe_src_url'] # La URL ya no debe contener el ID

    def test_initiate_auth_failure(self):
        """Prueba que una autenticación fallida devuelve un error 401."""
        self.mock_iauthentication.verify.return_value = {"success": False, "error": "Invalid API Key"}

        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        assert response.status_code == 401
        assert 'Invalid API Key' in response.json['error']

    def test_initiate_missing_payload(self):
        """Prueba que una petición sin 'external_user_id' devuelve un error 400."""
        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={}
        )
        assert response.status_code == 400
        assert 'Falta external_user_id' in response.json['error']


class TestExternalChatLoginView:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura la aplicación Flask y los mocks para cada test."""
        self.app = Flask(__name__)
        self.app.testing = True

        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_jwt_service = MagicMock(spec=JWTService)
        self.mock_branding_service = MagicMock(spec=BrandingService)

        self.mock_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.mock_company

        view_func = ExternalChatLoginView.as_view(
            'external_login',
            profile_service=self.mock_profile_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service,
            branding_service=self.mock_branding_service,
            iauthentication=self.mock_iauthentication,
            jwt_service=self.mock_jwt_service
        )
        self.app.add_url_rule('/<company_short_name>/external_login', view_func=view_func, methods=['GET'])
        self.client = self.app.test_client()

    @patch('iatoolkit.views.login_external_id_view.render_template')
    @patch('iatoolkit.views.login_external_id_view.SessionManager')
    def test_login_success(self, mock_session_manager, mock_render):
        """Prueba el flujo exitoso, leyendo los datos desde la sesión."""
        # Arrange: Simular una sesión válida creada por InitiateExternalChatView
        mock_session_manager.get.side_effect = lambda key: {
            'is_external_auth_complete': True,
            'external_user_id': MOCK_EXTERNAL_USER_ID
        }.get(key)
        self.mock_jwt_service.generate_chat_jwt.return_value = MOCK_JWT_TOKEN
        self.mock_prompt_service.get_user_prompts.return_value = []
        self.mock_branding_service.get_company_branding.return_value = {}
        mock_render.return_value = "<html>Chat Page</html>"

        # Act: Llamar al endpoint sin parámetros en la URL
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/external_login')

        # Assert
        assert response.status_code == 200
        # Verificar que la bandera de sesión se limpió
        mock_session_manager.set.assert_called_once_with('is_external_auth_complete', None)
        # Verificar que la lógica pesada se ejecutó
        self.mock_jwt_service.generate_chat_jwt.assert_called_once()
        self.mock_query_service.llm_init_context.assert_called_once()
        # Verificar que la plantilla final fue renderizada
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args[1]
        assert call_kwargs['external_user_id'] == MOCK_EXTERNAL_USER_ID
        assert call_kwargs['session_jwt'] == MOCK_JWT_TOKEN

    @patch('iatoolkit.views.login_external_id_view.SessionManager')
    def test_login_fails_without_session_flag(self, mock_session_manager):
        """Prueba que la vista devuelve un error 401 si la bandera de sesión no está presente."""
        # Arrange: Simular que la bandera no existe
        mock_session_manager.get.return_value = None

        # Act
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/external_login')

        # Assert
        assert response.status_code == 401
        assert b"Acceso no autorizado" in response.data

    @patch('iatoolkit.views.login_external_id_view.SessionManager')
    def test_login_fails_if_jwt_generation_fails(self, mock_session_manager):
        """Prueba que la vista maneja un error si JWTService no puede generar un token."""
        # Arrange: Simular una sesión válida pero un fallo en JWT
        mock_session_manager.get.side_effect = lambda key: {
            'is_external_auth_complete': True,
            'external_user_id': MOCK_EXTERNAL_USER_ID
        }.get(key)
        self.mock_jwt_service.generate_chat_jwt.return_value = None

        # Act
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/external_login')

        # Assert
        assert response.status_code == 500
        assert 'Error interno' in response.json['error']