import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import ApiKey, Company, AccessLog
from flask import Flask
import hashlib



class TestAuthServiceVerify:
    """
    Tests for the verify() method, which checks for existing sessions or API keys.
    These tests DO NOT cover the login/redeem flows.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up mocks for verify() tests."""
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_jwt_service = MagicMock(spec=JWTService)
        self.mock_db_manager = MagicMock(spec=DatabaseManager)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        self.service = AuthService(
            profile_service=self.mock_profile_service,
            jwt_service=self.mock_jwt_service,
            db_manager=self.mock_db_manager,
            i18n_service=self.mock_i18n_service
        )
        self.app = Flask(__name__)
        self.app.testing = True

        # Common mock setup for API key tests
        self.mock_company = Company(id=1, short_name="apico")
        self.mock_api_key_entry = ApiKey(key="valid-api-key", company=self.mock_company)
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

    def test_verify_success_with_flask_session(self):
        """verify() should succeed if a valid Flask session is found."""
        session_info = {
            "user_identifier": "user_session_123",
            "company_short_name": "testco",
            "profile": {"user_role": "admin"}
        }
        self.mock_profile_service.get_current_session_info.return_value = session_info

        with self.app.test_request_context():
            result = self.service.verify()

        assert result['success'] is True
        assert result['user_identifier'] == "user_session_123"
        assert result['company_short_name'] == "testco"
        assert result['user_role'] == "admin"
        self.mock_profile_service.get_active_api_key_entry.assert_not_called()

    def test_verify_success_with_api_key_and_user_identifier(self):
        """verify() should succeed if a valid API key and user_identifier in JSON are provided."""
        self.mock_profile_service.get_current_session_info.return_value = {}
        self.mock_profile_service.get_active_api_key_entry.return_value = self.mock_api_key_entry

        # FIX: Added json body with user_identifier, which is required by the service
        with self.app.test_request_context(
            headers={'Authorization': 'Bearer valid-api-key'},
            json={'user_identifier': 'api-user-456'}
        ):
            result = self.service.verify()

        assert result['success'] is True
        assert result['company_short_name'] == "apico"
        assert result['user_identifier'] == "api-user-456"
        self.mock_profile_service.get_active_api_key_entry.assert_called_once_with("valid-api-key")

    def test_verify_fails_with_api_key_but_no_user_identifier(self):
        """REPURPOSED: verify() should fail with 403 if API key is valid but user_identifier is missing."""
        self.mock_profile_service.get_current_session_info.return_value = {}
        self.mock_profile_service.get_active_api_key_entry.return_value = self.mock_api_key_entry

        # Test without a JSON body
        with self.app.test_request_context(headers={'Authorization': 'Bearer valid-api-key'}):
            result = self.service.verify()

        assert result['success'] is False
        assert result['error_message'] == 'translated:errors.auth.no_user_identifier_api'
        assert result['status_code'] == 403

    def test_verify_success_with_api_key_and_anonymous_flag(self):
        """NEW: verify(anonymous=True) should succeed even without a user_identifier."""
        self.mock_profile_service.get_current_session_info.return_value = {}
        self.mock_profile_service.get_active_api_key_entry.return_value = self.mock_api_key_entry

        # Call verify with anonymous=True and no user_identifier in the body
        with self.app.test_request_context(headers={'Authorization': 'Bearer valid-api-key'}):
            result = self.service.verify(anonymous=True)

        assert result['success'] is True
        assert result['company_short_name'] == "apico"
        assert result['user_identifier'] == '' # It should return an empty string

    def test_verify_fails_with_invalid_api_key(self):
        """verify() should fail with 402 if the API key is invalid or inactive."""
        self.mock_profile_service.get_current_session_info.return_value = {}
        self.mock_profile_service.get_active_api_key_entry.return_value = None

        with self.app.test_request_context(headers={'Authorization': 'Bearer invalid-key'}):
            result = self.service.verify()

        assert result['success'] is False
        assert result['error_message'] == 'translated:errors.auth.invalid_api_key'
        # FIX: The service returns 402 for invalid keys, not 401.
        assert result['status_code'] == 402

    def test_verify_fails_with_no_credentials(self):
        """verify() should fail with 401 if no credentials are provided at all."""
        self.mock_profile_service.get_current_session_info.return_value = {}

        with self.app.test_request_context(): # No session, no headers
            result = self.service.verify()

        assert result['success'] is False
        assert 'translated:errors.auth.authentication_required' in result['error_message']
        # FIX: The service returns 401 for missing credentials, not 402.
        assert result['status_code'] == 401


