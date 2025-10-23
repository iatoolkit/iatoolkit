# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.mail_app import MailApp
from iatoolkit.repositories.models import User, Company
from flask_bcrypt import generate_password_hash
from iatoolkit.services.dispatcher_service import Dispatcher


# CORRECTION: Patch where the object is USED, not where it is defined.
# The SessionManager is used inside the 'profile_service' module.
@patch('iatoolkit.services.profile_service.SessionManager')
class TestProfileService:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a consistent, mocked environment for each test."""
        self.mock_repo = MagicMock(spec=ProfileRepo)
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_mail_app = MagicMock(spec=MailApp)
        self.mock_dispatcher = MagicMock(spec=Dispatcher)

        self.service = ProfileService(
            profile_repo=self.mock_repo,
            session_context_service=self.mock_session_context,
            mail_app=self.mock_mail_app,
            dispatcher=self.mock_dispatcher
        )

        self.mock_user = User(id=1, email='test@email.com', first_name='Test', last_name='User',
                              password=generate_password_hash("password").decode("utf-8"), verified=True)
        self.mock_company = Company(id=100, name='My Company', short_name='test_company')
        self.mock_repo.get_company_by_short_name.return_value = self.mock_company
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.companies = [self.mock_company]

    # --- Tests for New Unified Session Logic ---

    def test_login_creates_web_session_for_local_user(self, mock_session_manager):
        """Tests that login() builds a local profile and calls the session creation helper."""
        response = self.service.login(self.mock_company.short_name, 'test@email.com', 'password')

        assert response['success'] is True
        self.mock_dispatcher.get_user_info.assert_not_called()
        self.mock_session_context.save_profile_data.assert_called_once()
        mock_session_manager.set.assert_any_call('user_identifier', str(self.mock_user.email))
        mock_session_manager.set.assert_any_call('company_short_name', self.mock_company.short_name)

    def test_create_external_user_session_creates_web_session(self, mock_session_manager):
        """Tests that create_external_user_session calls the dispatcher and creates a web session."""
        external_profile = {'name': 'External API User', 'roles': ['api']}
        self.mock_dispatcher.get_user_info.return_value = external_profile

        self.service.create_external_user_session(self.mock_company, "ext-user-1")

        self.mock_dispatcher.get_user_info.assert_called_once_with(
            company_name=self.mock_company.short_name, user_identifier="ext-user-1")
        self.mock_session_context.save_profile_data.assert_called_once_with(
            self.mock_company.short_name, "ext-user-1", external_profile
        )
        mock_session_manager.set.assert_any_call('user_identifier', "ext-user-1")

    def test_get_current_session_info(self, mock_session_manager):
        """Tests get_current_session_info reads from Flask cookie and fetches from Redis."""
        # This context is needed because SessionManager.get touches the real Flask `session` object.
        with patch('iatoolkit.services.profile_service.SessionManager', mock_session_manager):
            mock_session_manager.get.side_effect = lambda key: '1' if key == 'user_identifier' else 'testco'
            expected_profile = {"id": 1, "email": "test@email.com"}
            self.mock_session_context.get_profile_data.return_value = expected_profile

            result = self.service.get_current_session_info()

        self.mock_session_context.get_profile_data.assert_called_once_with('testco', '1')
        assert result['profile'] == expected_profile

    # --- Other tests also need the mock_session_manager argument ---

    def test_login_when_ok(self, mock_session_manager):
        """
        Tests that a successful login returns the correct user object and creates a session.
        """
        response = self.service.login(self.mock_company.short_name, 'test@email.com', 'password')

        mock_session_manager.set.assert_any_call('user_identifier', str(self.mock_user.email))
        self.mock_session_context.save_profile_data.assert_called_once()
        assert response['success'] and response['user_identifier'] == self.mock_user.email

    def test_signup_when_user_exist_and_already_register(self, mock_session_manager):
        """This test now correctly receives the mock argument and passes."""
        response = self.service.signup(
            self.mock_company.short_name, 'test@email.com', 'Test', 'User', 'password', 'password', 'url'
        )
        assert "Usuario ya registrado" in response['error']

    def test_signup_when_user_exist_and_invalid_password(self, mock_session_manager):
        self.mock_user.password = generate_password_hash("password").decode("utf-8")
        self.mock_repo.get_user_by_email.return_value = self.mock_user

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="invalid_password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "contraseña es incorrecta" in response['error']

    def test_signup_when_user_exist_and_not_in_company(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.companies = []

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "Usuario asociado" in response['message']
        self.mock_repo.save_user.assert_called_once()

    def test_signup_when_passwords_different(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password1", confirm_password="Password2$1",
            verification_url='http://verification'
        )

        assert "contraseñas no coinciden" in response['error']

    def test_signup_when_passwords_incorrect2(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password", confirm_password="Password",
            verification_url='http://verification'
        )

        assert "número" in response['error']

    def test_signup_when_passwords_incorrect3(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Passw1", confirm_password="Passw1",
            verification_url='http://verification'
        )

        assert "8 caracteres" in response['error']

    def test_signup_when_passwords_incorrect4(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password123", confirm_password="password123",
            verification_url='http://verification'
        )

        assert "mayúscula" in response['error']

    def test_signup_when_passwords_incorrect5(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password123", confirm_password="Password123",
            verification_url='http://verification'
        )

        assert "especial" in response['error']

    def test_signup_when_ok(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None
        self.mock_mail_app.send_email.return_value = True

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password$1", confirm_password="Password$1",
            verification_url='http://verification'
        )

        assert "Registro exitoso" in response['message']
        self.mock_mail_app.send_email.assert_called()

    def test_signup_when_exception(self, mock_session_manager):
        self.mock_repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "an error" == response['error']

    def test_get_companies_when_ok(self, mock_session_manager):
        self.mock_repo.get_companies.return_value = [self.mock_company]
        companies = self.service.get_companies()
        assert companies == [self.mock_company]

    def test_get_company_by_short_name_when_ok(self, mock_session_manager):
        company = self.service.get_company_by_short_name('test_company')
        assert company == self.mock_company

    def test_update_user(self, mock_session_manager):
        self.mock_repo.update_user.return_value = self.mock_user
        user = self.service.update_user('fl@opensoft.cl', first_name='fernando')

        assert user == self.mock_user

    def test_verify_account_when_user_not_exist(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.verify_account(email='test@email.com')

        assert "El usuario no existe." in response['error']

    def test_verify_account_when_exception(self,mock_session_manager):
        self.mock_repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.verify_account(email='test@email.com')

        assert "an error" == response['error']

    def test_verify_account_when_ok(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        response = self.service.verify_account(email='test@email.com')

        assert "cuenta ha sido verificada" in response['message']

    def test_change_password_when_password_mismatch(self,mock_session_manager):
        response = self.service.change_password(
            email='test@email.com',
            temp_code='ABC',
            new_password='pass1',
            confirm_password='pass2'
        )
        assert "contraseñas no coinciden" in response['error']

    def test_change_passworwd_when_invalid_code(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.temp_code = 'xYhvt'
        response = self.service.change_password(
            email='test@email.com',
            temp_code='ABC',
            new_password='pass1',
            confirm_password='pass1'
        )
        assert "código temporal no es válido" in response['error']

    def test_change_password_when_ok(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.temp_code = 'ABC'
        response = self.service.change_password(
            email='test@email.com',
            temp_code=self.mock_user.temp_code,
            new_password='pass1',
            confirm_password='pass1'
        )
        assert "clave se cambio correctamente" in response['message']

    def test_change_password_when_exception(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_repo.update_password.side_effect = Exception('db error')
        response = self.service.change_password(
            email='test@email.com',
            temp_code=self.mock_user.temp_code,
            new_password='pass1',
            confirm_password='pass1'
        )
        assert "db error" == response['error']

    def test_forgot_password_when_user_not_exist(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None
        response = self.service.forgot_password(
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )
        assert "El usuario no existe" in response['error']

    def test_forgot_password_when_ok(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        response = self.service.forgot_password(
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )
        assert "se envio mail para cambio de clave" in response['message']
        self.mock_mail_app.send_email.assert_called()

    def test_forgot_password_when_exception(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_mail_app.send_email.side_effect = Exception('mail error')
        response = self.service.forgot_password(
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )

        assert "mail error" == response['error']

    def test_new_api_key_when_not_company(self,mock_session_manager):
        self.mock_repo.get_company_by_short_name.return_value = None
        response = self.service.new_api_key(company_short_name='test_company')
        assert "test_company no existe" in response['error']

    def test_new_api_key_when_ok(self,mock_session_manager):
        self.mock_repo.get_company_by_short_name.return_value = self.mock_company
        response = self.service.new_api_key(company_short_name='test_company')

        self.mock_repo.create_api_key.assert_called()
        assert response['api-key'] != ''


