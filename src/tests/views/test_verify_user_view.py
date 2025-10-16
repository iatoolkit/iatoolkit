# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company
from iatoolkit.views.verify_user_view import VerifyAccountView
import os
from itsdangerous import SignatureExpired


class TestVerifyAccountView:
    @classmethod
    def setup_class(cls):
        cls.patcher = patch.dict(os.environ, {"USER_VERIF_KEY": "mocked_secret_key"})
        cls.patcher.start()

    @staticmethod
    def create_app():
        """Configura la aplicación Flask para pruebas."""
        app = Flask(__name__)
        app.testing = True
        app.config['SECRET_KEY'] = 'test-secret-key'
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        """Configura el cliente y los mocks antes de cada test."""
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.profile_service = MagicMock(spec=ProfileService)
        self.test_company = Company(
            id=1,
            name="Empresa de Prueba",
            short_name="test_company"
        )
        self.profile_service.get_company_by_short_name.return_value = self.test_company

        # Registrar la vista
        view = VerifyAccountView.as_view("verify_account", profile_service=self.profile_service)
        self.app.add_url_rule("/<company_short_name>/verify/<token>", view_func=view, methods=["GET"])

        # Añadir una ruta 'index' para que url_for() no falle en la prueba
        @self.app.route("/<company_short_name>/")
        def index(company_short_name):
            return "Página de índice", 200

    @patch("iatoolkit.views.verify_user_view.render_template")
    def test_get_with_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.get("/test_company/verify/<expired_token>")
        assert response.status_code == 404


    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_get_with_expired_token(self, mock_serializer_class, mock_render_template):
        # Configura que el serializer lance una excepción de expiración
        mock_serializer = mock_serializer_class.return_value
        mock_serializer.loads.side_effect = SignatureExpired('error')

        mock_render_template.return_value = "<html><body><h1>Signup Page</h1></body></html>"
        response = self.client.get("/test_company/verify/<expired_token>")

        assert response.status_code == 400

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_verify_with_error(self, mock_serializer, mock_render_template):
        # Simula que el token es válido y contiene un email
        mock_serializer.return_value.loads.return_value = "nonexistent@email.com"
        mock_render_template.return_value = "<html><body><h1>Signup Page</h1></body></html>"
        self.profile_service.verify_account.return_value = {'error': 'invalid link'}

        response = self.client.get("/test_company/verify/<valid_token>")
        assert response.status_code == 400

    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_verify_ok(self, mock_serializer_class):
        """Prueba una verificación de cuenta exitosa que redirige y establece la sesión."""
        # Configurar mocks para un flujo exitoso
        success_message = "¡Cuenta verificada exitosamente!"
        mock_serializer_class.return_value.loads.return_value = "user@example.com"
        self.profile_service.verify_account.return_value = {"message": success_message}

        # Usar el cliente de prueba dentro de un contexto para manejar la sesión
        with self.client:
            response = self.client.get("/test_company/verify/valid_token")

            # 1. Verificar que se produjo una redirección (302) a la página correcta
            assert response.status_code == 302
            assert response.location == "/test_company/"

            # 2. Abrir la sesión resultante para verificar su contenido
            with self.client.session_transaction() as sess:
                assert sess['alert_message'] == success_message
                assert sess['alert_icon'] == "success"

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_post_unexpected_error(self, mock_serializer, mock_render_template):
        mock_serializer.return_value.loads.return_value = "nonexistent@email.com"
        self.profile_service.verify_account.side_effect = Exception('an error')
        response = self.client.get("/test_company/verify/<valid_token>")

        mock_render_template.assert_called_once_with(
            "error.html",
            company=self.test_company,
            company_short_name='test_company',
            message="Ha ocurrido un error inesperado."
        )
        assert response.status_code == 500