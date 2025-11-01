# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask, url_for
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.views.signup_view import SignupView
from iatoolkit.repositories.models import Company
import os


class TestSignupView:
    # --- MEJORA: Añadimos el patcher para la variable de entorno a nivel de clase ---
    @classmethod
    def setup_class(cls):
        cls.patcher = patch.dict(os.environ, {"USER_VERIF_KEY": "mocked_verif_key"})
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
        self.test_company = Company(id=1, name="Empresa de Prueba", short_name="test_company")
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        self.branding_service.get_company_branding.return_value = {"name": "Empresa de Prueba"}

        # Registrar la vista
        view = SignupView.as_view("signup",
                                  profile_service=self.profile_service,
                                  branding_service=self.branding_service)
        self.app.add_url_rule("/<string:company_short_name>/signup", view_func=view, methods=["GET", "POST"])

        # --- CORRECCIÓN: Añadir rutas dummy con los endpoints correctos ---
        @self.app.route("/<string:company_short_name>/home.html", endpoint="home")
        def dummy_home(company_short_name):
            return "Página Home", 200

        @self.app.route("/<string:company_short_name>/verify/<token>", endpoint="verify_account")
        def dummy_verify_account(company_short_name, token):
            return "Página de verificación", 200

    @patch("iatoolkit.views.signup_view.render_template")
    def test_get_when_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.get("/test_company/signup")

        assert response.status_code == 404
        mock_render.assert_called_once_with('error.html', message="Empresa no encontrada")

    @patch("iatoolkit.views.signup_view.render_template")
    def test_post_when_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.post("/test_company/signup", data={})

        assert response.status_code == 404
        mock_render.assert_called_once_with('error.html', message="Empresa no encontrada")

    @patch("iatoolkit.views.signup_view.render_template")
    def test_get_signup_page(self, mock_render_template):
        mock_render_template.return_value = "<html></html>"
        response = self.client.get("/test_company/signup")

        assert response.status_code == 200
        mock_render_template.assert_called_once_with(
            'signup.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value
        )

    @patch("iatoolkit.views.signup_view.render_template")
    def test_post_with_error(self, mock_render_template):
        mock_render_template.return_value = "<html></html>"
        self.profile_service.signup.return_value = {'error': 'El usuario ya existe'}
        form_data = {
            "first_name": "Juan", "last_name": "Perez", "email": "test@email.com",
            "password": "password123", "confirm_password": "password123"
        }

        response = self.client.post("/test_company/signup", data=form_data)

        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'signup.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            form_data=form_data,
            alert_message='El usuario ya existe'
        )

    @patch("iatoolkit.views.signup_view.URLSafeTimedSerializer")
    def test_post_when_ok(self, mock_serializer_class):
        success_message = "¡Cuenta creada! Revisa tu correo para verificarla."
        mock_serializer_class.return_value.dumps.return_value = 'some-secure-token'
        self.profile_service.signup.return_value = {"message": success_message}

        with self.app.test_request_context():
            expected_redirect_url = url_for('home', company_short_name='test_company')

            with self.client:
                response = self.client.post("/test_company/signup", data={
                    "first_name": "Juan", "last_name": "Perez", "email": "juan@email.com",
                    "password": "password123", "confirm_password": "password123"
                })

                assert response.status_code == 302
                assert response.location == expected_redirect_url

                with self.client.session_transaction() as sess:
                    assert sess['alert_message'] == success_message
                    assert sess['alert_icon'] == 'success'

    @patch("iatoolkit.views.signup_view.render_template")
    def test_post_unexpected_error(self, mock_render_template):
        self.profile_service.signup.side_effect = Exception('an error')
        response = self.client.post("/test_company/signup", data={})

        assert response.status_code == 500
        mock_render_template.assert_called_once()
