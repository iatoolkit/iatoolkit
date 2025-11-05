# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask, url_for, get_flashed_messages
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
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
        self.branding_service = MagicMock(spec=BrandingService)
        self.i8n_service = MagicMock(spec=I18nService)

        self.test_company = Company(id=1, name="Empresa de Prueba", short_name="test_company")
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        self.branding_service.get_company_branding.return_value = {"name": "Empresa de Prueba"}

        # Configure the mock to return a real string, not another mock.
        self.i8n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        view = VerifyAccountView.as_view("verify_account",
                                         profile_service=self.profile_service,
                                         branding_service=self.branding_service,
                                         i18n_service=self.i8n_service,)
        self.app.add_url_rule("/<string:company_short_name>/verify/<token>", view_func=view, methods=["GET"])

        @self.app.route("/<string:company_short_name>/home.html", endpoint="home")
        def dummy_home(company_short_name):
            return "Página Home", 200

    @patch("iatoolkit.views.verify_user_view.render_template")
    def test_get_with_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.get("/test_company/verify/some_token")
        assert response.status_code == 404

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_get_with_expired_token(self, mock_serializer_class, mock_render_template):
        mock_serializer_class.return_value.loads.side_effect = SignatureExpired('error')
        mock_render_template.return_value = "<html></html>"

        with self.client:
            response = self.client.get("/test_company/verify/expired_token")
            flashed_messages = get_flashed_messages(with_categories=True)

        assert len(flashed_messages) == 1
        assert flashed_messages[0][0] == 'error'

        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'signup.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            token='expired_token',
        )

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_verify_with_error(self, mock_serializer, mock_render_template):
        mock_serializer.return_value.loads.return_value = "nonexistent@email.com"
        mock_render_template.return_value = "<html></html>"
        self.profile_service.verify_account.return_value = {'error': 'Enlace inválido'}

        with self.client:
            response = self.client.get("/test_company/verify/valid_token")
            flashed_messages = get_flashed_messages(with_categories=True)

        assert len(flashed_messages) == 1
        assert flashed_messages[0][0] == 'error'

        assert response.status_code == 400
        mock_render_template.assert_called_once_with(
            'signup.html',
            company=self.test_company,
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            token='valid_token'
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
                flashed_messages = get_flashed_messages(with_categories=True)

                assert response.status_code == 302
                assert response.location == expected_redirect_url
                assert len(flashed_messages) == 1
                assert flashed_messages[0][0] == 'success'

    @patch("iatoolkit.views.verify_user_view.render_template")
    @patch("iatoolkit.views.verify_user_view.URLSafeTimedSerializer")
    def test_get_unexpected_error(self, mock_serializer, mock_render_template):
        mock_serializer.return_value.loads.return_value = "user@example.com"
        self.profile_service.verify_account.side_effect = Exception('an error')
        with self.client:
            response = self.client.get("/test_company/verify/valid_token")
            flashed = get_flashed_messages(with_categories=True)

        assert response.status_code == 302
        assert len(flashed) == 1
        assert flashed[0] == ('error', 'translated:errors.general.unexpected_error')
