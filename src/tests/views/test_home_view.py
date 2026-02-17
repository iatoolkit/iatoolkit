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

        # Registrar la vista principal
        view = HomeView.as_view("home",
                                profile_service=self.profile_service,
                                branding_service=self.branding_service,
                                utility=self.utility,
                                i18n_service=self.i8n_service,)
        self.app.add_url_rule("/<string:company_short_name>/home.html", view_func=view, methods=["GET"])

        # Ruta dummy para que url_for() en el template de error no falle.
        # Es importante tenerla aunque no se use directamente en el test.
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
