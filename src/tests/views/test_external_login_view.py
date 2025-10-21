import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.external_login_view import InitiateExternalChatView, ExternalChatLoginView
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
MOCK_INIT_TOKEN = "a-fake-but-valid-initiation-token"
MOCK_SESSION_TOKEN = "a-long-lived-session-token"


class TestExternalLoginFlow:
    """
    Suite de tests unificada para el flujo de login externo.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para todos los servicios
        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_onboarding_service = MagicMock(spec=OnboardingService)
        self.mock_jwt_service = MagicMock(spec=JWTService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_prompt_service = MagicMock(spec=PromptService)

        # Configuración común de mocks
        self.mock_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.mock_company
        self.mock_iauthentication.verify.return_value = {"success": True}
        self.mock_branding_service.get_company_branding.return_value = {}

        # Registrar ambas vistas
        initiate_view = InitiateExternalChatView.as_view(
            'initiate_external_chat',
            iauthentication=self.mock_iauthentication,
            branding_service=self.mock_branding_service,
            profile_service=self.mock_profile_service,
            onboarding_service=self.mock_onboarding_service,
            jwt_service=self.mock_jwt_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service
        )
        finalize_view = ExternalChatLoginView.as_view(
            'external_login',
            profile_service=self.mock_profile_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service,
            jwt_service=self.mock_jwt_service,
            branding_service=self.mock_branding_service,
            # --- CORRECCIÓN: Añadir la dependencia que faltaba ---
            iauthentication=self.mock_iauthentication
        )
        self.app.add_url_rule('/<company_short_name>/initiate_external_chat', view_func=initiate_view, methods=['POST'])
        self.app.add_url_rule('/<company_short_name>/external_login', view_func=finalize_view, methods=['GET'])

    @patch('iatoolkit.views.external_login_view.render_template')
    def test_initiate_external_chat_fast_path(self, mock_render):
        """
        Prueba el CAMINO RÁPIDO: si no se necesita reconstruir, renderiza el chat directamente.
        """
        # Arrange
        self.mock_query_service.prepare_context.return_value = {'rebuild_needed': False}
        self.mock_jwt_service.generate_chat_jwt.return_value = MOCK_SESSION_TOKEN
        mock_render.return_value = "<html>Chat Page Direct</html>"

        # Act
        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        # Assert
        assert response.status_code == 200
        self.mock_query_service.prepare_context.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME, external_user_id=MOCK_EXTERNAL_USER_ID
        )
        self.mock_jwt_service.generate_chat_jwt.assert_called_once_with(
            company_id=self.mock_company.id, company_short_name=self.mock_company.short_name,
            external_user_id=MOCK_EXTERNAL_USER_ID, expires_delta_seconds=3600 * 8
        )
        mock_render.assert_called_once()
        assert mock_render.call_args[0][0] == 'chat.html'
        assert mock_render.call_args[1]['session_jwt'] == MOCK_SESSION_TOKEN
        self.mock_query_service.finalize_context_rebuild.assert_not_called()

    @patch('iatoolkit.views.external_login_view.render_template')
    def test_initiate_external_chat_slow_path(self, mock_render):
        """
        Prueba el CAMINO LENTO: si se necesita reconstruir, renderiza el shell con un token de iniciación.
        """
        # Arrange
        self.mock_query_service.prepare_context.return_value = {'rebuild_needed': True}
        self.mock_jwt_service.generate_chat_jwt.return_value = MOCK_INIT_TOKEN
        mock_render.return_value = "<html>Shell Page</html>"

        # Act
        response = self.client.post(
            f'/{MOCK_COMPANY_SHORT_NAME}/initiate_external_chat',
            json={'external_user_id': MOCK_EXTERNAL_USER_ID}
        )

        # Assert
        assert response.status_code == 200
        self.mock_query_service.prepare_context.assert_called_once()
        self.mock_jwt_service.generate_chat_jwt.assert_called_once_with(
            company_id=self.mock_company.id, company_short_name=self.mock_company.short_name,
            external_user_id=MOCK_EXTERNAL_USER_ID, expires_delta_seconds=180
        )
        mock_render.assert_called_once()
        assert mock_render.call_args[0][0] == 'onboarding_shell.html'
        assert f"init_token={MOCK_INIT_TOKEN}" in mock_render.call_args[1]['iframe_src_url']

    @patch('iatoolkit.views.external_login_view.render_template')
    def test_finalize_external_chat_view(self, mock_render):
        """
        Prueba la vista ExternalChatLoginView (trabajador pesado), asegurando que finaliza la reconstrucción.
        """
        # Arrange
        self.mock_jwt_service.validate_chat_jwt.return_value = {'external_user_id': MOCK_EXTERNAL_USER_ID}
        self.mock_jwt_service.generate_chat_jwt.return_value = MOCK_SESSION_TOKEN
        mock_render.return_value = "<html>Final Chat Page</html>"

        # Act
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/external_login?init_token={MOCK_INIT_TOKEN}')

        # Assert
        assert response.status_code == 200
        self.mock_jwt_service.validate_chat_jwt.assert_called_once_with(MOCK_INIT_TOKEN, MOCK_COMPANY_SHORT_NAME)
        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME, external_user_id=MOCK_EXTERNAL_USER_ID
        )
        self.mock_jwt_service.generate_chat_jwt.assert_called_with(
            company_id=self.mock_company.id, company_short_name=self.mock_company.short_name,
            external_user_id=MOCK_EXTERNAL_USER_ID, expires_delta_seconds=3600 * 8
        )
        mock_render.assert_called_once()
        assert mock_render.call_args[0][0] == 'chat.html'
        assert mock_render.call_args[1]['session_jwt'] == MOCK_SESSION_TOKEN