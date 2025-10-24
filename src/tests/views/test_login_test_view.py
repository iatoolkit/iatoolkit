import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
import os

# Asegúrate de que las importaciones sean correctas y existan
from iatoolkit.views.login_test_view import LoginTest
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService

# Ya no necesitamos JWTService, ChatTokenRequestView, etc.

class TestLoginTestView:
    @staticmethod
    def create_app():
        """Configura la aplicación Flask para pruebas."""
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        """Configura el cliente y el mock antes de cada test."""
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.profile_service = MagicMock(spec=ProfileService)
        self.test_company = Company(id=1, name='a company', short_name='test_company')
        self.profile_service.get_companies.return_value = [self.test_company]
        self.branding_service = MagicMock(spec=BrandingService)
        self.onboarding_service = MagicMock(spec=OnboardingService)

        # Registrar únicamente la vista que estamos probando.
        # No necesitamos registrar las otras vistas que han sido eliminadas.
        view = LoginTest.as_view("home",
                                 profile_service=self.profile_service,
                                 branding_service=self.branding_service,
                                 onboarding_service=self.onboarding_service,)
        self.app.add_url_rule("/", view_func=view, methods=["GET"])

    @patch("iatoolkit.views.login_test_view.render_template")
    @patch.dict(os.environ, {"IATOOLKIT_API_KEY": "una_api_key_de_prueba_segura"})
    def test_get_home_page(self, mock_render_template):
        """
        Prueba que la página de inicio se renderice correctamente sin los parámetros obsoletos.
        """
        mock_render_template.return_value = "<html><body><h1>Home Page</h1></body></html>"
        self.branding_service.get_company_branding.return_value = {}
        self.onboarding_service.get_onboarding_cards.return_value = {}
        # Ya no necesitamos el contexto de la petición para generar las URLs
        response = self.client.get("/")

        assert response.status_code == 200
        assert b"<h1>Home Page</h1>" in response.data

        # La aserción ahora debe reflejar los argumentos actuales de render_template en HomeView
        mock_render_template.assert_called_once_with(
            "login_test.html",
            companies=[self.test_company],
            alert_icon=None,
            alert_message=None,
            branding={},
            onboarding_cards={},
            api_key="una_api_key_de_prueba_segura",
        )