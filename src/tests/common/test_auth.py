# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import Flask, Response
from unittest.mock import patch, MagicMock
from iatoolkit.common.auth import IAuthentication
import pytest
from datetime import datetime, timezone
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.jwt_service import JWTService
from werkzeug.exceptions import HTTPException

CURRENT_TIME = datetime.now(timezone.utc).timestamp()


class TestAuth:

    def setup_method(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True

        self.profile_service = MagicMock(spec=ProfileService)
        self.jwt_service = MagicMock(spec=JWTService)
        self.iauth_service = IAuthentication(
            profile_service=self.profile_service,
            jwt_service=self.jwt_service
        )

        @self.app.route('/<company_short_name>/protected')
        def protected(company_short_name):
            with self.app.test_request_context():
                auth_result = self.iauth_service.check_if_user_is_logged_in(company_short_name)
            if isinstance(auth_result, Response):
                return auth_result
            return "Access Granted", 200

        @self.app.route('/login')
        def login():
            return "Login Page", 200

        self.client = self.app.test_client()

    def teardown_method(self):
        patch.stopall()

    # --- Pruebas para check_if_user_is_logged_in (de TestAuth original) ---

    def test_allows_access_if_user_authenticated_and_active(self):
        with patch('iatoolkit.common.auth.SessionManager.get') as mock_get, \
             patch('iatoolkit.common.auth.SessionManager.set') as mock_set:
            mock_get.side_effect = lambda key, default=None: {
                'user_id': 1,
                'user': {'id': 1, 'username': 'test_user'},
                'company_short_name': 'test_company',
                'last_activity': CURRENT_TIME
            }.get(key, default)

            response = self.client.get('/test_company/protected')

            assert response.status_code == 200
            assert response.data == b"Access Granted"
            mock_set.assert_called_with("last_activity", pytest.approx(CURRENT_TIME, 1))

    def test_redirect_if_user_not_authenticated(self):
        with patch('iatoolkit.common.auth.SessionManager.get') as mock_get:
            mock_get.side_effect = lambda key, default=None: None if key == "user" else default
            response = self.client.get('/test_company/protected')
            assert response.status_code == 302
            assert "/login" in response.headers['Location']

    def test_redirect_if_last_activity_missing(self):
        with patch('iatoolkit.common.auth.SessionManager.get') as mock_get, \
             patch('iatoolkit.common.auth.SessionManager.clear') as mock_clear:
            mock_get.side_effect = lambda key, default=None: {
                'user_id': 1,
                'user': {'id': 1, 'username': 'test_user'},
                'company_short_name': 'test_company'
            }.get(key, default)

            response = self.client.get('/test_company/protected')

            assert response.status_code == 302
            assert "/login" in response.headers['Location']
            mock_clear.assert_called_once()

    # --- Pruebas para verify (de TestAuthVerify original) ---

    def test_verify_with_jwt_success(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key:
            mock_auth_jwt.return_value = (123, 'ext_user_1', None)

            with self.app.test_request_context():
                result = self.iauth_service.verify('some_company')

            assert result['success'] is True
            assert result['company_id'] == 123
            assert result['external_user_id'] == 'ext_user_1'
            mock_auth_jwt.assert_called_once_with('some_company')
            mock_auth_api_key.assert_not_called()

    def test_verify_with_jwt_failure(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key:
            mock_auth_jwt.return_value = (None, None, "Error de JWT")

            with self.app.test_request_context():
                result = self.iauth_service.verify('some_company')

            assert result == {"error_message": "Fallo de autenticación JWT"}
            mock_auth_api_key.assert_not_called()

    def test_verify_with_api_key_success(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key, \
             patch.object(self.iauth_service, 'check_if_user_is_logged_in') as mock_check_if_logged_in:
            mock_auth_jwt.return_value = (None, None, None)
            mock_auth_api_key.return_value = (456, None)

            with self.app.test_request_context():
                result = self.iauth_service.verify('some_company', body_external_user_id='body_user_2')

            assert result['success'] is True
            assert result['company_id'] == 456
            assert result['external_user_id'] == 'body_user_2'
            mock_auth_api_key.assert_called_once_with('some_company')
            mock_check_if_logged_in.assert_not_called()

    def test_verify_with_api_key_failure(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key:
            mock_auth_jwt.return_value = (None, None, None)
            mock_auth_api_key.return_value = (None, "Error de API Key")

            with self.app.test_request_context():
                result = self.iauth_service.verify('some_company')

            assert result == {"error_message": "Error de API Key"}

    def test_verify_with_session_success(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key, \
             patch.object(self.iauth_service, 'check_if_user_is_logged_in') as mock_check_if_logged_in, \
             patch('iatoolkit.common.auth.SessionManager.get') as mock_session_get:
            mock_auth_jwt.return_value = (None, None, None)
            mock_auth_api_key.return_value = (None, None)
            mock_check_if_logged_in.return_value = None
            mock_session_get.side_effect = lambda key, default=None: {'user_id': 789, 'company_id': 999}.get(key,
                                                                                                              default)

            with self.app.test_request_context():
                result = self.iauth_service.verify('some_company')

            assert result['success'] is True
            assert result['company_id'] == 999
            assert result['local_user_id'] == 789
            mock_check_if_logged_in.assert_called_once_with('some_company')

    def test_verify_with_session_incomplete_data(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key, \
             patch.object(self.iauth_service, 'check_if_user_is_logged_in') as mock_check_if_logged_in, \
             patch('iatoolkit.common.auth.SessionManager.get') as mock_session_get:
            mock_auth_jwt.return_value = (None, None, None)
            mock_auth_api_key.return_value = (None, None)
            mock_check_if_logged_in.return_value = None
            mock_session_get.side_effect = lambda key, default=None: {'user_id': 789}.get(key, default)

            with self.app.test_request_context():
                result = self.iauth_service.verify('some_company')

            assert result == {"error_message": "Fallo interno en la autenticación o no autenticado"}

    def test_verify_with_session_check_fails_by_exception(self):
        with patch.object(self.iauth_service, '_authenticate_via_chat_jwt') as mock_auth_jwt, \
             patch.object(self.iauth_service, '_authenticate_via_api_key') as mock_auth_api_key, \
             patch.object(self.iauth_service, 'check_if_user_is_logged_in') as mock_check_if_logged_in:
            mock_auth_jwt.return_value = (None, None, None)
            mock_auth_api_key.return_value = (None, None)
            mock_check_if_logged_in.side_effect = HTTPException

            with self.app.test_request_context(), pytest.raises(HTTPException):
                self.iauth_service.verify('some_company')

    # --- Nuevas pruebas para _authenticate_via_api_key ---

    def test_authenticate_via_api_key_success(self):
        with self.app.test_request_context(headers={'Authorization': 'Bearer valid_key'}):
            mock_api_entry = MagicMock()
            mock_api_entry.company.short_name = 'test_company'
            mock_api_entry.company_id = 123
            self.profile_service.get_active_api_key_entry.return_value = mock_api_entry

            company_id, error = self.iauth_service._authenticate_via_api_key('test_company')

            assert company_id == 123
            assert error is None
            self.profile_service.get_active_api_key_entry.assert_called_once_with('valid_key')

    def test_authenticate_via_api_key_no_header(self):
        with self.app.test_request_context(headers={}):
            company_id, error = self.iauth_service._authenticate_via_api_key('test_company')
            assert company_id is None
            assert error is None
            self.profile_service.get_active_api_key_entry.assert_not_called()

    def test_authenticate_via_api_key_wrong_scheme(self):
        with self.app.test_request_context(headers={'Authorization': 'Basic some_token'}):
            company_id, error = self.iauth_service._authenticate_via_api_key('test_company')
            assert company_id is None
            assert error is None
            self.profile_service.get_active_api_key_entry.assert_not_called()

    def test_authenticate_via_api_key_inactive_key(self):
        with self.app.test_request_context(headers={'Authorization': 'Bearer inactive_key'}):
            self.profile_service.get_active_api_key_entry.return_value = None
            company_id, error = self.iauth_service._authenticate_via_api_key('test_company')
            assert company_id is None
            assert error == "API Key inválida o inactiva"

    def test_authenticate_via_api_key_company_mismatch(self):
        with self.app.test_request_context(headers={'Authorization': 'Bearer valid_key'}):
            mock_api_entry = MagicMock()
            mock_api_entry.company.short_name = 'other_company'
            self.profile_service.get_active_api_key_entry.return_value = mock_api_entry

            company_id, error = self.iauth_service._authenticate_via_api_key('test_company')
            assert company_id is None
            assert error == "API Key no es válida para la compañía test_company"

    def test_authenticate_via_api_key_repo_exception(self):
        with self.app.test_request_context(headers={'Authorization': 'Bearer any_key'}):
            self.profile_service.get_active_api_key_entry.side_effect = Exception("DB error")
            company_id, error = self.iauth_service._authenticate_via_api_key('test_company')
            assert company_id is None
            assert error == "Error interno del servidor al validar API Key"

    # --- Nuevas pruebas para _authenticate_via_chat_jwt ---

    def test_authenticate_via_chat_jwt_success(self):
        with self.app.test_request_context(headers={'X-Chat-Token': 'valid_jwt'}):
            self.jwt_service.validate_chat_jwt.return_value = {'company_id': 123, 'external_user_id': 'ext_user'}
            company_id, external_user_id, error = self.iauth_service._authenticate_via_chat_jwt('test_company')
            assert company_id == 123
            assert external_user_id == 'ext_user'
            assert error is None
            self.jwt_service.validate_chat_jwt.assert_called_once_with('valid_jwt', 'test_company')

    def test_authenticate_via_chat_jwt_no_header(self):
        with self.app.test_request_context(headers={}):
            company_id, external_user_id, error = self.iauth_service._authenticate_via_chat_jwt('test_company')
            assert company_id is None
            assert external_user_id is None
            assert error is None
            self.jwt_service.validate_chat_jwt.assert_not_called()

    def test_authenticate_via_chat_jwt_validation_fails(self):
        with self.app.test_request_context(headers={'X-Chat-Token': 'invalid_jwt'}):
            self.jwt_service.validate_chat_jwt.return_value = None
            company_id, external_user_id, error = self.iauth_service._authenticate_via_chat_jwt('test_company')
            assert company_id is None
            assert external_user_id is None
            assert error == "Token de chat expirado, debes reingresar al chat"

    def test_authenticate_via_chat_jwt_incomplete_payload_no_company_id(self):
        with self.app.test_request_context(headers={'X-Chat-Token': 'valid_jwt'}):
            self.jwt_service.validate_chat_jwt.return_value = {'external_user_id': 'ext_user'}
            company_id, external_user_id, error = self.iauth_service._authenticate_via_chat_jwt('test_company')
            assert company_id is None
            assert external_user_id is None
            assert error == "Token de chat con formato interno incorrecto"

    def test_authenticate_via_chat_jwt_incomplete_payload_no_external_id(self):
        with self.app.test_request_context(headers={'X-Chat-Token': 'valid_jwt'}):
            self.jwt_service.validate_chat_jwt.return_value = {'company_id': 123}
            company_id, external_user_id, error = self.iauth_service._authenticate_via_chat_jwt('test_company')
            assert company_id is None
            assert external_user_id is None
            assert error == "Token de chat con formato interno incorrecto"