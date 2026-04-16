# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from pathlib import Path

import pytest
from flask import Flask, render_template, request


class TestPublicAuthTemplates:
    @staticmethod
    def create_app():
        project_root = Path(__file__).resolve().parents[3]
        template_folder = project_root / "src" / "iatoolkit" / "templates"
        static_folder = project_root / "src" / "iatoolkit" / "static"

        app = Flask(
            __name__,
            template_folder=str(template_folder),
            static_folder=str(static_folder),
        )
        app.config['SECRET_KEY'] = 'test-secret-key'
        app.testing = True

        def translate(key: str, **kwargs):
            translations = {
                'ui.login_widget.welcome_message': 'Welcome message',
                'ui.login_widget.google_button': 'Continue with Google',
                'ui.login_widget.or_continue_with': 'or continue with',
                'ui.login_widget.session_expired_message': 'Your session expired. Please sign in again.',
                'ui.signup.email_label': 'Email Address',
                'ui.signup.password_label': 'Password',
                'ui.login_widget.login_button': 'Login',
                'ui.login_widget.no_account_prompt': "Don't have an account?",
                'ui.login_widget.signup_link': 'Sign Up',
                'ui.login_widget.forgot_password_link': 'Forgot your password?',
                'ui.signup.title': 'Create an Account',
                'ui.signup.google_button': 'Sign up with Google',
                'ui.signup.or_signup_with_email': 'or sign up with email',
                'ui.signup.first_name_label': 'First Name',
                'ui.signup.last_name_label': 'Last Name',
                'ui.signup.confirm_password_label': 'Confirm Password',
                'ui.change_password.password_instructions': 'Password instructions',
                'ui.signup.signup_button': 'Create Account',
                'ui.signup.disclaimer': 'Privacy disclaimer',
                'ui.signup.already_have_account': 'Already have an account?',
                'ui.signup.login_link': 'Log In',
            }
            return translations.get(key, key)

        @app.context_processor
        def inject_test_globals():
            return {
                't': translate,
                'flashed_messages': [],
                'google_analytics_id': '',
            }

        @app.route("/<string:company_short_name>/home", endpoint="home")
        def home(company_short_name):
            google_enabled = request.args.get('google', '1') == '1'
            return render_template(
                "_login_widget.html",
                company_short_name=company_short_name,
                google_login_enabled=google_enabled,
                branding={"name": "Test Co", "primary_text_style": "", "css_variables": ""},
            )

        @app.route("/<string:company_short_name>/signup", endpoint="signup")
        def signup(company_short_name):
            google_enabled = request.args.get('google', '1') == '1'
            return render_template(
                "signup.html",
                company_short_name=company_short_name,
                google_login_enabled=google_enabled,
                branding={"name": "Test Co", "primary_text_style": "", "css_variables": ""},
                lang=request.args.get('lang', 'en'),
            )

        @app.route("/<string:company_short_name>/login", endpoint="login")
        def login(company_short_name):
            return "login", 200

        @app.route("/<string:company_short_name>/login/google", endpoint="login_google_start")
        def login_google_start(company_short_name):
            return "google", 200

        @app.route("/<string:company_short_name>/forgot-password", endpoint="forgot_password")
        def forgot_password(company_short_name):
            return "forgot", 200

        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()

    def test_login_widget_shows_google_button_when_enabled(self):
        response = self.client.get('/acme/home?lang=en&google=1')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Continue with Google' in html
        assert '/acme/login/google?lang=en' in html
        assert 'or continue with' in html

    def test_login_widget_hides_google_button_when_disabled(self):
        response = self.client.get('/acme/home?lang=en&google=0')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Continue with Google' not in html
        assert 'or continue with' not in html

    def test_login_widget_shows_session_expired_message(self):
        response = self.client.get('/acme/home?lang=en&session_expired=1')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Your session expired. Please sign in again.' in html

    def test_signup_template_shows_google_button_when_enabled(self):
        response = self.client.get('/acme/signup?lang=en&google=1')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Sign up with Google' in html
        assert '/acme/login/google?lang=en' in html
        assert 'or sign up with email' in html
        assert 'Already have an account?' in html

    def test_signup_template_hides_google_button_when_disabled(self):
        response = self.client.get('/acme/signup?lang=en&google=0')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'Sign up with Google' not in html
        assert 'or sign up with email' not in html
