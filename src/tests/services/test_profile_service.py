# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock, patch
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from flask_bcrypt import generate_password_hash
from iatoolkit.repositories.models import User, Company
from iatoolkit.infra.mail_app import MailApp
import os

class TestProfileService:
    @classmethod
    def setup_class(cls):
        cls.patcher = patch.dict(os.environ, {"USER_VERIF_KEY": "mocked_secret_key"})
        cls.patcher.start()

    def setup_method(self):
        self.repo = MagicMock(ProfileRepo)
        self.mail_app = MagicMock(MailApp)
        self.session_context = MagicMock(UserSessionContextService)

        # init the service with the mock
        self.service = ProfileService(
            profile_repo=self.repo,
            session_context_service=self.session_context,
            mail_app=self.mail_app)

        self.mock_user = User(email='test@opensoft.cl',
                            first_name='fernando', last_name='libe',
                            password=generate_password_hash("password").decode("utf-8"), verified=True)

        self.mock_company = Company(name='my company',
                                    short_name='test_company',
                                    )
        self.repo.get_company_by_short_name.return_value = self.mock_company

        self.mock_user.companies = [self.mock_company, Company(id=2, name="Test Company 2")]

    def teardown_method(self):
        self.patcher.stop()

    def test_login_when_exception(self):
        self.repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.login(self.mock_company.short_name,
                                      'fernando',
                                      'a password'
                                      )

        assert not response['success']  and response['message'] == "an error"

    def test_login_when_user_not_exist(self):
        self.repo.get_user_by_email.return_value = None
        response = self.service.login(self.mock_company.short_name,
                                      'fernando',
                                      'a password')

        assert not response['success']  and response['message'] == "Usuario no encontrado"

    def test_login_when_invalid_password(self):
        # Simula un usuario válido pero con una contraseña incorrecta
        mock_user = MagicMock()
        mock_user.password = generate_password_hash("correct_password").decode("utf-8")
        mock_user.verified = True
        self.repo.get_user_by_email.return_value = mock_user

        response = self.service.login(self.mock_company.short_name,
                                      'fernando',
                                      'wrong_password'
                                      )

        assert not response['success']  and response['message'] =="Contraseña inválida"

    def test_login_when_company_not_in_user_companies(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.password = generate_password_hash("password").decode("utf-8")
        self.mock_user.companies = [Company(id=2, name="Test Company 2")]

        response = self.service.login(self.mock_company.short_name,
                                      'fernando',
                                      'password'
                                      )

        assert not response['success']  and response['message'] == "Usuario no esta autorizado para esta empresa"

    def test_login_when_unverified_account(self):
        self.mock_user.password = generate_password_hash("password").decode("utf-8")
        self.mock_user.verified = False
        self.repo.get_user_by_email.return_value = self.mock_user

        response = self.service.login(self.mock_company.short_name,
                                      'fernando',
                                      'password'
                                      )

        assert not response['success']  and "Tu cuenta no ha sido verificada" in response['message']

    @patch("iatoolkit.services.profile_service.SessionManager")
    def test_login_when_ok(self, mock_session):
        mock_session.set.return_value = True
        self.mock_user.password = generate_password_hash("password").decode("utf-8")
        self.repo.get_user_by_email.return_value = self.mock_user

        response = self.service.login(self.mock_company.short_name,
                                      'test@email.com',
                                      'password'
                                      )

        assert response['success'] and response['user'] == self.mock_user

    def test_signup_when_invalid_company(self):
        self.repo.get_company_by_short_name.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "empresa test_company no existe" in response['error']

    def test_signup_when_user_exist_and_invalid_password(self):
        self.mock_user.password = generate_password_hash("password").decode("utf-8")
        self.repo.get_user_by_email.return_value = self.mock_user

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="invalid_password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "contraseña es incorrecta" in response['error']


    def test_signup_when_user_exist_and_already_register(self):
        self.repo.get_user_by_email.return_value = self.mock_user

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "Usuario ya registrado" in response['error']

    def test_signup_when_user_exist_and_not_in_company(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.companies = []

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "Usuario asociado" in response['message']
        self.repo.save_user.assert_called_once()

    def test_signup_when_passwords_different(self):
        self.repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password1", confirm_password="Password2$1",
            verification_url='http://verification'
        )

        assert "contraseñas no coinciden" in response['error']

    def test_signup_when_passwords_incorrect2(self):
        self.repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password", confirm_password="Password",
            verification_url='http://verification'
        )

        assert "número" in response['error']

    def test_signup_when_passwords_incorrect3(self):
        self.repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Passw1", confirm_password="Passw1",
            verification_url='http://verification'
        )

        assert "8 caracteres" in response['error']

    def test_signup_when_passwords_incorrect4(self):
        self.repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password123", confirm_password="password123",
            verification_url='http://verification'
        )

        assert "mayúscula" in response['error']

    def test_signup_when_passwords_incorrect5(self):
        self.repo.get_user_by_email.return_value = None

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password123", confirm_password="Password123",
            verification_url='http://verification'
        )

        assert "especial" in response['error']

    def test_signup_when_ok(self):
        self.repo.get_user_by_email.return_value = None
        self.mail_app.send_email.return_value = True

        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="Password$1", confirm_password="Password$1",
            verification_url='http://verification'
        )

        assert "Registro exitoso" in response['message']
        self.mail_app.send_email.assert_called()

    def test_signup_when_exception(self):
        self.repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.signup(
            self.mock_company.short_name,
            email='test@email.com',
            first_name='Test', last_name='User',
            password="password", confirm_password="password",
            verification_url='http://verification'
        )

        assert "an error" == response['error']

    def test_get_companies_when_ok(self):
        self.repo.get_companies.return_value = [self.mock_company]
        companies = self.service.get_companies()
        assert companies == [self.mock_company]

    def test_get_company_by_short_name_when_ok(self):
        company = self.service.get_company_by_short_name('test_company')
        assert company == self.mock_company

    def test_update_user(self):
        self.repo.update_user.return_value = self.mock_user
        user = self.service.update_user('fl@opensoft.cl', first_name='fernando')

        assert user == self.mock_user

    def test_verify_account_when_user_not_exist(self):
        self.repo.get_user_by_email.return_value = None

        response = self.service.verify_account(email='test@email.com')

        assert "El usuario no existe." in response['error']

    def test_verify_account_when_exception(self):
        self.repo.get_user_by_email.side_effect = Exception('an error')
        response = self.service.verify_account(email='test@email.com')

        assert "an error" == response['error']

    def test_verify_account_when_ok(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        response = self.service.verify_account(email='test@email.com')

        assert "cuenta ha sido verificada" in response['message']

    def test_change_password_when_password_mismatch(self):
        response = self.service.change_password(
            email='test@email.com',
            temp_code='ABC',
            new_password='pass1',
            confirm_password='pass2'
        )
        assert "contraseñas no coinciden" in response['error']

    def test_change_passworwd_when_invalid_code(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.temp_code = 'xYhvt'
        response = self.service.change_password(
            email='test@email.com',
            temp_code='ABC',
            new_password='pass1',
            confirm_password='pass1'
        )
        assert "código temporal no es válido" in response['error']

    def test_change_password_when_ok(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        self.mock_user.temp_code = 'ABC'
        response = self.service.change_password(
            email='test@email.com',
            temp_code=self.mock_user.temp_code,
            new_password='pass1',
            confirm_password='pass1'
        )
        assert "clave se cambio correctamente" in response['message']

    def test_change_password_when_exception(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        self.repo.update_password.side_effect = Exception('db error')
        response = self.service.change_password(
            email='test@email.com',
            temp_code=self.mock_user.temp_code,
            new_password='pass1',
            confirm_password='pass1'
        )
        assert "db error" == response['error']

    def test_forgot_password_when_user_not_exist(self):
        self.repo.get_user_by_email.return_value = None
        response = self.service.forgot_password(
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )
        assert "El usuario no existe" in response['error']

    def test_forgot_password_when_ok(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        response = self.service.forgot_password(
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )
        assert "se envio mail para cambio de clave" in response['message']
        self.mail_app.send_email.assert_called()

    def test_forgot_password_when_exception(self):
        self.repo.get_user_by_email.return_value = self.mock_user
        self.mail_app.send_email.side_effect = Exception('mail error')
        response = self.service.forgot_password(
            email='test@email.com',
            reset_url='http://a_reset_utl'
        )

        assert "mail error" == response['error']

    def test_new_api_key_when_not_company(self):
        self.repo.get_company_by_short_name.return_value = None
        response = self.service.new_api_key(company_short_name='test_company')
        assert "test_company no existe" in response['error']

    def test_new_api_key_when_ok(self):
        self.repo.get_company_by_short_name.return_value = self.mock_company
        response = self.service.new_api_key(company_short_name='test_company')

        self.repo.create_api_key.assert_called()
        assert response['api-key'] != ''

