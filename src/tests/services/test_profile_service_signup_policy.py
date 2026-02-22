# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from unittest.mock import MagicMock

from iatoolkit.repositories.models import Company
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.language_service import LanguageService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.common.interfaces.signup_policy_resolver import SignupPolicyDecision, SignupPolicyResolver
from iatoolkit.services.user_session_context_service import UserSessionContextService


def test_signup_returns_error_when_policy_denies():
    repo = MagicMock(spec=ProfileRepo)
    session_context = MagicMock(spec=UserSessionContextService)
    mail_service = MagicMock(spec=MailService)
    dispatcher = MagicMock(spec=Dispatcher)
    i18n = MagicMock(spec=I18nService)
    config_service = MagicMock(spec=ConfigurationService)
    lang_service = MagicMock(spec=LanguageService)
    signup_policy_resolver = MagicMock(spec=SignupPolicyResolver)

    i18n.t.side_effect = lambda key, **kwargs: f"translated:{key}"
    config_service.get_configuration.return_value = {}
    repo.get_company_by_short_name.return_value = Company(id=1, name="Acme", short_name="acme")
    signup_policy_resolver.evaluate_signup.return_value = SignupPolicyDecision(
        allowed=False,
        reason_key="errors.signup.signup_not_allowed",
    )

    service = ProfileService(
        i18n_service=i18n,
        profile_repo=repo,
        session_context_service=session_context,
        config_service=config_service,
        lang_service=lang_service,
        dispatcher=dispatcher,
        mail_service=mail_service,
        signup_policy_resolver=signup_policy_resolver,
    )

    response = service.signup(
        company_short_name="acme",
        email="user@external.com",
        first_name="Test",
        last_name="User",
        password="Password$1",
        confirm_password="Password$1",
        verification_url="https://example.com/verify",
    )

    assert response["error"] == "translated:errors.signup.signup_not_allowed"
    repo.create_user.assert_not_called()
    signup_policy_resolver.evaluate_signup.assert_called_once()
