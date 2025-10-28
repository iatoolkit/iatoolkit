# tests/views/test_external_login_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.external_login_view import ExternalLoginView, RedeemTokenApiView
from iatoolkit.views.base_login_view import BaseLoginView

# --- Tests for ExternalLoginView ---
class TestExternalLoginView:
    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        self.app = Flask(__name__)
        self.client = self.app.test_client()

        # Mocks for all services that could be used by the view or its parent
        self.auth_service = MagicMock()
        self.profile_service = MagicMock()
        self.jwt_service = MagicMock()
        self.branding_service = MagicMock()
        self.onboarding_service = MagicMock()
        self.query_service = MagicMock()
        self.prompt_service = MagicMock()

        # A single, comprehensive patch for the parent constructor
        def patched_base_init(instance, **kwargs):
            instance.auth_service = self.auth_service
            instance.profile_service = self.profile_service
            instance.jwt_service = self.jwt_service
            instance.branding_service = self.branding_service
            instance.onboarding_service = self.onboarding_service
            instance.query_service = self.query_service
            instance.prompt_service = self.prompt_service
        monkeypatch.setattr(BaseLoginView, "__init__", patched_base_init)

        # Register view under test
        self.app.add_url_rule(
            "/<company_short_name>/external_login",
            view_func=ExternalLoginView.as_view("external_login"),
            methods=["POST"],
        )
        # This endpoint is needed for url_for() to work inside the view
        @self.app.route("/<company_short_name>/finalize/<token>", endpoint="finalize_with_token")
        def fake_finalize(company_short_name, token):
            return "finalize page", 200

        # Common test data
        self.company_short_name = "acme"
        self.user_identifier = "ext-123"

        # Default success cases for mocks
        self.profile_service.get_company_by_short_name.return_value = MagicMock(short_name=self.company_short_name)
        self.auth_service.verify.return_value = {"success": True}
        self.jwt_service.generate_chat_jwt.return_value = "fake-redeem-token"

    def test_missing_body_or_key_returns_400(self):
        """A request with an empty or malformed JSON body should return 400."""
        # Flask's test client sends 415 without a proper json content-type
        # Sending json={} ensures the header is set and our view logic is tested
        resp_empty = self.client.post(f"/{self.company_short_name}/external_login", json={})
        assert resp_empty.status_code == 400

        resp_missing_key = self.client.post(f"/{self.company_short_name}/external_login", json={"other": "data"})
        assert resp_missing_key.status_code == 400

    def test_company_not_found_returns_404(self):
        self.profile_service.get_company_by_short_name.return_value = None
        resp = self.client.post(f"/{self.company_short_name}/external_login", json={"user_identifier": "any"})
        assert resp.status_code == 404

    def test_empty_external_user_id_returns_404(self):
        resp = self.client.post(f"/{self.company_short_name}/external_login", json={"user_identifier": ""})
        assert resp.status_code == 404

    def test_auth_failure_returns_401(self):
        self.auth_service.verify.return_value = {"success": False, "error": "denied"}
        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            json={"user_identifier": self.user_identifier},
        )
        assert resp.status_code == 401
        assert resp.get_json() == {"success": False, "error": "denied"}

    def test_success_delegates_to_base_handler(self):
        """On success, the view should call the base handler with correct args."""
        with patch.object(BaseLoginView, "_handle_login_path") as mock_handle_path:
            mock_handle_path.return_value = "OK", 200

            resp = self.client.post(
                f"/{self.company_short_name}/external_login",
                json={"user_identifier": self.user_identifier},
            )

            assert resp.status_code == 200
            assert resp.data == b"OK"
            self.profile_service.create_external_user_profile_context.assert_called_once()
            self.jwt_service.generate_chat_jwt.assert_called_once()
            mock_handle_path.assert_called_once()


    def test_handle_path_exception_returns_500_json(self):
        """If _handle_login_path fails, it should return a 500 JSON error."""
        with patch.object(BaseLoginView, "_handle_login_path", side_effect=Exception("boom")):
            resp = self.client.post(
                f"/{self.company_short_name}/external_login",
                json={"user_identifier": self.user_identifier},
            )
        assert resp.status_code == 500
        assert resp.is_json
        assert "Internal server error" in resp.get_json().get("error", "")


# --- Tests for RedeemTokenApiView (separated for clarity) ---
class TestRedeemTokenApiView:
    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.auth_service = MagicMock()

        # Use the same patching strategy for consistency
        def patched_base_init(instance, **kwargs):
            instance.auth_service = self.auth_service
            instance.profile_service = MagicMock()
            instance.jwt_service = MagicMock()
        monkeypatch.setattr(BaseLoginView, "__init__", patched_base_init)

        self.app.add_url_rule(
            "/<company_short_name>/api/redeem_token",
            view_func=RedeemTokenApiView.as_view("redeem_token"),
            methods=["POST"],
        )
        self.company_short_name = "acme"

    def test_redeem_missing_token_returns_400(self):
        resp = self.client.post(f"/{self.company_short_name}/api/redeem_token", json={})
        assert resp.status_code == 400
        assert "Falta token" in resp.get_json().get("error", "")

    def test_redeem_failure_returns_401(self):
        self.auth_service.redeem_token_for_session.return_value = {'success': False, 'error': 'Token es inválido'}
        resp = self.client.post(
            f"/{self.company_short_name}/api/redeem_token", json={"token": "bad"}
        )
        assert resp.status_code == 401
        assert "Token es inválido" in resp.get_json().get("error", "")
        self.auth_service.redeem_token_for_session.assert_called_once_with(
            company_short_name=self.company_short_name, token="bad"
        )

    def test_redeem_success_returns_200(self):
        self.auth_service.redeem_token_for_session.return_value = {'success': True}
        resp = self.client.post(
            f"/{self.company_short_name}/api/redeem_token", json={"token": "good"}
        )
        assert resp.status_code == 200
        assert resp.get_json().get("status") == "ok"
        self.auth_service.redeem_token_for_session.assert_called_once_with(
            company_short_name=self.company_short_name, token="good"
        )