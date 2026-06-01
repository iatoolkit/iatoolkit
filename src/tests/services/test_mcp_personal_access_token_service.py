from datetime import datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from iatoolkit.common.util import Utility
from iatoolkit.repositories.models import Company, McpToken
from iatoolkit.repositories.mcp_token_repo import McpTokenRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.mcp_token_service import McpTokenService


class TestMcpTokenService:
    def setup_method(self):
        self.mock_i18n = MagicMock(spec=I18nService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_repo = MagicMock(spec=McpTokenRepo)
        self.mock_utility = MagicMock(spec=Utility)
        self.mock_i18n.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.mock_utility.encrypt_key.side_effect = lambda value: f"encrypted:{value}"
        self.mock_utility.decrypt_key.side_effect = lambda value: value.replace("encrypted:", "", 1)
        self.company = Company(id=7, short_name="acme", name="ACME")
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.service = McpTokenService(
            i18n_service=self.mock_i18n,
            profile_repo=self.mock_profile_repo,
            token_repo=self.mock_repo,
            utility=self.mock_utility,
        )

    def test_create_token_requires_name(self):
        result = self.service.create_user_token("acme", "user@acme.com", name="")

        assert result["status_code"] == 400
        assert result["error"] == "translated:errors.auth.mcp_pat_name_required"

    def test_create_user_token_returns_raw_token_once(self):
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = lambda token: token

        result = self.service.create_user_token("acme", "user@acme.com", name="Claude", expires_in_days=30)

        assert result["data"]["name"] == "Claude"
        assert result["data"]["token"].startswith("iatmcp_")
        assert result["data"]["subject_type"] == McpToken.SUBJECT_TYPE_USER
        assert result["data"]["subject_identifier"] == "user@acme.com"
        assert result["data"]["created_by_identifier"] == "user@acme.com"
        assert result["data"]["is_active"] is True
        assert result["data"]["can_view_token"] is True

    def test_create_user_token_accepts_sso_user_identifier_without_local_user(self):
        self.mock_profile_repo.get_user_by_email.return_value = None
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = lambda token: token

        result = self.service.create_user_token("acme", "sso-user@maxxa.cl", name="Claude", expires_in_days=30)

        assert result["data"]["subject_type"] == McpToken.SUBJECT_TYPE_USER
        assert result["data"]["subject_identifier"] == "sso-user@maxxa.cl"
        self.mock_profile_repo.get_user_by_email.assert_not_called()

    def test_list_company_tokens_returns_all_subject_types(self):
        service_token = McpToken(
            id=1,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier="service:mcp",
            created_by_identifier="admin@acme.com",
            name="Service",
            token_hash="s" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        user_token = McpToken(
            id=2,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="User",
            token_hash="u" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        self.mock_repo.list_tokens.return_value = [service_token, user_token]

        result = self.service.list_company_tokens("acme")

        assert [item["subject_type"] for item in result["data"]] == [
            McpToken.SUBJECT_TYPE_SERVICE,
            McpToken.SUBJECT_TYPE_USER,
        ]
        self.mock_repo.list_tokens.assert_called_once_with(self.company.id)

    def test_create_service_token_requires_service_prefix(self):
        result = self.service.create_service_token(
            "acme",
            subject_identifier="mcp",
            name="Claude",
            expires_in_days=30,
        )

        assert result["status_code"] == 400
        assert result["error"] == "translated:errors.auth.mcp_pat_service_subject_invalid"

    def test_create_service_token_returns_raw_token_once(self):
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = lambda token: token

        result = self.service.create_service_token(
            "acme",
            subject_identifier="service:mcp",
            name="Claude",
            expires_in_days=30,
            created_by_identifier="admin@acme.com",
        )

        assert result["data"]["token"].startswith("iatmcp_")
        assert result["data"]["subject_type"] == McpToken.SUBJECT_TYPE_SERVICE
        assert result["data"]["subject_identifier"] == "service:mcp"
        assert result["data"]["created_by_identifier"] == "admin@acme.com"
        created_token = self.mock_repo.create_token.call_args[0][0]
        assert created_token.token_encrypted.startswith("encrypted:iatmcp_")
        assert created_token.created_by_identifier == "admin@acme.com"

    def test_create_service_token_requires_created_by_identifier(self):
        self.mock_repo.get_token_by_name.return_value = None

        result = self.service.create_service_token(
            "acme",
            subject_identifier="service:mcp",
            name="Claude",
            expires_in_days=30,
        )

        assert result["status_code"] == 400
        assert result["error"] == "translated:errors.auth.mcp_pat_created_by_required"
        self.mock_repo.create_token.assert_not_called()

    def test_create_service_token_accepts_two_year_expiry(self):
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = lambda token: token

        result = self.service.create_service_token(
            "acme",
            subject_identifier="service:mcp",
            name="Claude Long",
            expires_in_days=730,
            created_by_identifier="admin@acme.com",
        )

        assert result["data"]["token"].startswith("iatmcp_")
        assert result["data"]["subject_identifier"] == "service:mcp"
        assert result["data"]["is_active"] is True

    def test_create_user_token_reuses_revoked_name(self):
        token = McpToken(
            id=5,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="Claude",
            token_hash="z" * 64,
            expires_at=datetime.now() - timedelta(days=1),
            revoked_at=datetime.now() - timedelta(hours=1),
            last_used_at=datetime.now() - timedelta(hours=2),
        )
        self.mock_repo.get_token_by_name.return_value = token
        self.mock_repo.save_token.side_effect = lambda item: item

        result = self.service.create_user_token("acme", "user@acme.com", name="Claude", expires_in_days=30)

        assert result["data"]["id"] == 5
        assert result["data"]["token"].startswith("iatmcp_")
        assert token.token_encrypted.startswith("encrypted:iatmcp_")
        assert token.revoked_at is None
        assert token.last_used_at is None
        self.mock_repo.save_token.assert_called_once_with(token)

    def test_create_user_token_handles_integrity_error_as_name_conflict(self):
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = IntegrityError("stmt", "params", Exception("duplicate"))

        result = self.service.create_user_token("acme", "user@acme.com", name="Claude", expires_in_days=30)

        assert result["status_code"] == 409
        assert result["error"] == "translated:errors.auth.mcp_pat_name_exists"
        self.mock_repo.rollback.assert_called_once()

    def test_authenticate_token_updates_last_used(self):
        token = McpToken(
            id=3,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier="service:mcp",
            created_by_identifier="admin@acme.com",
            name="Claude",
            token_hash="x" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        raw_token = "iatmcp_test"
        self.mock_repo.get_active_token_by_hash.return_value = token

        result = self.service.authenticate_token("acme", raw_token)

        assert result["success"] is True
        assert result["subject_type"] == McpToken.SUBJECT_TYPE_SERVICE
        assert result["subject_identifier"] == "service:mcp"
        assert result["user_identifier"] == "service:mcp"
        assert token.last_used_at is not None
        self.mock_repo.save_token.assert_called_once_with(token)

    def test_get_company_token_connection_returns_recoverable_snippet(self):
        token = McpToken(
            id=8,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier="service:mcp",
            created_by_identifier="admin@acme.com",
            name="Claude",
            token_hash="x" * 64,
            token_encrypted="encrypted:iatmcp_saved",
            expires_at=datetime.now() + timedelta(days=1),
        )
        self.mock_repo.get_token_by_id.return_value = token

        result = self.service.get_company_token_connection("acme", 8)

        assert result["data"]["token"] == "iatmcp_saved"
        assert result["data"]["mcp_server_url"] == "https://mcp.iatoolkit.com/acme/mcp/"
        assert '"Authorization": "Bearer iatmcp_saved"' in result["data"]["connection_snippet"]
        self.mock_utility.decrypt_key.assert_called_once_with("encrypted:iatmcp_saved")

    def test_get_company_token_connection_requires_encrypted_token(self):
        token = McpToken(
            id=9,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier="service:mcp",
            created_by_identifier="admin@acme.com",
            name="Legacy",
            token_hash="x" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        self.mock_repo.get_token_by_id.return_value = token

        result = self.service.get_company_token_connection("acme", 9)

        assert result["status_code"] == 409
        assert result["error"] == "translated:errors.auth.mcp_pat_token_unavailable"

    def test_revoke_user_token_marks_revoked(self):
        token = McpToken(
            id=4,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="PyCharm",
            token_hash="y" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        self.mock_repo.get_token_by_id.return_value = token

        result = self.service.revoke_user_token("acme", "user@acme.com", 4)

        assert result["data"]["revoked_at"] is not None
        self.mock_repo.save_token.assert_called_once_with(token)

    def test_revoke_company_token_marks_any_subject_type_revoked(self):
        token = McpToken(
            id=6,
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="admin@acme.com",
            name="User",
            token_hash="q" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        self.mock_repo.get_token_by_id.return_value = token

        result = self.service.revoke_company_token("acme", 6)

        assert result["data"]["revoked_at"] is not None
        self.mock_repo.get_token_by_id.assert_called_once_with(
            self.company.id,
            6,
            subject_type=None,
            subject_identifier=None,
        )

    def test_build_connection_snippet_uses_bearer_token(self):
        snippet = self.service.build_mcp_connection_snippet(
            company_short_name="acme",
            mcp_server_url="https://mcp.example.com/acme/mcp/",
            bearer_token="iatmcp_test",
        )

        assert '"Authorization": "Bearer iatmcp_test"' in snippet
