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
from iatoolkit.services.signup_guard_service import SignupGuardService
from iatoolkit.views.signup_view import SignupView
from iatoolkit.repositories.models import Company
import os


class TestSignupView:
    @classmethod
    def setup_class(cls):
        cls.patcher = patch.dict(os.environ, {"IATOOLKIT_SECRET_KEY": "mocked_verif_key"})
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
        self.i8n_service = MagicMock(spec=I18nService)
        self.signup_guard_service = MagicMock(spec=SignupGuardService)
        self.signup_guard_service.issue_form_token.return_value = 'form-token'
        self.signup_guard_service.check.return_value = None
        self.signup_guard_service.client_ip.return_value = '203.0.113.7'

        self.test_company = Company(id=1, name="Empresa de Prueba", short_name="test_company")
        self.profile_service.get_company_by_short_name.return_value = self.test_company
        self.branding_service.get_company_branding.return_value = {"name": "Empresa de Prueba"}

        self.i8n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        # Registrar la vista
        view = SignupView.as_view("signup",
                                  profile_service=self.profile_service,
                                  branding_service=self.branding_service,
                                  i18n_service=self.i8n_service,
                                  signup_guard_service=self.signup_guard_service,)
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
        mock_render.assert_called_once()

    @patch("iatoolkit.views.signup_view.render_template")
    def test_post_when_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.post("/test_company/signup", data={})

        assert response.status_code == 404
        mock_render.assert_called_once()

    @patch("iatoolkit.views.signup_view.render_template")
    def test_get_signup_page(self, mock_render_template):
        mock_render_template.return_value = "<html></html>"
        response = self.client.get("/test_company/signup")

        assert response.status_code == 200
        mock_render_template.assert_called_once_with(
            'signup.html',
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            lang='en',
            form_token='form-token',
        )

    @patch("iatoolkit.views.signup_view.render_template")
    def test_invitation_only_signup_requires_valid_link(self, mock_render_template):
        mock_render_template.return_value = "<html></html>"
        self.profile_service.signup_invitation_context.return_value = (True, None)

        response = self.client.get("/test_company/signup")

        assert response.status_code == 403
        mock_render_template.assert_called_once_with(
            'error.html', message='translated:errors.signup.invitation_required',
        )

    @patch("iatoolkit.views.signup_view.render_template")
    def test_invitation_link_prefills_invited_email(self, mock_render_template):
        mock_render_template.return_value = "<html></html>"
        self.profile_service.signup_invitation_context.return_value = (
            True, 'invited@example.com',
        )

        response = self.client.get("/test_company/signup?invite_token=secret")

        assert response.status_code == 200
        assert mock_render_template.call_args.kwargs['invite_token'] == 'secret'
        assert mock_render_template.call_args.kwargs['invited_email'] == 'invited@example.com'

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
            company_short_name='test_company',
            branding=self.branding_service.get_company_branding.return_value,
            form_data=form_data,
            form_token='form-token',
            lang=None
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
                flashed_messages = get_flashed_messages(with_categories=True)

                assert len(flashed_messages) == 1
                assert flashed_messages[0][0] == 'success'

                assert response.status_code == 302
                assert response.location == expected_redirect_url



    @patch("iatoolkit.views.signup_view.render_template")
    def test_post_unexpected_error(self, mock_render_template):
        self.profile_service.signup.side_effect = Exception('an error')
        response = self.client.post("/test_company/signup", data={})

        assert response.status_code == 500
        mock_render_template.assert_called_once()

    def test_post_rejected_by_bot_guard_looks_like_success(self):
        self.signup_guard_service.check.return_value = 'honeypot'

        with self.client:
            response = self.client.post("/test_company/signup", data={
                "first_name": "hoddjzfoabcekfbgyu", "last_name": "eyixfj",
                "email": "victim@example.com", "password": "x", "confirm_password": "x",
                "website": "http://spam",
            })
            flashed_messages = get_flashed_messages(with_categories=True)

        assert response.status_code == 302
        assert flashed_messages == [('success', 'translated:flash_messages.signup_success')]
        self.profile_service.signup.assert_not_called()
        args, kwargs = self.signup_guard_service.check.call_args
        assert args[0] == 'test_company'
        assert kwargs == {'client_ip': '203.0.113.7', 'email': 'victim@example.com'}

    @patch("iatoolkit.views.signup_view.render_template")
    def test_post_with_expired_form_asks_to_retry(self, mock_render_template):
        mock_render_template.return_value = "<html></html>"
        self.signup_guard_service.check.return_value = SignupGuardService.EXPIRED

        with self.client:
            response = self.client.post("/test_company/signup", data={
                "first_name": "Juan", "last_name": "Perez", "email": "juan@email.com",
                "password": "password123", "confirm_password": "password123",
            })
            flashed_messages = get_flashed_messages(with_categories=True)

        assert response.status_code == 400
        assert flashed_messages == [('error', 'translated:errors.signup.form_expired')]
        self.profile_service.signup.assert_not_called()
        assert mock_render_template.call_args.kwargs['form_token'] == 'form-token'
