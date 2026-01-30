# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.mail_service import MailService
from iatoolkit.repositories.models import User, Company
from flask_bcrypt import generate_password_hash
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.language_service import LanguageService
from iatoolkit.services.embedding_service import EmbeddingService


# The SessionManager is used inside the 'profile_service' module.
@patch('iatoolkit.services.profile_service.SessionManager')
class TestProfileService:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a consistent, mocked environment for each test."""
        self.mock_repo = MagicMock(spec=ProfileRepo)
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_mail_service = MagicMock(spec=MailService)
        self.mock_dispatcher = MagicMock(spec=Dispatcher)
        self.mock_i18n = MagicMock(spec=I18nService)
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_language_service = MagicMock(spec=LanguageService)
        self.mock_embedding_service = MagicMock(spec=EmbeddingService)

        self.service = ProfileService(
            profile_repo=self.mock_repo,
            session_context_service=self.mock_session_context,
            mail_service=self.mock_mail_service,
            dispatcher=self.mock_dispatcher,
            i18n_service=self.mock_i18n,
            config_service=self.mock_config_service,
            lang_service=self.mock_language_service,
            embedding_service=self.mock_embedding_service
        )

        self.mock_user = User(id=1, email='test@email.com', first_name='Test', last_name='User',
                              password=generate_password_hash("password").decode("utf-8"), verified=True)
        self.mock_company = Company(id=100, name='My Company', short_name='test_company')
        self.mock_repo.get_company_by_short_name.return_value = self.mock_company
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.companies = [self.mock_company]

        # Simula el diccionario de traducciones cargado para la validación
        self.mock_i18n.translations = {'en': {}, 'es': {}}
        self.mock_i18n.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.mock_config_service.get_configuration.return_value = {}


    # --- Tests for New Unified Session Logic ---

    def test_login_creates_web_session_for_local_user(self, mock_session_manager):
        """Tests that login() builds a local profile and calls the session creation helper."""
        response = self.service.login(self.mock_company.short_name, 'test@email.com', 'password')

        assert response['success'] is True
        self.mock_session_context.save_profile_data.assert_called_once()
        mock_session_manager.set.assert_any_call('user_identifier', str(self.mock_user.email))
        mock_session_manager.set.assert_any_call('company_short_name', self.mock_company.short_name)


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
        assert  response['error'] == 'translated:errors.signup.user_already_registered'

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

        assert 'translated:errors.signup.incorrect_password_for_existing_user' == response['error']

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

        assert response['message'] == 'translated:flash_messages.user_associated_success'
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

        assert response['error'] == 'translated:errors.signup.password_mismatch'

    def test_signup_when_passwords_incorrect2(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password", confirm_password="Password",
            verification_url='http://verification'
        )

        assert response['error'] == 'translated:errors.validation.password_no_digit'

    def test_signup_when_passwords_incorrect3(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Passw1", confirm_password="Passw1",
            verification_url='http://verification'
        )

        assert response['error'] == 'translated:errors.validation.password_too_short'

    def test_signup_when_passwords_incorrect4(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password123", confirm_password="password123",
            verification_url='http://verification'
        )

        assert response['error'] == 'translated:errors.validation.password_no_uppercase'

    def test_signup_when_passwords_incorrect5(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password123", confirm_password="Password123",
            verification_url='http://verification'
        )

        assert response['error'] == 'translated:errors.validation.password_no_special_char'

    def test_signup_when_ok(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None
        self.mock_mail_service.send_mail.return_value = True

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password$1", confirm_password="Password$1",
            verification_url='http://verification'
        )

        assert response['message'] == 'translated:flash_messages.signup_success'
        self.mock_mail_service.send_mail.assert_called()

    def test_signup_when_ok_and_mail_not_verified(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None
        self.mock_mail_service.send_mail.return_value = True
        self.mock_config_service.get_configuration.return_value = {'verify_account': False}

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password$1", confirm_password="Password$1",
            verification_url='http://verification'
        )

        assert response['message'] == 'translated:flash_messages.signup_success_no_verification'
        self.mock_mail_service.send_mail.assert_not_called()

    def test_signup_when_exception(self, mock_session_manager):
        self.mock_repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert  response['error'] == 'translated:errors.general.unexpected_error'

    def test_get_companies_when_ok(self, mock_session_manager):
        self.mock_repo.get_companies.return_value = [self.mock_company]
        companies = self.service.get_companies()
        assert companies == [self.mock_company]

    def test_get_company_by_short_name_when_ok(self, mock_session_manager):
        company = self.service.get_company_by_short_name('test_company')
        assert company == self.mock_company

    def test_get_company_users_transforms_data_correctly(self, mock_session_manager):
        # Arrange
        short_name = "test_corp"

        # Mock company existence
        mock_company = MagicMock()
        self.mock_repo.get_company_by_short_name.return_value = mock_company

        # Mock raw data from repo (Tuple: User, Role, LastAccess)
        mock_user = User(
            first_name="John",
            last_name="Doe",
            email="john@test.com",
            verified=True,
            created_at="2023-01-01"
        )
        mock_role = "editor"
        mock_access = "2024-05-20"

        self.mock_repo.get_company_users_with_details.return_value = [
            (mock_user, mock_role, mock_access)
        ]

        # Act
        result = self.service.get_company_users(short_name)

        # Assert
        assert len(result) == 1
        user_dict = result[0]

        assert user_dict['email'] == "john@test.com"
        assert user_dict['role'] == "editor"
        assert user_dict['last_access'] == "2024-05-20"
        # Verificar que se usaron los campos del objeto user
        assert user_dict['first_name'] == "John"
        
    def test_update_user(self, mock_session_manager):
        self.mock_repo.update_user.return_value = self.mock_user
        user = self.service.update_user('fl@opensoft.cl', first_name='fernando')

        assert user == self.mock_user

    def test_verify_account_when_user_not_exist(self, mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None

        response = self.service.verify_account(email='test@email.com')

        assert 'translated:errors.verification.user_not_found' == response['error']

    def test_verify_account_when_exception(self,mock_session_manager):
        self.mock_repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.verify_account(email='test@email.com')

        assert 'translated:errors.general.unexpected_error' == response['error']

    def test_verify_account_when_ok(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        response = self.service.verify_account(email='test@email.com')

        assert 'translated:flash_messages.account_verified_success' == response['message']

    def test_change_password_when_password_mismatch(self,mock_session_manager):
        response = self.service.change_password(
            email='test@email.com',
            temp_code='ABC',
            new_password='pass1',
            confirm_password='pass2'
        )
        assert 'translated:errors.change_password.password_mismatch' == response['error']

    def test_change_passworwd_when_invalid_code(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.temp_code = 'xYhvt'
        response = self.service.change_password(
            email='test@email.com',
            temp_code='ABC',
            new_password='pass1',
            confirm_password='pass1'
        )
        assert 'translated:errors.change_password.invalid_temp_code' == response['error']

    def test_change_password_when_ok(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.temp_code = 'ABC'
        response = self.service.change_password(
            email='test@email.com',
            temp_code=self.mock_user.temp_code,
            new_password='pass1',
            confirm_password='pass1'
        )
        assert 'translated:flash_messages.password_changed_success' == response['message']

    def test_change_password_when_exception(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_repo.update_password.side_effect = Exception('db error')
        response = self.service.change_password(
            email='test@email.com',
            temp_code=self.mock_user.temp_code,
            new_password='pass1',
            confirm_password='pass1'
        )
        assert 'translated:errors.general.unexpected_error' == response['error']

    def test_forgot_password_when_user_not_exist(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = None
        response = self.service.forgot_password(
            company_short_name='test_company',
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )
        assert 'translated:errors.forgot_password.user_not_registered' == response['error']

    def test_forgot_password_when_ok(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        response = self.service.forgot_password(
            company_short_name='test_company',
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )
        assert 'translated:flash_messages.forgot_password_success' == response['message']
        self.mock_mail_service.send_mail.assert_called()

    def test_forgot_password_when_exception(self,mock_session_manager):
        self.mock_repo.get_user_by_email.return_value = self.mock_user
        self.mock_mail_service.send_mail.side_effect = Exception('mail error')
        response = self.service.forgot_password(
            company_short_name='test_company',
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )

        assert 'translated:errors.general.unexpected_error' == response['error']

    def test_new_api_key_when_not_company(self,mock_session_manager):
        self.mock_repo.get_company_by_short_name.return_value = None
        response = self.service.new_api_key(company_short_name='test_company', key_name='key_name')
        assert 'translated:errors.company_not_found' == response['error']

    def test_new_api_key_when_ok(self,mock_session_manager):
        self.mock_repo.get_company_by_short_name.return_value = self.mock_company
        response = self.service.new_api_key(company_short_name='test_company', key_name='key_name')

        self.mock_repo.create_api_key.assert_called()
        assert response['api-key'] != ''

    def test_update_user_language_success(self, mock_session_manager):
        """
        Tests that update_user_language calls the repository with correct arguments
        when the language is valid.
        """
        user_email = "test@example.com"
        new_lang = "en"

        result = self.service.update_user_language(user_email, new_lang)
        assert result['success'] is True

    def test_update_user_language_unsupported_language(self, mock_session_manager):
        """
        Tests that the method returns an error if the language is not supported
        without calling the repository.
        """
        # Arrange
        user_email = "test@example.com"
        new_lang = "fr"  # 'fr' is not in our mocked translations

        # Act
        result = self.service.update_user_language(user_email, new_lang)

        # Assert
        assert result['success'] is False
        assert result['error_message'] == 'translated:errors.general.unsupported_language'

    @patch('iatoolkit.services.profile_service.logging')
    def test_update_user_language_handles_repository_exception(self, mock_logging, mock_session_manager):
        """
        Tests that if the repository fails, an exception is logged and an error is returned.
        """
        # Arrange
        user_email = "test@example.com"
        new_lang = "es"
        self.mock_repo.update_user.side_effect = Exception("Database connection failed")

        result = self.service.update_user_language(user_email, new_lang)
        assert result['success'] is False
