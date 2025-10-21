# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

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
    Suite de tests unificada para el flujo de login completo (local).
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'super-secret-key-for-testing'
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para todos los servicios inyectados
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_onboarding_service = MagicMock(spec=OnboardingService)

        # Configuración común de mocks
        self.test_company = Company(id=1, name="Empresa de Prueba", short_name=MOCK_COMPANY_SHORT_NAME)
        self.test_user = User(id=MOCK_USER_ID, email=MOCK_USER_EMAIL)
        self.mock_profile_service.get_company_by_short_name.return_value = self.test_company
        self.mock_profile_service.login.return_value = {'success': True, 'user': self.test_user}
        self.mock_profile_service.get_current_user_profile.return_value = {'id': MOCK_USER_ID, 'email': MOCK_USER_EMAIL}
        self.mock_branding_service.get_company_branding.return_value = {"css_variables": ":root{}", "name": "Test"}

        # Registrar ambas vistas con la sintaxis de URL correcta
        initiate_view = InitiateLoginView.as_view(
            "initiate_login",
            profile_service=self.mock_profile_service,
            branding_service=self.mock_branding_service,
            onboarding_service=self.mock_onboarding_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service
        )
        finalize_view = LoginView.as_view(
            "login",  # Endpoint para el iframe
            profile_service=self.mock_profile_service,
            query_service=self.mock_query_service,
            prompt_service=self.mock_prompt_service,
            branding_service=self.mock_branding_service
        )

        # --- CORRECCIÓN: Usar <company_short_name> para capturar el parámetro de la URL ---
        self.app.add_url_rule("/<company_short_name>/initiate_login", view_func=initiate_view, methods=["POST"])
        self.app.add_url_rule("/<company_short_name>/login", view_func=finalize_view, methods=["GET"])

        # Endpoints falsos para que url_for funcione
        @self.app.route("/<company_short_name>/login_page", endpoint='login_page')
        def dummy_login_page(company_short_name): return "Login Page"

    @patch("iatoolkit.views.login_view.render_template")
    def test_initiate_login_fast_path(self, mock_render_template):
        """
        Prueba el CAMINO RÁPIDO: si prepare_context dice que no se necesita reconstruir,
        se renderiza chat.html directamente.
        """
        # Arrange
        self.mock_query_service.prepare_context.return_value = {'rebuild_needed': False}
        mock_render_template.return_value = "<html>Chat Page</html>"

        # Act
        response = self.client.post(f"/{MOCK_COMPANY_SHORT_NAME}/initiate_login",
                                    data={"email": MOCK_USER_EMAIL, "password": MOCK_USER_PASSWORD})

        # Assert
        assert response.status_code == 200
        self.mock_profile_service.login.assert_called_once()
        self.mock_query_service.prepare_context.assert_called_once_with(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                                                        local_user_id=MOCK_USER_ID)

        mock_render_template.assert_called_once()
        template_name = mock_render_template.call_args[0][0]
        assert template_name == "chat.html"

        self.mock_onboarding_service.get_onboarding_cards.assert_not_called()
        self.mock_query_service.finalize_context_rebuild.assert_not_called()

    @patch("iatoolkit.views.login_view.render_template")
    def test_initiate_login_slow_path(self, mock_render_template):
        """
        Prueba el CAMINO LENTO: si prepare_context dice que se necesita reconstruir,
        se renderiza onboarding_shell.html.
        """
        # Arrange
        self.mock_query_service.prepare_context.return_value = {'rebuild_needed': True}
        mock_render_template.return_value = "<html>Shell Page</html>"

        # Act
        response = self.client.post(f"/{MOCK_COMPANY_SHORT_NAME}/initiate_login",
                                    data={"email": MOCK_USER_EMAIL, "password": MOCK_USER_PASSWORD})

        # Assert
        assert response.status_code == 200
        self.mock_query_service.prepare_context.assert_called_once_with(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                                                        local_user_id=MOCK_USER_ID)

        mock_render_template.assert_called_once()
        template_name = mock_render_template.call_args[0][0]
        assert template_name == "onboarding_shell.html"

        self.mock_onboarding_service.get_onboarding_cards.assert_called_once()

    @patch("iatoolkit.views.login_view.render_template")
    def test_finalize_login_view(self, mock_render_template):
        """
        Prueba la vista LoginView (el trabajador pesado), asegurando que finaliza la reconstrucción.
        """
        # Arrange
        mock_render_template.return_value = "<html>Final Chat Page</html>"

        # Act
        response = self.client.get(f"/{MOCK_COMPANY_SHORT_NAME}/login")

        # Assert
        assert response.status_code == 200
        self.mock_profile_service.get_current_user_profile.assert_called_once()

        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            local_user_id=MOCK_USER_ID
        )

        mock_render_template.assert_called_once()
        template_name = mock_render_template.call_args[0][0]
        assert template_name == "chat.html"

    def test_finalize_login_view_redirects_if_no_session(self):
        """Prueba que LoginView redirige si no hay una sesión de usuario válida."""
        # Arrange
        self.mock_profile_service.get_current_user_profile.return_value = {}  # Sin sesión

        # Act
        response = self.client.get(f"/{MOCK_COMPANY_SHORT_NAME}/login")

        # Assert
        assert response.status_code == 302  # Redirección
        assert response.location.endswith(f"/{MOCK_COMPANY_SHORT_NAME}/login_page")
        self.mock_query_service.finalize_context_rebuild.assert_not_called()