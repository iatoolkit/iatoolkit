from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.services.language_service import LanguageService
from iatoolkit.services.profile_service import ProfileService


@pytest.fixture
def stack():
    app = Flask(__name__)
    app.secret_key = "account-tests"
    repo = MagicMock()
    user = SimpleNamespace(id=1, first_name="Ana", last_name="Perez", auth_method="local",
                           preferred_language=None)
    repo.get_user_by_email.return_value = user
    repo.get_company_by_short_name.return_value = SimpleNamespace(id=10)
    repo.get_user_role_in_company.return_value = "user"
    config = MagicMock()
    config.get_configuration.return_value = "es"
    language = LanguageService(config, repo)
    context = MagicMock()
    service = ProfileService(
        i18n_service=MagicMock(), profile_repo=repo, session_context_service=context,
        config_service=config, lang_service=language, dispatcher=MagicMock(), mail_service=MagicMock(),
    )
    info = {"company_short_name": "acme", "user_identifier": "ana@example.com",
            "profile": {"user_is_local": True, "user_fullname": "Ana Perez", "user_role": "user"}}
    return app, repo, user, service, context, info, language


def test_local_name_changes_only_identity_fields_and_refreshes_profile(stack):
    app, repo, _, service, context, info, _ = stack
    with app.test_request_context():
        result = service.update_account("acme", info, action="update_profile",
                                        first_name=" Ana Maria ", last_name="Lopez")
    assert result == {"success": True}
    repo.update_user.assert_called_once_with("ana@example.com", first_name="Ana Maria", last_name="Lopez")
    assert context.save_profile_data.call_args.args == (
        "acme", "ana@example.com", {**info["profile"], "user_fullname": "Ana Maria Lopez"})


@pytest.mark.parametrize("method", ["google", "corporate"])
def test_managed_identity_cannot_be_edited(stack, method):
    app, repo, user, service, _, info, _ = stack
    user.auth_method = method
    info["profile"].update(user_is_local=False, extras={"auth_method": method})
    with app.test_request_context():
        result = service.update_account("acme", info, action="update_profile", first_name="X", last_name="Y")
    assert result["status_code"] == 403
    repo.update_user.assert_not_called()


@pytest.mark.parametrize("name", ["", "a" * 101, "A\nB"])
def test_invalid_name_is_not_saved(stack, name):
    app, repo, _, service, _, info, _ = stack
    with app.test_request_context():
        assert "error" in service.update_account("acme", info, action="update_profile",
                                                 first_name=name, last_name="Perez")
    repo.update_user.assert_not_called()


def test_local_name_requires_company_membership(stack):
    app, repo, _, service, _, info, _ = stack
    repo.get_user_role_in_company.return_value = None
    with app.test_request_context():
        assert service.update_account("acme", info, action="update_profile",
                                      first_name="X", last_name="Y")["status_code"] == 403
        assert service.update_account("other", info, action="update_profile",
                                      first_name="X", last_name="Y")["status_code"] == 403
    repo.update_user.assert_not_called()


def test_local_language_is_persisted_and_used_by_chat(stack):
    from flask import session
    app, repo, user, service, _, info, language = stack
    with app.test_request_context():
        session["active_company_short_name"] = "acme"
        session["company_sessions"] = {"acme": {"user_identifier": "ana@example.com"}}
        assert service.update_account("acme", info, action="update_preferences", language="en")["success"]
        repo.update_user.assert_called_once_with("ana@example.com", preferred_language="en")
        user.preferred_language = "en"
        assert language.get_current_language() == "en"


def test_corporate_language_is_scoped_to_user_and_company(stack):
    from flask import session
    app, repo, _, service, _, info, language = stack
    info["profile"]["user_is_local"] = False
    with app.test_request_context():
        session["active_company_short_name"] = "acme"
        session["company_sessions"] = {"acme": {"user_identifier": "ana@example.com"}}
        assert service.update_account("acme", info, action="update_preferences", language="en")["success"]
        repo.update_user.assert_not_called()
        assert language._resolve_locale_string() == "en"
        session["company_sessions"] = {"acme": {"user_identifier": "other@example.com"}}
        assert language._resolve_locale_string() == "es"
        session["active_company_short_name"] = "other"
        assert language._resolve_locale_string() == "es"


def test_invalid_language_and_persistence_error_are_reported(stack):
    app, repo, _, service, context, info, _ = stack
    with app.test_request_context():
        assert "error" in service.update_account("acme", info, action="update_preferences", language="xx")
        repo.update_user.assert_not_called()
        repo.update_user.side_effect = RuntimeError("database unavailable")
        result = service.update_account("acme", info, action="update_profile", first_name="A", last_name="B")
    assert result["status_code"] == 500
    context.save_profile_data.assert_not_called()
    repo.session.rollback.assert_called_once()
