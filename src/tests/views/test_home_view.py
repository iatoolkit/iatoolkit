# src/tests/views/test_home_view.py

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch, mock_open

from iatoolkit.repositories.models import Company
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.views.home_view import HomeView


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

        self.test_company = Company(id=1, name="Test Co", short_name="test_co")
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        self.branding_service.get_company_branding.return_value = {"name": "Test Co Branding"}

        # Registrar la vista principal
        view = HomeView.as_view("home",
                                profile_service=self.profile_service,
                                branding_service=self.branding_service)
        self.app.add_url_rule("/<string:company_short_name>/home.html", view_func=view, methods=["GET"])

        # Ruta dummy para que url_for() en el template de error no falle.
        # Es importante tenerla aunque no se use directamente en el test.
        @self.app.route("/<string:company_short_name>/home_dummy", endpoint="home_dummy_for_error")
        def dummy_home_for_error_template(company_short_name):
            return "Dummy Home"

    @patch('iatoolkit.views.home_view.render_template_string')
    @patch('iatoolkit.views.home_view.open', new_callable=mock_open, read_data="<html>{{ company.name }}</html>")
    @patch('iatoolkit.views.home_view.os.path.exists', return_value=True)
    def test_custom_template_renders_successfully(self, mock_exists, mock_file, mock_render_string):
        """Prueba el caso de éxito: la plantilla personalizada existe y se renderiza."""
        mock_render_string.return_value = "Rendered HTML"

        response = self.client.get("/test_co/home.html")

        assert response.status_code == 200
        # Verificamos que se llamó a la función correcta para renderizar el string
        mock_render_string.assert_called_once_with(
            "<html>{{ company.name }}</html>",
            company=self.test_company,
            company_short_name='test_co',
            branding=self.branding_service.get_company_branding.return_value,
            alert_message=None,
            alert_icon='error'
        )

    @patch('iatoolkit.views.home_view.render_template')
    @patch('iatoolkit.views.home_view.os.path.exists', return_value=False)
    def test_custom_template_does_not_exist(self, mock_exists, mock_render_template):
        """Prueba el caso en que la plantilla personalizada no existe."""
        mock_render_template.return_value = "Error Page"

        response = self.client.get("/test_co/home.html")

        assert response.status_code == 500
        # Verificamos que se renderiza la página de error con el mensaje correcto
        mock_render_template.assert_called_once_with(
            "error.html",
            company_short_name='test_co',
            branding=self.branding_service.get_company_branding.return_value,
            message="La plantilla de la página de inicio para la empresa 'test_co' no está configurada."
        )

    @patch('iatoolkit.views.home_view.render_template')
    @patch('iatoolkit.views.home_view.render_template_string', side_effect=Exception("Jinja Error"))
    @patch('iatoolkit.views.home_view.open', new_callable=mock_open, read_data="<html>...</html>")
    @patch('iatoolkit.views.home_view.os.path.exists', return_value=True)
    def test_custom_template_processing_fails(self, mock_exists, mock_file, mock_render_string, mock_render_template):
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
