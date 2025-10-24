# tests/views/test_external_login_view.py
import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.external_login_view import ExternalLoginView
from iatoolkit.views.base_login_view import BaseLoginView

class TestExternalLoginView:
    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.client = self.app.test_client()

        # Mocks
        self.auth_service = MagicMock()
        self.profile_service = MagicMock()
        self.query_service = MagicMock()
        self.branding_service = MagicMock()
        self.onboarding_service = MagicMock()
        self.prompt_service = MagicMock()  # por si tu BaseLoginView actual la usa

        # Inyección directa sin llamar a super().__init__
        def patched_init(instance):
            instance.iauthentication = self.auth_service
            instance.profile_service = self.profile_service
            instance.branding_service = self.branding_service
            instance.onboarding_service = self.onboarding_service
            instance.query_service = self.query_service
            instance.prompt_service = self.prompt_service  # inofensivo si no se usa
        monkeypatch.setattr(ExternalLoginView, "__init__", patched_init)

        self.app.add_url_rule(
            "/<company_short_name>/external_login",
            view_func=ExternalLoginView.as_view("external_login"),
            methods=["POST"],
        )

        self.company_short_name = "acme"
        self.external_user_id = "ext-123"

        # Defaults
        self.profile_service.get_company_by_short_name.return_value = MagicMock()
        self.auth_service.verify.return_value = {"success": True}

    def test_missing_body_returns_400(self):
        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 400

        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            json={"foo": "bar"},
        )
        assert resp.status_code == 400

    def test_company_not_found_returns_404(self):
        self.profile_service.get_company_by_short_name.return_value = None
        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            json={"external_user_id": self.external_user_id},
        )
        assert resp.status_code == 404

    def test_empty_external_user_id_returns_404(self):
        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            json={"external_user_id": ""},
        )
        assert resp.status_code == 404

    def test_auth_failure_returns_401(self):
        self.auth_service.verify.return_value = {"success": False, "error": "denied"}
        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            json={"external_user_id": self.external_user_id},
        )
        assert resp.status_code == 401
        self.auth_service.verify.assert_called_once()

    def test_success_delegates_to_base_handler(self, monkeypatch):
        def fake_handle(_self, csn, uid, company):
            return "OK", 200
        monkeypatch.setattr(BaseLoginView, "_handle_login_path", fake_handle, raising=True)

        resp = self.client.post(
            f"/{self.company_short_name}/external_login",
            json={"external_user_id": self.external_user_id},
        )

        assert resp.status_code == 200
        assert resp.data == b"OK"
        self.profile_service.create_external_user_session.assert_called_once()

    def test_handle_path_exception_returns_500_json(self):
        with patch.object(BaseLoginView, "_handle_login_path", side_effect=Exception("boom")):
            resp = self.client.post(
                f"/{self.company_short_name}/external_login",
                json={"external_user_id": self.external_user_id},
            )
        assert resp.status_code == 500
        assert resp.is_json
        assert "boom" in resp.get_json().get("error", "")