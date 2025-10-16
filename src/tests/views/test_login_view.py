# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask, session
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


class TestInitiateLoginView:
    """Pruebas para la nueva vista de inicio rápido (InitiateLoginView)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'super-secret-key-for-testing'
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para las dependencias de InitiateLoginView
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_onboarding_service = MagicMock(spec=OnboardingService)

        self.test_company = Company(id=1, name="Empresa de Prueba", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.test_company
        self.mock_branding_service.get_company_branding.return_value = {"css_variables": ":root{}", "name": "Test"}

        # Registrar la vista a probar
        initiate_view = InitiateLoginView.as_view("initiate_login",
                                                  profile_service=self.mock_profile_service,
                                                  branding_service=self.mock_branding_service,
                                                  onboarding_service=self.mock_onboarding_service)
        self.app.add_url_rule(f"/<company_short_name>/initiate_login", view_func=initiate_view, methods=["POST"])

        # Registrar un endpoint falso para que url_for('login') funcione
        @self.app.route("/<company_short_name>/login", endpoint='login')
        def dummy_login(company_short_name): return "OK"

    @patch("iatoolkit.views.login_view.render_template")
    def test_successful_initiation_returns_shell(self, mock_render_template):
        """Prueba que un login exitoso en initiate_login devuelve la página shell."""
        # Arrange
        self.mock_profile_service.login.return_value = {'success': True, 'user': User(id=1)}
        self.mock_onboarding_service.get_onboarding_cards.return_value = [{'title': 'Test Card'}]
        mock_render_template.return_value = "<html>Shell Page</html>"

        # Act
        response = self.client.post(f"/{MOCK_COMPANY_SHORT_NAME}/initiate_login",
                                    data={"email": MOCK_USER_EMAIL, "password": MOCK_USER_PASSWORD})

        # Assert
        assert response.status_code == 200
        self.mock_profile_service.login.assert_called_once()
        self.mock_branding_service.get_company_branding.assert_called_once_with(self.test_company)
        self.mock_onboarding_service.get_onboarding_cards.assert_called_once_with(self.test_company)

        # Verificar que se renderizó la plantilla correcta con los datos correctos
        mock_render_template.assert_called_once()
        call_args, call_kwargs = mock_render_template.call_args
        assert call_args[0] == "onboarding_shell.html"
        assert 'iframe_src_url' in call_kwargs
        assert 'branding' in call_kwargs
        assert 'onboarding_cards' in call_kwargs
        assert call_kwargs['onboarding_cards'] == [{'title': 'Test Card'}]

    @patch("iatoolkit.views.login_view.render_template")
    def test_failed_initiation_renders_login_again(self, mock_render_template):
        """Prueba que un login fallido en initiate_login vuelve a renderizar la página de login con un error."""
        # Arrange
        self.mock_profile_service.login.return_value = {'success': False, 'message': 'Credenciales inválidas'}
        mock_render_template.return_value = "<html>Login con Error</html>"

        # Act
        response = self.client.post(f"/{MOCK_COMPANY_SHORT_NAME}/initiate_login",
                                    data={"email": "wrong@user.com", "password": "bad"})

        # Assert
        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'login.html',
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            company=self.test_company,
            form_data={"email": "wrong@user.com", "password": "bad"},
            alert_message='Credenciales inválidas'
        )


class TestLoginView:
    """Pruebas para la vista de carga pesada (LoginView), que ahora responde a GET."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'super-secret-key-for-testing'
        self.app.testing = True
        self.client = self.app.test_client()

        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_branding_service = MagicMock(spec=BrandingService)

        self.test_company = Company(id=1, name="Empresa de Prueba", short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_service.get_company_by_short_name.return_value = self.test_company

        view = LoginView.as_view("login",
                                 profile_service=self.mock_profile_service,
                                 query_service=self.mock_query_service,
                                 prompt_service=self.mock_prompt_service,
                                 branding_service=self.mock_branding_service)
        # La vista ahora responde a GET y POST
        self.app.add_url_rule("/<company_short_name>/login", view_func=view, methods=["GET", "POST"])

        # Endpoint falso para probar la redirección
        @self.app.route("/<company_short_name>/home", endpoint='home')
        def dummy_home(company_short_name): return "Home Page"

    @patch("iatoolkit.views.login_view.render_template")
    @patch("iatoolkit.views.login_view.SessionManager")
    def test_get_successful_with_session(self, mock_session_manager, mock_render_template):
        """Prueba que el GET a login (heavy-lifting) funciona cuando hay una sesión."""
        # Arrange
        mock_session_manager.get.side_effect = lambda key: {
            'user_id': 123,
            'user': {'email': MOCK_USER_EMAIL},
        }.get(key)
        mock_render_template.return_value = "<html>Chat Page</html>"

        # Act
        response = self.client.get(f"/{MOCK_COMPANY_SHORT_NAME}/login")

        # Assert
        assert response.status_code == 200
        self.mock_query_service.llm_init_context.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            local_user_id=123
        )
        self.mock_prompt_service.get_user_prompts.assert_called_once()
        self.mock_branding_service.get_company_branding.assert_called_once()

        mock_render_template.assert_called_once()
        call_args, call_kwargs = mock_render_template.call_args
        assert call_args[0] == "chat.html"
        assert call_kwargs['user_email'] == MOCK_USER_EMAIL

    @patch("iatoolkit.views.login_view.SessionManager")
    def test_get_fails_without_session_redirects(self, mock_session_manager):
        """Prueba que un GET a login sin sesión redirige al home."""
        # Arrange
        mock_session_manager.get.return_value = None

        # Act
        response = self.client.get(f"/{MOCK_COMPANY_SHORT_NAME}/login")

        # Assert
        assert response.status_code == 302  # 302 es el código para redirección
        assert response.location.endswith(f"/{MOCK_COMPANY_SHORT_NAME}/home")