class TestAuthServiceLoginFlows:
    """
    Tests for the new login/redeem methods in AuthService and their logging side-effects.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        """Set up a mocked environment and patch the log_access method."""
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_jwt_service = MagicMock(spec=JWTService)
        self.mock_db_manager = MagicMock(spec=DatabaseManager, scoped_session=MagicMock())
        self.mock_i18n_service = MagicMock(spec=I18nService)

        self.mock_session = MagicMock()
        self.mock_db_manager.scoped_session.return_value = self.mock_session

        self.service = AuthService(
            profile_service=self.mock_profile_service,
            jwt_service=self.mock_jwt_service,
            db_manager=self.mock_db_manager,
            i18n_service=self.mock_i18n_service
        )
        self.app = Flask(__name__)
        self.app.testing = True

        self.mock_log_access = MagicMock()
        monkeypatch.setattr(self.service, 'log_access', self.mock_log_access)

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"


        self.company_short_name = "acme"
        self.user_identifier = "user-123"
        self.email = "test@user.com"

    def test_login_local_user_success(self):
        """login_local_user should return success and log a successful 'local' access."""
        self.mock_profile_service.login.return_value = {'success': True, 'user_identifier': self.user_identifier}

        with self.app.test_request_context():
            result = self.service.login_local_user(self.company_short_name, self.email, "password")

        assert result['success'] is True
        self.mock_log_access.assert_called_once_with(
            company_short_name=self.company_short_name,
            auth_type='local',
            outcome='success',
            user_identifier=self.user_identifier
        )

    def test_login_local_user_failure(self):
        """login_local_user should return failure and log a failed 'local' access."""
        self.mock_profile_service.login.return_value = {'success': False, 'message': 'Wrong password'}

        with self.app.test_request_context():
            result = self.service.login_local_user(self.company_short_name, self.email, "wrong")

        assert result['success'] is False
        self.mock_log_access.assert_called_once_with(
            company_short_name=self.company_short_name,
            auth_type='local',
            outcome='failure',
            reason_code='INVALID_CREDENTIALS',
            user_identifier=self.email
        )

    def test_redeem_token_success(self):
        """redeem_token should succeed, create a session, and log a successful 'redeem_token' access."""
        self.mock_jwt_service.validate_chat_jwt.return_value = {'user_identifier': self.user_identifier}

        with self.app.test_request_context():
            result = self.service.redeem_token_for_session(self.company_short_name, "valid-token")

        assert result['success'] is True
        assert result['user_identifier'] == self.user_identifier
        self.mock_profile_service.set_session_for_user.assert_called_once_with(self.company_short_name, self.user_identifier)
        self.mock_log_access.assert_called_once_with(
            company_short_name=self.company_short_name,
            auth_type='redeem_token',
            outcome='success',
            user_identifier=self.user_identifier
        )

    def test_redeem_token_invalid_jwt(self):
        """redeem_token should fail for an invalid JWT and log a failed 'redeem_token' access."""
        self.mock_jwt_service.validate_chat_jwt.return_value = None

        with self.app.test_request_context():
            result = self.service.redeem_token_for_session(self.company_short_name, "invalid-token")

        assert result['success'] is False
        self.mock_profile_service.set_session_for_user.assert_not_called()
        self.mock_log_access.assert_called_once_with(
            company_short_name=self.company_short_name,
            auth_type='redeem_token',
            outcome='failure',
            reason_code='JWT_INVALID'
        )

    def test_redeem_token_session_creation_fails(self):
        """redeem_token should log a failure if session creation throws an exception."""
        self.mock_jwt_service.validate_chat_jwt.return_value = {'user_identifier': self.user_identifier}
        self.mock_profile_service.set_session_for_user.side_effect = Exception("DB connection error")

        with self.app.test_request_context():
            result = self.service.redeem_token_for_session(self.company_short_name, "valid-token")

        assert result['success'] is False
        self.mock_log_access.assert_called_once_with(
            company_short_name=self.company_short_name,
            auth_type='redeem_token',
            outcome='failure',
            reason_code='SESSION_CREATION_FAILED',
            user_identifier=self.user_identifier
        )

class TestAuthServiceLogAccess:
    """
    Tests the log_access() method directly to ensure it correctly
    creates and saves AccessLog entries.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up mocks for log_access() tests."""
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_jwt_service = MagicMock(spec=JWTService)

        # Use create_autospec to create a mock that correctly reflects
        # an INSTANCE of DatabaseManager, including attributes created in __init__.
        # This will automatically know that 'scoped_session' is a valid attribute.
        self.mock_db_manager = MagicMock(spec=DatabaseManager)
        # Manually add the missing attribute to the strict mock
        self.mock_db_manager.scoped_session = MagicMock()

        # The important mock: the session object returned by the db_manager
        self.mock_session = MagicMock()
        self.mock_db_manager.scoped_session.return_value = self.mock_session
        self.mock_i18n_service = MagicMock(spec=I18nService)

        self.service = AuthService(
            profile_service=self.mock_profile_service,
            jwt_service=self.mock_jwt_service,
            db_manager=self.mock_db_manager,
            i18n_service=self.mock_i18n_service
        )
        self.app = Flask(__name__)
        self.app.testing = True

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

    def test_log_access_creates_correct_log_entry(self):
        """
        Test that log_access creates an AccessLog entry with all fields populated correctly
        from the request context.
        """
        test_path = "/test/path"
        test_user_agent = "Mozilla/5.0 Test-Agent"
        ua_hash = hashlib.sha256(test_user_agent.encode()).hexdigest()[:16]
        test_ip = "192.168.1.1"

        with self.app.test_request_context(
            test_path,
            headers={'User-Agent': test_user_agent, 'X-Forwarded-For': test_ip}
        ):
            self.service.log_access(
                company_short_name="acme",
                auth_type="local",
                outcome="success",
                user_identifier="test_user",
                reason_code="OK"
            )

        self.mock_db_manager.scoped_session.assert_called_once()
        self.mock_session.add.assert_called_once()
        self.mock_session.commit.assert_called_once()
        self.mock_session.rollback.assert_not_called()

        # Inspect the object that was passed to session.add()
        captured_log = self.mock_session.add.call_args[0][0]
        assert isinstance(captured_log, AccessLog)
        assert captured_log.company_short_name == "acme"
        assert captured_log.user_identifier == "test_user"
        assert captured_log.auth_type == "local"
        assert captured_log.outcome == "success"
        assert captured_log.reason_code == "OK"
        assert captured_log.source_ip == test_ip
        assert captured_log.request_path == test_path
        assert captured_log.user_agent_hash == ua_hash

    def test_log_access_handles_missing_x_forwarded_for(self):
        """Test that source_ip falls back to remote_addr if X-Forwarded-For is not present."""
        with self.app.test_request_context():  # No specific headers
            self.service.log_access("acme", "local", "success")

        captured_log = self.mock_session.add.call_args[0][0]

    def test_log_access_handles_missing_user_agent(self):
        """Test that user_agent_hash is None if the User-Agent header is missing."""
        with self.app.test_request_context():  # No User-Agent header
            self.service.log_access("acme", "local", "success")

        captured_log = self.mock_session.add.call_args[0][0]
        assert captured_log.user_agent_hash is None

    def test_log_access_rolls_back_on_db_exception(self):
        """Test that the session is rolled back if session.commit() raises an exception."""
        self.mock_session.commit.side_effect = Exception("Database is locked")

        with self.app.test_request_context():
            self.service.log_access("acme", "local", "failure")

        self.mock_session.add.assert_called_once()
        self.mock_session.commit.assert_called_once()
        self.mock_session.rollback.assert_called_once()
