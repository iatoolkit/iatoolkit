# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask, url_for
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company
from iatoolkit.views.forgot_password_view import ForgotPasswordView
import os
from iatoolkit.services.branding_service import BrandingService


class TestForgotPasswordView:
    @classmethod
    def setup_class(cls):
        cls.patcher = patch.dict(os.environ, {"PASS_RESET_KEY": "mocked_reset_key"})
        cls.patcher.start()

    @classmethod
    def teardown_class(cls):
        cls.patcher.stop()

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
        self.test_company = Company(
            id=1,
            name="Empresa de Prueba",
            short_name="test_company"
        )
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        # Mock para el branding data que se espera en los templates
        self.branding_service.get_company_branding.return_value = {"name": "Empresa de Prueba"}

        # Registrar la vista
        view = ForgotPasswordView.as_view("forgot_password",
                                          profile_service=self.profile_service,
                                          branding_service=self.branding_service)
        self.app.add_url_rule("/<string:company_short_name>/forgot_password", view_func=view, methods=["GET", "POST"])

        # --- MEJORA: Añadir rutas dummy con los nombres correctos para que url_for() no falle ---
        @self.app.route("/<string:company_short_name>/home.html", endpoint="home")
        def dummy_home(company_short_name):
            return "Página Home", 200

        @self.app.route("/<string:company_short_name>/change_password/<token>", endpoint="change_password")
        def dummy_change_password(company_short_name, token):
            return "Página de cambio de contraseña", 200

    @patch("iatoolkit.views.forgot_password_view.render_template")
    def test_get_when_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None

        response = self.client.get("/test_company/forgot_password")

        # --- MEJORA: Verificar que se renderiza el template de error correcto ---
        assert response.status_code == 404
        mock_render.assert_called_once_with('error.html', message="Empresa no encontrada")

    @patch("iatoolkit.views.forgot_password_view.render_template")
    def test_post_when_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None

        response = self.client.post("/test_company/forgot_password", data={"email": "nonexistent@email.com"})

        # --- MEJORA: Verificar que se renderiza el template de error correcto ---
        assert response.status_code == 404
        mock_render.assert_called_once_with('error.html', message="Empresa no encontrada")

    @patch("iatoolkit.views.forgot_password_view.render_template")
    def test_get_forgot_password_page(self, mock_render_template):
        mock_render_template.return_value = "<html><body><h1>Forgot Password</h1></body></html>"

        response = self.client.get("/test_company/forgot_password")

        # --- MEJORA: Verificar que se llama a render_template con los argumentos correctos ---
        assert response.status_code == 200
        mock_render_template.assert_called_once_with(
            'forgot_password.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value
        )

    @patch("iatoolkit.views.forgot_password_view.render_template")
    def test_post_with_error_from_service(self, mock_render_template):
        # Este test reemplaza el anterior 'test_post_with_error' para ser más preciso
        mock_render_template.return_value = "<html><body><h1>Error</h1></body></html>"
        self.profile_service.forgot_password.return_value = {'error': 'Usuario no encontrado'}
        test_email = "nonexistent@email.com"

        response = self.client.post("/test_company/forgot_password", data={"email": test_email})

        # --- MEJORA: Verificación completa de la llamada a render_template en caso de error ---
        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'forgot_password.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            form_data={"email": test_email},
            alert_message='Usuario no encontrado'
        )

    @patch("iatoolkit.views.forgot_password_view.URLSafeTimedSerializer")
    def test_post_ok(self, mock_serializer_class):
        """Prueba un POST exitoso que envía el correo y establece el mensaje en sesión."""
        mock_serializer_class.return_value.dumps.return_value = 'some-secure-token'
        self.profile_service.forgot_password.return_value = {"message": "link sent"}

        with self.app.test_request_context():  # Contexto para que url_for funcione
            expected_redirect_url = url_for('home', company_short_name='test_company')

            with self.client:
                response = self.client.post("/test_company/forgot_password", data={"email": "user@example.com"})

                # --- MEJORA: Usar url_for para verificar la redirección, haciéndola más robusta ---
                assert response.status_code == 302
                assert response.location == expected_redirect_url

                with self.client.session_transaction() as sess:
                    assert sess['alert_icon'] == "success"
                    assert sess[
                               'alert_message'] == "Si tu correo está registrado, recibirás un enlace para restablecer tu contraseña."

    @patch("iatoolkit.views.forgot_password_view.render_template")
    def test_post_unexpected_error(self, mock_render_template):
        # Este test ya estaba bien, pero lo dejamos para consistencia
        self.profile_service.forgot_password.side_effect = Exception('an error')

        response = self.client.post("/test_company/forgot_password", data={"email": "nonexistent@email.com"})

        mock_render_template.assert_called_once_with(
            "error.html",
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            message="Ha ocurrido un error inesperado: an error"
        )
        assert response.status_code == 500
