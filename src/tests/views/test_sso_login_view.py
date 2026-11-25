# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask

from iatoolkit.common.interfaces.identity_provider_resolver import CompanyIdentityProvider
from iatoolkit.infra.oidc_client import OidcAuthorizationRequest, OidcError, OidcProviderConfig
from iatoolkit.views import sso_login_view
from iatoolkit.views.sso_login_view import PENDING_KEY, SsoLoginCallbackView, SsoLoginStartView

ISSUER = "https://login.example-idp.com/tenant-1/v2.0"


def _provider(issuer=ISSUER):
    return CompanyIdentityProvider(
        company_short_name="acme", provider_type="entra", display_name="Microsoft",
        oidc=OidcProviderConfig(issuer=issuer, client_id="client-1", client_secret="secret-1"),
        trusted_email_domains=("acme.com",),
    )


class TestSsoLoginViews:

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.client = self.app.test_client()

        self.profile_service = MagicMock()
        self.auth_service = MagicMock()
        self.resolver = MagicMock()
        self.oidc_client = MagicMock()
        self.i18n = MagicMock()
        self.i18n.t.side_effect = lambda key, **kw: f"translated:{key}"
        self.resolver.get_provider.return_value = _provider()
        self.counter = 0

        def build(config, redirect_uri, login_hint=None):
            self.counter += 1
            self.last_redirect_uri = redirect_uri
            self.last_login_hint = login_hint
            n = self.counter
            return OidcAuthorizationRequest(url=f"https://idp.example/authorize?state=state-{n}",
                                            state=f"state-{n}", nonce=f"nonce-{n}", code_verifier=f"verifier-{n}")

        self.oidc_client.build_authorization_request.side_effect = build

        start_init = SsoLoginStartView.__init__
        monkeypatch.setattr(SsoLoginStartView, "__init__", lambda inst, **kw: start_init(
            inst, profile_service=self.profile_service, identity_provider_resolver=self.resolver,
            oidc_client=self.oidc_client, i18n_service=self.i18n))
        callback_init = SsoLoginCallbackView.__init__
        monkeypatch.setattr(SsoLoginCallbackView, "__init__", lambda inst, **kw: callback_init(
            inst, identity_provider_resolver=self.resolver, profile_service=self.profile_service,
            auth_service=self.auth_service, jwt_service=MagicMock(), branding_service=MagicMock(),
            prompt_service=MagicMock(), config_service=MagicMock(), query_service=MagicMock(),
            i18n_service=self.i18n, utility=MagicMock()))
        self.handle_login_path = MagicMock(return_value=("chat", 200))
        monkeypatch.setattr(SsoLoginCallbackView, "_handle_login_path", self.handle_login_path)

        self.app.add_url_rule("/<company_short_name>/login/sso", view_func=SsoLoginStartView.as_view("login_sso_start"))
        self.app.add_url_rule("/auth/sso/callback", view_func=SsoLoginCallbackView.as_view("login_sso_callback"))
        self.app.add_url_rule("/<company_short_name>/home", endpoint="home", view_func=lambda company_short_name: "home")
        self.app.add_url_rule("/<company_short_name>/finalize", endpoint="finalize_no_token",
                              view_func=lambda company_short_name: "finalize")
        self.app.add_url_rule("/", endpoint="root_redirect", view_func=lambda: "root")

    def _pending(self):
        with self.client.session_transaction() as sess:
            return dict(sess.get(PENDING_KEY) or {})

    # ------------------------------------------------------------------- start

    def test_start_redirects_to_the_provider_and_keeps_the_pending_sign_in(self):
        response = self.client.get("/acme/login/sso?lang=es&next=/acme/chat&login_hint=ana@acme.com")

        assert response.status_code == 302
        assert response.location.startswith("https://idp.example/authorize")
        assert self.last_redirect_uri == "http://localhost/auth/sso/callback"
        assert self.last_login_hint == "ana@acme.com"
        entry = self._pending()["state-1"]
        assert entry["company_short_name"] == "acme"
        assert entry["issuer"] == ISSUER
        assert (entry["nonce"], entry["code_verifier"]) == ("nonce-1", "verifier-1")
        assert (entry["lang"], entry["next_target"]) == ("es", "/acme/chat")

    def test_start_drops_an_unsafe_next_target(self):
        self.client.get("/acme/login/sso?next=https://evil.example.com/")
        assert self._pending()["state-1"]["next_target"] is None

    def test_start_without_a_provider_returns_home(self):
        self.resolver.get_provider.return_value = None

        response = self.client.get("/acme/login/sso")

        assert response.status_code == 302
        assert urlparse(response.location).path == "/acme/home"
        self.oidc_client.build_authorization_request.assert_not_called()

    def test_start_for_an_unknown_company_is_404(self):
        self.profile_service.get_company_by_short_name.return_value = None
        self.app.jinja_loader = None
        from unittest.mock import patch
        with patch.object(sso_login_view, "render_template", return_value="not found"):
            response = self.client.get("/nope/login/sso")
        assert response.status_code == 404

    def test_start_when_the_provider_is_unreachable_returns_home(self):
        self.oidc_client.build_authorization_request.side_effect = OidcError("OIDC_DISCOVERY_FAILED",
                                                                             "errors.auth.sso_not_available")
        response = self.client.get("/acme/login/sso")

        assert urlparse(response.location).path == "/acme/home"
        assert self._pending() == {}

    def test_only_the_latest_pending_sign_ins_are_kept(self):
        for _ in range(sso_login_view.MAX_PENDING + 3):
            self.client.get("/acme/login/sso")

        pending = self._pending()
        assert len(pending) == sso_login_view.MAX_PENDING
        assert f"state-{sso_login_view.MAX_PENDING + 3}" in pending
        assert "state-1" not in pending

    # ---------------------------------------------------------------- callback

    def test_callback_finishes_the_sign_in_and_consumes_the_state(self):
        self.client.get("/acme/login/sso")
        self.auth_service.login_sso_user.return_value = {"success": True, "user_identifier": "ana@acme.com"}

        response = self.client.get("/auth/sso/callback?state=state-1&code=code-1")

        assert response.status_code == 200
        provider = self.auth_service.login_sso_user.call_args.args[0]
        kwargs = self.auth_service.login_sso_user.call_args.kwargs
        assert provider.company_short_name == "acme"
        assert kwargs == {"code": "code-1", "redirect_uri": "http://localhost/auth/sso/callback",
                          "code_verifier": "verifier-1", "nonce": "nonce-1"}
        assert self.handle_login_path.call_args.args[0:2] == ("acme", "ana@acme.com")
        assert self._pending() == {}

        # a replay of the same state finds nothing
        replay = self.client.get("/auth/sso/callback?state=state-1&code=code-1")
        assert urlparse(replay.location).path == "/"
        assert self.auth_service.login_sso_user.call_count == 1

    def test_callback_goes_to_the_next_target(self):
        self.client.get("/acme/login/sso?next=/acme/chat")
        self.auth_service.login_sso_user.return_value = {"success": True, "user_identifier": "ana@acme.com"}

        response = self.client.get("/auth/sso/callback?state=state-1&code=code-1")

        assert response.location == "http://localhost/acme/chat"
        self.handle_login_path.assert_not_called()

    def test_callback_with_an_unknown_state_does_nothing(self):
        response = self.client.get("/auth/sso/callback?state=forged&code=code-1")

        assert urlparse(response.location).path == "/"
        self.auth_service.login_sso_user.assert_not_called()

    def test_an_expired_pending_sign_in_is_refused(self, monkeypatch):
        self.client.get("/acme/login/sso")
        real_time = sso_login_view.time.time
        monkeypatch.setattr(sso_login_view.time, "time", lambda: real_time() + sso_login_view.PENDING_TTL_SECONDS + 1)

        response = self.client.get("/auth/sso/callback?state=state-1&code=code-1")

        assert urlparse(response.location).path == "/"
        self.auth_service.login_sso_user.assert_not_called()

    def test_a_provider_error_is_logged_and_the_state_consumed(self):
        self.client.get("/acme/login/sso")

        response = self.client.get("/auth/sso/callback?state=state-1&error=access_denied")

        assert urlparse(response.location).path == "/acme/home"
        assert self.auth_service.log_access.call_args.kwargs["reason_code"] == "SSO_PROVIDER_ACCESS_DENIED"
        self.auth_service.login_sso_user.assert_not_called()
        assert self._pending() == {}

    def test_a_provider_changed_meanwhile_cancels_the_sign_in(self):
        self.client.get("/acme/login/sso")
        self.resolver.get_provider.return_value = _provider(issuer="https://other-idp.example.com")

        response = self.client.get("/auth/sso/callback?state=state-1&code=code-1")

        assert urlparse(response.location).path == "/acme/home"
        self.auth_service.login_sso_user.assert_not_called()

    def test_a_refused_sign_in_returns_home(self):
        self.client.get("/acme/login/sso")
        self.auth_service.login_sso_user.return_value = {"success": False, "message": "no"}

        response = self.client.get("/auth/sso/callback?state=state-1&code=code-1")

        assert urlparse(response.location).path == "/acme/home"
        assert parse_qs(urlparse(response.location).query)["lang"] == ["en"]
        self.handle_login_path.assert_not_called()
