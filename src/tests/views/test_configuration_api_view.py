import pytest
from flask import Flask
from unittest.mock import MagicMock, patch

from iatoolkit.views.configuration_api_view import ConfigurationApiView
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.views.configuration_api_view import ConfigurationApiView, ValidateConfigurationApiView # Importar la nueva clase


MOCK_COMPANY_SHORT_NAME = "sample_company"

class TestConfigurationApiView:
    """
    Tests for ConfigurationApiView, covering GET, PATCH, and POST methods.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a Flask environment and mocks before each test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()
        self.config_url = f'/{MOCK_COMPANY_SHORT_NAME}/api/config'
        self.load_config_url = f'/{MOCK_COMPANY_SHORT_NAME}/api/load_configuration'
        self.validate_url = f"/{MOCK_COMPANY_SHORT_NAME}/api/config/validate"

        # Mocks for injected services
        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_config_service = MagicMock(spec=ConfigurationService)

        # Register view with mocked dependencies
        view_func = ConfigurationApiView.as_view(
            "load_company_config_api",
            configuration_service=self.mock_config_service,
            profile_service=self.mock_profile_service,
            auth_service=self.mock_auth_service,
        )

        # Enable GET, PATCH, POST methods
        self.app.add_url_rule(
            "/<company_short_name>/api/config",
            view_func=view_func,
            methods=["GET", "PATCH", "POST"],
        )
        self.app.add_url_rule(
            "/<company_short_name>/api/load_configuration",
            view_func=view_func,
            methods=["GET"],
            defaults={"action": "load_configuration"},
        )

        # Register the view for validation
        validate_view_func = ValidateConfigurationApiView.as_view(
            "validate_company_config_api",
            configuration_service=self.mock_config_service,
            auth_service=self.mock_auth_service,
        )

        self.app.add_url_rule(
            "/<company_short_name>/api/config/validate",
            view_func=validate_view_func,
            methods=["GET"],
        )

        # Default: Successful authentication
        self.mock_auth_service.verify.return_value = {
            "success": True,
            "company_short_name": MOCK_COMPANY_SHORT_NAME,
            "user_identifier": "user@test.com",
        }

    # --- GET Tests (Loading Configuration) ---

    def test_get_fails_if_auth_fails(self):
        """Should return auth status code (401) if authentication fails."""
        self.mock_auth_service.verify.return_value = {
            "success": False,
            "error_message": "Invalid API Key",
            "status_code": 401,
        }

        resp = self.client.get(self.config_url)

        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert data["error_message"] == "Invalid API Key"
        self.mock_profile_service.get_company_by_short_name.assert_not_called()
        self.mock_config_service.load_configuration.assert_not_called()

    def test_get_company_not_found_returns_404(self):
        """Should return 404 if the company does not exist."""
        self.mock_profile_service.get_company_by_short_name.return_value = None

        resp = self.client.get(self.config_url)

        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "company not found."
        self.mock_config_service.load_configuration.assert_not_called()

    def test_get_success_without_errors(self):
        """When load_configuration returns no errors, it should respond with 200."""
        # Arrange
        mock_company = MagicMock()
        self.mock_profile_service.get_company_by_short_name.return_value = mock_company

        config = {"id": MOCK_COMPANY_SHORT_NAME, "name": "Sample Company", "company": mock_company}
        errors = []
        self.mock_config_service.load_configuration.return_value = (config, errors)

        # Act
        resp = self.client.get(self.config_url)

        # Assert
        assert resp.status_code == 200
        data = resp.get_json()
        assert "config" in data
        assert data["config"]["id"] == MOCK_COMPANY_SHORT_NAME
        # The view removes the 'company' key from the config
        assert "company" not in data["config"]
        # Updated assertion: View returns errors list directly, not nested
        assert data["errors"] == []
        self.mock_config_service.load_configuration.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)

    def test_get_with_errors_returns_400(self):
        """When load_configuration returns errors, it should respond with 400."""
        mock_company = MagicMock()
        self.mock_profile_service.get_company_by_short_name.return_value = mock_company

        config = {"id": MOCK_COMPANY_SHORT_NAME, "name": "Sample Company"}
        errors = ["validation error 1", "validation error 2"]
        self.mock_config_service.load_configuration.return_value = (config, errors)

        resp = self.client.get(self.config_url)

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["config"]["id"] == MOCK_COMPANY_SHORT_NAME
        # Updated assertion: View returns errors list directly, not nested
        assert data["errors"] == errors
        self.mock_config_service.load_configuration.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)

    def test_get_when_exception(self):
        """If an unexpected exception occurs, it should return 500 and status 'error'."""
        mock_company = MagicMock()
        self.mock_profile_service.get_company_by_short_name.return_value = mock_company

        self.mock_config_service.load_configuration.side_effect = Exception("boom")

        resp = self.client.get(self.config_url)

        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"

    def test_get_load_configuration_endpoint_triggers_runtime_refresh(self):
        mock_company = MagicMock()
        self.mock_profile_service.get_company_by_short_name.return_value = mock_company
        config = {"id": MOCK_COMPANY_SHORT_NAME, "name": "Sample Company", "company": mock_company}
        errors = []
        self.mock_config_service.load_configuration.return_value = (config, errors)

        with patch.object(
            ConfigurationApiView,
            "_refresh_runtime_clients",
            return_value={"llm_proxy": True, "embedding_clients": True, "sql_connections": True},
        ) as mock_runtime_refresh:
            resp = self.client.get(self.load_config_url)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["errors"] == []
        assert data["runtime_refresh"] == {
            "llm_proxy": True,
            "embedding_clients": True,
            "sql_connections": True,
        }
        self.mock_config_service.invalidate_configuration_cache.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)
        self.mock_config_service.register_data_sources.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            config=config,
        )
        mock_runtime_refresh.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)

    # --- PATCH Tests (Update Configuration) ---

    def test_patch_fails_auth(self):
        """PATCH should fail if authentication fails (requires valid user)."""
        self.mock_auth_service.verify.return_value = {"success": False, "status_code": 401}

        resp = self.client.patch(self.config_url, json={})

        assert resp.status_code == 401
        self.mock_config_service.update_configuration_key.assert_not_called()

    def test_patch_missing_key(self):
        """PATCH should return 400 if 'key' is missing from payload."""
        resp = self.client.patch(self.config_url, json={"value": "foo"})

        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'Missing "key" in payload'

    def test_patch_success(self):
        """PATCH should return 200 and the updated config on success."""
        payload = {"key": "llm.model", "value": "gpt-5"}

        # Mock service returning success (valid config, no errors)
        updated_config = {"llm": {"model": "gpt-5"}, "company": MagicMock()} # 'company' obj to ensure it gets removed
        self.mock_config_service.update_configuration_key.return_value = (updated_config, [])

        resp = self.client.patch(self.config_url, json=payload)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['config']['llm']['model'] == 'gpt-5'
        assert 'company' not in data['config']

        self.mock_config_service.update_configuration_key.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, "llm.model", "gpt-5"
        )

    def test_patch_validation_error(self):
        """PATCH should return 400 if the update causes validation errors."""
        payload = {"key": "tools", "value": []}

        # Mock service returning validation errors
        updated_config = {"tools": []}
        errors = ["Missing required tools"]
        self.mock_config_service.update_configuration_key.return_value = (updated_config, errors)

        resp = self.client.patch(self.config_url, json=payload)

        assert resp.status_code == 400
        data = resp.get_json()
        assert data['status'] == 'invalid'
        assert data['errors'] == errors
        assert data['config'] == updated_config

    def test_patch_file_not_found(self):
        """PATCH should return 404 if the configuration file is not found."""
        self.mock_config_service.update_configuration_key.side_effect = FileNotFoundError()

        resp = self.client.patch(self.config_url, json={"key": "k", "value": "v"})

        assert resp.status_code == 404
        assert resp.get_json()['error'] == 'Configuration file not found'

    def test_patch_internal_error(self):
        """PATCH should return 500 on unexpected exceptions."""
        self.mock_config_service.update_configuration_key.side_effect = Exception("Disk error")

        resp = self.client.patch(self.config_url, json={"key": "k", "value": "v"})

        assert resp.status_code == 500
        assert resp.get_json()['status'] == 'error'

    # --- POST Tests (Add Configuration Key) ---

    def test_post_fails_auth(self):
        """POST should fail if authentication fails."""
        self.mock_auth_service.verify.return_value = {"success": False, "status_code": 401}

        resp = self.client.post(self.config_url, json={})

        assert resp.status_code == 401
        self.mock_config_service.add_configuration_key.assert_not_called()

    def test_post_missing_key(self):
        """POST should return 400 if 'key' is missing."""
        resp = self.client.post(self.config_url, json={"parent_key": "llm", "value": 1})

        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'Missing "key" in payload'

    def test_post_success(self):
        """POST should return 200 and updated config on success."""
        payload = {"parent_key": "llm", "key": "new_param", "value": 123}
        updated_config = {"llm": {"new_param": 123}, "company": MagicMock()}

        self.mock_config_service.add_configuration_key.return_value = (updated_config, [])

        resp = self.client.post(self.config_url, json=payload)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'success'
        assert data['config']['llm']['new_param'] == 123
        assert 'company' not in data['config']

        self.mock_config_service.add_configuration_key.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, "llm", "new_param", 123
        )

    def test_post_validation_error(self):
        """POST should return 400 if validation fails."""
        payload = {"key": "bad_key", "value": "val"}
        errors = ["Invalid key"]
        self.mock_config_service.add_configuration_key.return_value = ({}, errors)

        resp = self.client.post(self.config_url, json=payload)

        assert resp.status_code == 400
        data = resp.get_json()
        assert data['status'] == 'invalid'
        assert data['errors'] == errors

    # --- ValidateConfigurationApiView Tests (GET) ---

    def test_validate_fails_auth(self):
        """GET validate should fail if authentication fails."""
        self.mock_auth_service.verify.return_value = {"success": False, "status_code": 401}

        resp = self.client.get(self.validate_url)

        assert resp.status_code == 401
        self.mock_config_service.validate_configuration.assert_not_called()

    def test_validate_valid(self):
        """GET validate should return 200 and status 'valid' if configuration is correct."""
        self.mock_config_service.validate_configuration.return_value = []

        resp = self.client.get(self.validate_url)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'valid'
        assert data['errors'] == []
        self.mock_config_service.validate_configuration.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)

    def test_validate_invalid(self):
        """GET validate should return 200 and status 'invalid' if validation fails."""
        errors = ["Missing ID", "Invalid Model"]
        self.mock_config_service.validate_configuration.return_value = errors

        resp = self.client.get(self.validate_url)

        assert resp.status_code == 200 # Request succeeded, result is that config is invalid
        data = resp.get_json()
        assert data['status'] == 'invalid'
        assert data['errors'] == errors

    def test_validate_internal_error(self):
        """GET validate should return 500 on unexpected exceptions."""
        self.mock_config_service.validate_configuration.side_effect = Exception("Parser error")

        resp = self.client.get(self.validate_url)

        assert resp.status_code == 500
        assert resp.get_json()['status'] == 'error'
