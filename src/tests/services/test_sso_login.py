# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Sign-in with a company's identity provider (BL-031): AuthService.login_sso_user
and ProfileService.login_with_sso."""

from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.common.interfaces.identity_provider_resolver import CompanyIdentityProvider
from iatoolkit.common.interfaces.signup_policy_resolver import SignupPolicyDecision, SignupPolicyResolver
from iatoolkit.infra.oidc_client import OidcError, OidcIdentity, OidcProviderConfig
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, User
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService

ISSUER = "https://login.example-idp.com/tenant-1/v2.0"
PROVIDER = CompanyIdentityProvider(
    company_short_name="acme", provider_type="entra", display_name="Microsoft",
    oidc=OidcProviderConfig(issuer=ISSUER, client_id="client-1", client_secret="secret-1"),
    trusted_email_domains=("acme.com",),
)


def _identity(email="ana@acme.com", verified=None, subject="subject-1"):
    return OidcIdentity(issuer=ISSUER, subject=subject, email=email, email_verified=verified,
                        given_name="Ana", family_name="Pérez", full_name="Ana Pérez")


def test_the_client_secret_never_shows_in_a_repr():
    assert "secret-1" not in repr(PROVIDER)


# ------------------------------------------------------------------ ProfileService

class TestLoginWithSso:

    def setup_method(self):
        self.db = DatabaseManager('sqlite:///:memory:')
        self.db.create_all()
        self.session = self.db.get_session()
        self.repo = ProfileRepo(self.db)
        self.company = Company(name="Acme", short_name="acme")
        self.session.add(self.company)
        self.session.commit()

        self.policy = MagicMock(spec=SignupPolicyResolver)
        self.policy.evaluate_signup.return_value = SignupPolicyDecision(allowed=True, metadata={"policy_mode": "domain"})
        self.policy.claim_signup.return_value = True
        i18n = MagicMock(spec=I18nService)
        i18n.t.side_effect = lambda key, **kw: f"translated:{key}"

        self.service = ProfileService(
            i18n_service=i18n, profile_repo=self.repo, session_context_service=MagicMock(),
            config_service=MagicMock(), lang_service=MagicMock(), dispatcher=MagicMock(),
            mail_service=MagicMock(), signup_policy_resolver=self.policy)
        self.sessions = []
        self.service._build_session_user_profile = (
            lambda user, company, role, login_method=None: self.sessions.append((user.email, company.short_name, login_method))
            or {"success": True, "user_identifier": user.email})

    def _user(self, email):
        return self.session.query(User).filter_by(email=email).first()

    def test_a_new_person_gets_an_sso_account_and_joins_the_company(self):
        result = self.service.login_with_sso(PROVIDER, _identity())

        assert result == {"success": True, "user_identifier": "ana@acme.com"}
        user = self._user("ana@acme.com")
        assert (user.auth_method, user.password, user.verified) == ("sso", None, True)
        assert (user.first_name, user.last_name) == ("ana", "pérez")   # normalized as with Google
        assert [(i.issuer, i.subject) for i in user.identities] == [(ISSUER, "subject-1")]
        assert self.company in user.companies
        self.policy.claim_signup.assert_called_once_with("acme", "ana@acme.com", verified_email=True)
        assert self.sessions == [("ana@acme.com", "acme", "sso")]

    def test_the_next_sign_in_finds_the_account_by_issuer_and_subject(self):
        self.service.login_with_sso(PROVIDER, _identity())
        # The provider now reports another address for the same person.
        result = self.service.login_with_sso(PROVIDER, _identity(email="ana.perez@acme.com"))

        assert result["user_identifier"] == "ana@acme.com"
        assert self.session.query(User).count() == 1
        assert self.policy.evaluate_signup.call_count == 1      # already a member

    def test_an_existing_local_account_is_linked_and_keeps_its_password(self):
        local = User(email="ana@acme.com", first_name="Ana", last_name="P", password="hash", auth_method="local")
        self.session.add(local)
        self.session.commit()

        result = self.service.login_with_sso(PROVIDER, _identity())

        assert result["success"] is True
        user = self._user("ana@acme.com")
        assert (user.auth_method, user.password) == ("local", "hash")
        assert user.find_identity(ISSUER).subject == "subject-1"

    def test_an_account_linked_to_another_subject_at_the_same_provider_is_refused(self):
        self.service.login_with_sso(PROVIDER, _identity(subject="subject-1"))

        result = self.service.login_with_sso(PROVIDER, _identity(subject="subject-2"))

        assert result["reason_code"] == "SSO_ACCOUNT_CONFLICT"
        assert [i.subject for i in self._user("ana@acme.com").identities] == ["subject-1"]

    def test_an_unverified_address_outside_the_company_domains_is_refused(self):
        result = self.service.login_with_sso(PROVIDER, _identity(email="ana@gmail.com", verified=None))

        assert result["reason_code"] == "SSO_EMAIL_NOT_TRUSTED"
        assert self.session.query(User).count() == 0

    def test_the_provider_is_believed_when_it_says(self):
        assert self.service.login_with_sso(PROVIDER, _identity(email="ana@partner.com", verified=True))["success"]
        refused = self.service.login_with_sso(PROVIDER, _identity(email="bob@acme.com", verified=False, subject="s-2"))
        assert refused["reason_code"] == "SSO_EMAIL_NOT_TRUSTED"

    def test_no_email_is_refused(self):
        assert self.service.login_with_sso(PROVIDER, _identity(email=None))["reason_code"] == "SSO_EMAIL_MISSING"

    def test_the_signup_policy_decides_who_joins(self):
        self.policy.evaluate_signup.return_value = SignupPolicyDecision(allowed=False, reason_key="errors.signup.domain")

        result = self.service.login_with_sso(PROVIDER, _identity())

        assert result == {"success": False, "reason_code": "SIGNUP_NOT_ALLOWED",
                          "message": "translated:errors.signup.domain"}
        assert self.session.query(User).count() == 0
        assert self.sessions == []

    def test_a_failed_invitation_claim_is_refused(self):
        self.policy.claim_signup.return_value = False

        result = self.service.login_with_sso(PROVIDER, _identity())

        assert result["reason_code"] == "SIGNUP_NOT_ALLOWED"
        assert self.session.query(User).count() == 0


# --------------------------------------------------------------------- AuthService

class TestLoginSsoUser:

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setenv("IAT_RATE_LIMITS", "off")
        self.profile_service = MagicMock(spec=ProfileService)
        self.oidc_client = MagicMock()
        i18n = MagicMock(spec=I18nService)
        i18n.t.side_effect = lambda key, **kw: f"translated:{key}"
        self.service = AuthService(
            profile_service=self.profile_service, api_key_service=MagicMock(), jwt_service=MagicMock(),
            db_manager=MagicMock(), google_auth_client=MagicMock(), i18n_service=i18n,
            oidc_client=self.oidc_client)
        self.log_access = MagicMock()
        monkeypatch.setattr(self.service, "log_access", self.log_access)
        self.app = Flask(__name__)

    def _login(self):
        with self.app.test_request_context():
            return self.service.login_sso_user(PROVIDER, code="code-1", redirect_uri="https://app.test/cb",
                                               code_verifier="verifier-1", nonce="nonce-1")

    def test_success_is_logged(self):
        self.oidc_client.exchange_code.return_value = _identity()
        self.profile_service.login_with_sso.return_value = {"success": True, "user_identifier": "ana@acme.com"}

        assert self._login()["success"] is True
        self.oidc_client.exchange_code.assert_called_once_with(
            PROVIDER.oidc, code="code-1", redirect_uri="https://app.test/cb",
            code_verifier="verifier-1", nonce="nonce-1")
        self.log_access.assert_called_once_with(company_short_name="acme", auth_type="sso",
                                                outcome="success", user_identifier="ana@acme.com")

    def test_a_token_the_provider_does_not_prove_is_refused(self):
        self.oidc_client.exchange_code.side_effect = OidcError("OIDC_NONCE_MISMATCH")

        result = self._login()

        assert result == {"success": False, "reason_code": "OIDC_NONCE_MISMATCH",
                          "message": "translated:errors.auth.sso_login_failed"}
        self.profile_service.login_with_sso.assert_not_called()
        assert self.log_access.call_args.kwargs["reason_code"] == "OIDC_NONCE_MISMATCH"

    def test_a_refusal_by_the_profile_service_is_logged_with_the_email(self):
        self.oidc_client.exchange_code.return_value = _identity()
        self.profile_service.login_with_sso.return_value = {"success": False, "reason_code": "SIGNUP_NOT_ALLOWED"}

        self._login()

        assert self.log_access.call_args.kwargs == {
            "company_short_name": "acme", "auth_type": "sso", "outcome": "failure",
            "reason_code": "SIGNUP_NOT_ALLOWED", "user_identifier": "ana@acme.com"}

    def test_too_many_attempts_from_one_ip_are_refused(self, monkeypatch):
        from iatoolkit.common import rate_limiter
        monkeypatch.setattr(rate_limiter, "over_limit", lambda bucket, identity, limit: bucket == "login_ip")

        result = self._login()

        assert result["reason_code"] == "RATE_LIMITED"
        self.oidc_client.exchange_code.assert_not_called()


# ------------------------------------------------------ login methods per company (PR-4)

class TestLoginMethods:

    def setup_method(self):
        from flask_bcrypt import generate_password_hash
        from iatoolkit.common.interfaces.identity_provider_resolver import CompanyLoginMethods, IdentityProviderResolver
        self.CompanyLoginMethods = CompanyLoginMethods
        self.db = DatabaseManager('sqlite:///:memory:')
        self.db.create_all()
        self.session = self.db.get_session()
        self.company = Company(name="Acme", short_name="acme")
        self.user = User(email="ana@acme.com", first_name="ana", last_name="p", verified=True,
                         password=generate_password_hash("secret").decode("utf-8"))
        self.user.companies.append(self.company)
        self.session.add_all([self.company, self.user])
        self.session.commit()

        self.resolver = MagicMock(spec=IdentityProviderResolver)
        self.resolver.get_login_methods.return_value = CompanyLoginMethods(sso=PROVIDER, password=False, google=False)
        i18n = MagicMock(spec=I18nService)
        i18n.t.side_effect = lambda key, **kw: f"translated:{key}"
        self.policy = MagicMock(spec=SignupPolicyResolver)
        self.service = ProfileService(
            i18n_service=i18n, profile_repo=ProfileRepo(self.db), session_context_service=MagicMock(),
            config_service=MagicMock(), lang_service=MagicMock(), dispatcher=MagicMock(),
            mail_service=MagicMock(), signup_policy_resolver=self.policy,
            identity_provider_resolver=self.resolver)
        self.service._build_session_user_profile = (
            lambda user, company, role, login_method=None: {"success": True, "user_identifier": user.email})

    def test_password_off_refuses_a_member(self, monkeypatch):
        monkeypatch.setattr("iatoolkit.services.profile_service.access.is_owner", lambda c, u: False)

        result = self.service.login("acme", "ana@acme.com", "secret")

        assert result["reason_code"] == "PASSWORD_LOGIN_DISABLED"

    def test_password_off_still_lets_an_owner_in(self, monkeypatch):
        monkeypatch.setattr("iatoolkit.services.profile_service.access.is_owner",
                            lambda c, u: (c, u) == ("acme", "ana@acme.com"))

        assert self.service.login("acme", "ana@acme.com", "secret")["success"] is True

    def test_a_wrong_password_is_still_a_wrong_password(self, monkeypatch):
        monkeypatch.setattr("iatoolkit.services.profile_service.access.is_owner", lambda c, u: True)

        result = self.service.login("acme", "ana@acme.com", "wrong")

        assert result["success"] is False and "reason_code" not in result

    def test_password_off_refuses_signup_with_password(self):
        result = self.service.signup("acme", "bob@acme.com", "Bob", "B", "Secret123!", "Secret123!",
                                     "https://app.test/verify")

        assert result == {"error": "translated:errors.signup.password_signup_disabled"}
        self.policy.evaluate_signup.assert_not_called()

    def test_google_off_refuses_google_sign_in(self):
        from iatoolkit.infra.google_auth_client import GoogleIdentity

        result = self.service.login_with_google("acme", GoogleIdentity(subject="g", email="ana@acme.com",
                                                                       email_verified=True))

        assert result["reason_code"] == "GOOGLE_LOGIN_DISABLED"

    def test_every_method_is_allowed_when_the_lookup_fails(self):
        self.resolver.get_login_methods.side_effect = RuntimeError("db down")

        methods = self.service.login_methods("acme")

        assert (methods.sso, methods.google, methods.password) == (None, True, True)

    def test_without_a_resolver_every_method_is_allowed(self):
        self.service.identity_provider_resolver = None
        assert self.service.login_methods("acme") == self.CompanyLoginMethods()


def test_the_default_resolver_offers_the_provider_and_every_method():
    from iatoolkit.common.interfaces.identity_provider_resolver import IdentityProviderResolver

    class OneProvider(IdentityProviderResolver):
        def get_provider(self, company_short_name):
            return PROVIDER

    methods = OneProvider().get_login_methods("acme")
    assert (methods.sso, methods.google, methods.password) == (PROVIDER, True, True)
