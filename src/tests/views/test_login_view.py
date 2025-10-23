# test_login_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.login_view import InitiateLoginView, LoginView
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService
from iatoolkit.repositories.models import Company, User

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test_company"
MOCK_USER_EMAIL = "test@email.com"
MOCK_USER_PASSWORD = "password"
MOCK_USER_ID = 1


class TestLoginFlow:
    """
    Suite de tests unificada para el flujo de login local (user/pass).
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para todos los servicios
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_onboarding_service = MagicMock(spec=OnboardingService)

        # Configuración común de mocks
        self.test_company = Company(id=1, name="Test Company", short_name=MOCK_COMPANY_SHORT_NAME)
        self.test_user = User(id=MOCK_USER_ID, email=MOCK_USER_EMAIL)
        self.mock_profile_service.get_company_by_short_name.return_value = self.test_company
        self.mock_profile_service.login.return_value = {'success': True, 'user_identifier': self.test_user.email}
        self.mock_profile_service.get_current_session_info.return_value = {
            'user_identifier': str(MOCK_USER_ID),
            'profile': {'id': MOCK_USER_ID, 'email': MOCK_USER_EMAIL, 'user_is_local': True}
        }
        self.mock_branding_service.get_company_branding.return_value = {}

        # Registrar ambas vistas con sus dependencias
        initiate_view = InitiateLoginView.as_view(
            "initiate_login",
            profile_service=self.mock_profile_service,
            branding_service=self.mock_branding_service,
            onboarding_service=self.mock_onboarding_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service
        )
        finalize_view = LoginView.as_view(
            "login",
            profile_service=self.mock_profile_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service,
            branding_service=self.mock_branding_service
        )
        self.app.add_url_rule("/<company_short_name>/initiate_login", view_func=initiate_view, methods=["POST"])
        self.app.add_url_rule("/<company_short_name>/login", view_func=finalize_view, methods=["GET"])

        @self.app.route("/<company_short_name>/login_page", endpoint='login_page')
        def dummy_login_page(company_short_name): return "Login Page"

    @patch("iatoolkit.views.login_view.render_template")
    def test_initiate_login_fast_path(self, mock_render_template):
        """
        Prueba el CAMINO RÁPIDO: si prepare_context no necesita reconstruir, renderiza chat.html directamente.
        """
        self.mock_query_service.prepare_context.return_value = {'rebuild_needed': False}
        mock_render_template.return_value = "OK"

        response = self.client.post(f"/{MOCK_COMPANY_SHORT_NAME}/initiate_login",
                                    data={"email": MOCK_USER_EMAIL, "password": MOCK_USER_PASSWORD})

        assert response.status_code == 200
        self.mock_profile_service.login.assert_called_once()
        self.mock_query_service.prepare_context.assert_called_once_with(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                                                        user_identifier=self.test_user.email)
        mock_render_template.assert_called_once()
        assert mock_render_template.call_args[0][0] == "chat.html"
        self.mock_query_service.finalize_context_rebuild.assert_not_called()

    @patch("iatoolkit.views.login_view.render_template")
    def test_initiate_login_slow_path(self, mock_render_template):
        """
        Prueba el CAMINO LENTO: si prepare_context necesita reconstruir, renderiza onboarding_shell.html.
        """
        self.mock_query_service.prepare_context.return_value = {'rebuild_needed': True}
        mock_render_template.return_value = "OK"

        response = self.client.post(f"/{MOCK_COMPANY_SHORT_NAME}/initiate_login",
                                    data={"email": MOCK_USER_EMAIL, "password": MOCK_USER_PASSWORD})

        assert response.status_code == 200
        self.mock_query_service.prepare_context.assert_called_once()
        mock_render_template.assert_called_once()
        assert mock_render_template.call_args[0][0] == "onboarding_shell.html"

    @patch("iatoolkit.views.login_view.render_template")
    def test_finalize_login_view(self, mock_render_template):
        """
        Prueba LoginView (trabajador pesado), asegurando que finaliza la reconstrucción.
        """
        mock_render_template.return_value = "OK"

        response = self.client.get(f"/{MOCK_COMPANY_SHORT_NAME}/login")

        assert response.status_code == 200
        self.mock_profile_service.get_current_session_info.assert_called_once()
        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=str(MOCK_USER_ID)
        )
        mock_render_template.assert_called_once()
        assert mock_render_template.call_args[0][0] == "chat.html"