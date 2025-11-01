# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask, url_for
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.repositories.models import Company
from iatoolkit.views.verify_user_view import VerifyAccountView
import os
from itsdangerous import SignatureExpired


class TestVerifyAccountView:
    @classmethod
    def setup_class(cls):
        cls.patcher = patch.dict(os.environ, {"USER_VERIF_KEY": "mocked_secret_key"})
        cls.patcher.start()

    @classmethod
    def teardown_class(cls):
        cls.patcher.stop()

    @staticmethod
    def create_app():
        app = Flask(__name__)
        app.testing = True
        app.config['SECRET_KEY'] = 'test-secret-key'
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.profile_service = MagicMock(spec=ProfileService)
        # --- MEJORA: Añadir mock para BrandingService ---
        self.branding_service = MagicMock(spec=BrandingService)
        self.test_company = Company(id=1, name="Empresa de Prueba", short_name="test_company")
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        self.branding_service.get_company_branding.return_value = {"name": "Empresa de Prueba"}

        # --- MEJORA: Inyectar branding_service en la vista ---
        view = VerifyAccountView.as_view("verify_account",
                                         profile_service=self.profile_service,
                                         branding_service=self.branding_service)
        self.app.add_url_rule("/<string:company_short_name>/verify/<token>", view_func=view, methods=["GET"])

        # --- CORRECCIÓN: Añadir la ruta 'home' para que url_for() no falle ---
        @self.app.route("/<string:company_short_name>/home.html", endpoint="home")
        def dummy_home(company_short_name):
            return "Página Home", 200

    @patch("iatoolkit.views.verify_user_view.render_template")
    def test_get_with_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.get("/test_company/verify/some_token")

        assert response.status_code == 404
        mock_render.assert_called_once_with('error.html', message="Empresa no encontrada")

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_get_with_expired_token(self, mock_serializer_class, mock_render_template):
        mock_serializer_class.return_value.loads.side_effect = SignatureExpired('error')
        mock_render_template.return_value = "<html></html>"

        response = self.client.get("/test_company/verify/expired_token")

        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'signup.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            token='expired_token',
            alert_message="El enlace de verificación ha expirado. Por favor, solicita uno nuevo."
        )

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_verify_with_error(self, mock_serializer, mock_render_template):
        mock_serializer.return_value.loads.return_value = "nonexistent@email.com"
        mock_render_template.return_value = "<html></html>"
        self.profile_service.verify_account.return_value = {'error': 'Enlace inválido'}

        response = self.client.get("/test_company/verify/valid_token")

        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'signup.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            token='valid_token',
            alert_message='Enlace inválido'
        )

    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_verify_ok(self, mock_serializer_class):
        success_message = "¡Cuenta verificada exitosamente!"
        mock_serializer_class.return_value.loads.return_value = "user@example.com"
        self.profile_service.verify_account.return_value = {"message": success_message}

        with self.app.test_request_context():
            expected_redirect_url = url_for('home', company_short_name='test_company')

            with self.client:
                response = self.client.get("/test_company/verify/valid_token")

                assert response.status_code == 302
                assert response.location == expected_redirect_url

                with self.client.session_transaction() as sess:
                    assert sess['alert_message'] == success_message
                    assert sess['alert_icon'] == "success"

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_get_unexpected_error(self, mock_serializer, mock_render_template):
        mock_serializer.return_value.loads.return_value = "user@example.com"
        self.profile_service.verify_account.side_effect = Exception('an error')
        response = self.client.get("/test_company/verify/valid_token")

        assert response.status_code == 500
        mock_render_template.assert_called_once_with(
            "error.html",
            branding=self.branding_service.get_company_branding.return_value,
            company_short_name='test_company',
            message="Ha ocurrido un error inesperado."
        )
