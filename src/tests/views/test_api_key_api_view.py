import pytest
from unittest.mock import MagicMock
from flask import Flask

from iatoolkit.views.api_key_api_view import ApiKeyApiView
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.api_key_service import ApiKeyService


class TestApiKeyApiView:
    COMPANY = "acme"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        self.mock_auth = MagicMock(spec=AuthService)
        self.mock_api_key_service = MagicMock(spec=ApiKeyService)

        self.mock_auth.verify.return_value = {
            "success": True,
            "company_short_name": self.COMPANY,
            "user_role": "admin",
        }

        view = ApiKeyApiView.as_view(
            "api_key_api",
            auth_service=self.mock_auth,
            api_key_service=self.mock_api_key_service,
        )

        self.app.add_url_rule(
            "/<company_short_name>/api/api-keys",
            view_func=view,
            methods=["GET", "POST"],
        )
        self.app.add_url_rule(
            "/<company_short_name>/api/api-keys/<int:api_key_id>",
            view_func=view,
            methods=["GET", "PUT", "DELETE"],
        )

    def test_list_api_keys_success(self):
        expected = [{"id": 1, "key_name": "default", "key": "abc"}]
        self.mock_api_key_service.list_api_keys.return_value = {"data": expected}

        resp = self.client.get(f"/{self.COMPANY}/api/api-keys")

        assert resp.status_code == 200
        assert resp.json == expected
        self.mock_api_key_service.list_api_keys.assert_called_once_with(self.COMPANY)

    def test_get_api_key_success(self):
        expected = {"id": 3, "key_name": "integration", "key": "xyz"}
        self.mock_api_key_service.get_api_key.return_value = {"data": expected}

        resp = self.client.get(f"/{self.COMPANY}/api/api-keys/3")

        assert resp.status_code == 200
        assert resp.json == expected
        self.mock_api_key_service.get_api_key.assert_called_once_with(self.COMPANY, 3)

    def test_create_api_key_success(self):
        payload = {"key_name": "prod_key"}
        expected = {"id": 4, "key_name": "prod_key", "key": "new-key"}
        self.mock_api_key_service.create_api_key_entry.return_value = {"data": expected}

        resp = self.client.post(f"/{self.COMPANY}/api/api-keys", json=payload)

        assert resp.status_code == 201
        assert resp.json == expected
        self.mock_api_key_service.create_api_key_entry.assert_called_once_with(self.COMPANY, "prod_key")

    def test_update_api_key_success(self):
        payload = {"key_name": "renamed", "is_active": False}
        expected = {"id": 5, "key_name": "renamed", "is_active": False}
        self.mock_api_key_service.update_api_key_entry.return_value = {"data": expected}

        resp = self.client.put(f"/{self.COMPANY}/api/api-keys/5", json=payload)

        assert resp.status_code == 200
        assert resp.json == expected
        self.mock_api_key_service.update_api_key_entry.assert_called_once_with(
            company_short_name=self.COMPANY,
            api_key_id=5,
            key_name="renamed",
            is_active=False,
        )

    def test_delete_api_key_success(self):
        self.mock_api_key_service.delete_api_key_entry.return_value = {"status": "success"}

        resp = self.client.delete(f"/{self.COMPANY}/api/api-keys/7")

        assert resp.status_code == 200
        assert resp.json["status"] == "success"
        self.mock_api_key_service.delete_api_key_entry.assert_called_once_with(self.COMPANY, 7)

    def test_auth_failure(self):
        self.mock_auth.verify.return_value = {"success": False, "status_code": 401}

        resp = self.client.get(f"/{self.COMPANY}/api/api-keys")

        assert resp.status_code == 401
        self.mock_api_key_service.list_api_keys.assert_not_called()

    def test_forbidden_when_role_is_not_admin(self):
        self.mock_auth.verify.return_value = {
            "success": True,
            "company_short_name": self.COMPANY,
            "user_role": "user",
        }

        resp = self.client.get(f"/{self.COMPANY}/api/api-keys")

        assert resp.status_code == 403
        self.mock_api_key_service.list_api_keys.assert_not_called()

    def test_forbidden_when_company_mismatch(self):
        self.mock_auth.verify.return_value = {
            "success": True,
            "company_short_name": "other",
            "user_role": "admin",
        }

        resp = self.client.get(f"/{self.COMPANY}/api/api-keys")

        assert resp.status_code == 403
        self.mock_api_key_service.list_api_keys.assert_not_called()

    def test_create_handles_service_errors(self):
        self.mock_api_key_service.create_api_key_entry.return_value = {
            "error": "duplicate",
            "status_code": 409,
        }

        resp = self.client.post(f"/{self.COMPANY}/api/api-keys", json={"key_name": "dup"})

        assert resp.status_code == 409
        assert resp.json["error"] == "duplicate"

    def test_delete_handles_service_errors(self):
        self.mock_api_key_service.delete_api_key_entry.return_value = {
            "error": "not found",
            "status_code": 404,
        }

        resp = self.client.delete(f"/{self.COMPANY}/api/api-keys/999")

        assert resp.status_code == 404
        assert resp.json["error"] == "not found"
