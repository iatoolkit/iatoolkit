# src/tests/views/test_home_view.py

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch, mock_open

from iatoolkit.repositories.models import Company
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.views.home_view import HomeView
from iatoolkit.common.util import Utility


class TestHomeView:
    @staticmethod
    def create_app():
        """Configura la aplicación Flask para pruebas."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-secret-key'
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        """Configura el cliente y los mocks antes de cada test."""
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.profile_service = MagicMock(spec=ProfileService)
        self.branding_service = MagicMock(spec=BrandingService)
        self.utility = MagicMock(spec=Utility)
        self.i8n_service = MagicMock(spec=I18nService)

        self.i8n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.test_company = Company(id=1, name="Test Co", short_name="test_co")
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        self.branding_service.get_company_branding.return_value = {"name": "Test Co Branding"}
        self.profile_service.get_current_session_info.return_value = {}

        # Registrar la vista principal
        view = HomeView.as_view("home",
                                profile_service=self.profile_service,
                                branding_service=self.branding_service,
                                utility=self.utility,
                                i18n_service=self.i8n_service,)
        self.app.add_url_rule("/<string:company_short_name>/home.html", view_func=view, methods=["GET"])

        # Ruta dummy para que url_for() en el template de error no falle.
        # Es importante tenerla aunque no se use directamente en el test.
        @self.app.route("/<string:company_short_name>/chat", endpoint="chat")
        def dummy_chat(company_short_name):
            return "Chat"

        @self.app.route("/<string:company_short_name>/home_dummy", endpoint="home_dummy_for_error")
        def dummy_home_for_error_template(company_short_name):
            return "Dummy Home"

    @patch('iatoolkit.views.home_view.render_template_string')
    def test_custom_template_renders_successfully(self, mock_render_string):
        """Prueba el caso de éxito: la plantilla personalizada existe y se renderiza."""
        mock_render_string.return_value = "Rendered HTML"
        self.utility.get_company_template.return_value = "<html>{{ company.name }}</html>"

        response = self.client.get("/test_co/home.html")

        assert response.status_code == 200
        mock_render_string.assert_called_once()


    @patch('iatoolkit.views.home_view.render_template')
    @patch('iatoolkit.views.home_view.render_template_string', side_effect=Exception("Jinja Error"))
    def test_custom_template_processing_fails(self, mock_render_string, mock_render_template):
        """Prueba el caso en que la plantilla existe pero falla al ser procesada."""
        mock_render_template.return_value = "Error Page"

        response = self.client.get("/test_co/home.html")

        assert response.status_code == 500
        # Verificamos que se renderiza la página de error con el mensaje de error de procesamiento
        mock_render_template.assert_called_once()

    @patch('iatoolkit.views.home_view.render_template')
    def test_get_home_page_invalid_company(self, mock_render_template):
        """Prueba que se devuelve un 404 si la empresa no es válida (sin cambios)."""
        self.profile_service.get_company_by_short_name.return_value = None
        mock_render_template.return_value = "Error Page"

        response = self.client.get("/invalid_co/home.html")
        assert response.status_code == 404

    @patch('iatoolkit.views.home_view.render_template')
    def test_missing_template_renders_hosted_default_for_hosted_company(self, mock_render_template):
        self.test_company.runtime_mode = "hosted"
        self.utility.get_company_template.return_value = None
        mock_render_template.return_value = "Hosted Home"

        response = self.client.get("/test_co/home.html")

        assert response.status_code == 200
        mock_render_template.assert_called_once()
        assert mock_render_template.call_args[0][0] == "home_hosted_default.html"
        assert mock_render_template.call_args[1]["company_short_name"] == "test_co"

    @patch('iatoolkit.views.home_view.render_template')
    def test_missing_template_renders_the_sign_in_for_a_company_without_home(self, mock_render_template):
        """A company entered from its own portal (Maxxa) has no home: show its sign-in, not an error."""
        self.test_company.runtime_mode = "static"
        self.utility.get_company_template.return_value = None
        self.utility.is_hosted_company_runtime.return_value = False
        mock_render_template.return_value = "Sign in"

        response = self.client.get("/test_co/home.html?lang=es")

        assert response.status_code == 200
        assert mock_render_template.call_args[0][0] == "home_default.html"
        assert mock_render_template.call_args[1]["company_short_name"] == "test_co"

    def test_missing_template_sends_a_signed_in_person_to_the_chat(self):
        self.test_company.runtime_mode = "static"
        self.utility.get_company_template.return_value = None
        self.profile_service.get_current_session_info.return_value = {
            "user_identifier": "ana@maxxa.cl", "company_short_name": "test_co"}

        response = self.client.get("/test_co/home.html?lang=es")

        assert response.status_code == 302
        assert response.location == "/test_co/chat?lang=es"

    @patch('iatoolkit.views.home_view.render_template')
    def test_a_session_of_another_company_does_not_skip_the_sign_in(self, mock_render_template):
        self.test_company.runtime_mode = "static"
        self.utility.get_company_template.return_value = None
        self.utility.is_hosted_company_runtime.return_value = False
        self.profile_service.get_current_session_info.return_value = {
            "user_identifier": "ana@otra.cl", "company_short_name": "otra"}
        mock_render_template.return_value = "Sign in"

        response = self.client.get("/test_co/home.html")

        assert response.status_code == 200
        assert mock_render_template.call_args[0][0] == "home_default.html"
