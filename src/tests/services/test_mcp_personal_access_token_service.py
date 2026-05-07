from datetime import datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from iatoolkit.repositories.models import Company, McpPersonalAccessToken
from iatoolkit.repositories.mcp_personal_access_token_repo import McpPersonalAccessTokenRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.mcp_personal_access_token_service import McpPersonalAccessTokenService


class TestMcpPersonalAccessTokenService:
    def setup_method(self):
        self.mock_i18n = MagicMock(spec=I18nService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_repo = MagicMock(spec=McpPersonalAccessTokenRepo)
        self.mock_i18n.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.company = Company(id=7, short_name="acme", name="ACME")
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.service = McpPersonalAccessTokenService(
            i18n_service=self.mock_i18n,
            profile_repo=self.mock_profile_repo,
            token_repo=self.mock_repo,
        )

    def test_create_token_requires_name(self):
        result = self.service.create_token("acme", "user@acme.com", name="")

        assert result["status_code"] == 400
        assert result["error"] == "translated:errors.auth.mcp_pat_name_required"

    def test_create_token_returns_raw_token_once(self):
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = lambda token: token

        result = self.service.create_token("acme", "user@acme.com", name="Claude", expires_in_days=30)

        assert result["data"]["name"] == "Claude"
        assert result["data"]["token"].startswith("iatmcp_")
        assert result["data"]["is_active"] is True

    def test_create_token_reuses_revoked_name(self):
        token = McpPersonalAccessToken(
            id=5,
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Claude",
            token_hash="z" * 64,
            expires_at=datetime.now() - timedelta(days=1),
            revoked_at=datetime.now() - timedelta(hours=1),
            last_used_at=datetime.now() - timedelta(hours=2),
        )
        self.mock_repo.get_token_by_name.return_value = token
        self.mock_repo.save_token.side_effect = lambda item: item

        result = self.service.create_token("acme", "user@acme.com", name="Claude", expires_in_days=30)

        assert result["data"]["id"] == 5
        assert result["data"]["token"].startswith("iatmcp_")
        assert token.revoked_at is None
        assert token.last_used_at is None
        self.mock_repo.save_token.assert_called_once_with(token)

    def test_create_token_handles_integrity_error_as_name_conflict(self):
        self.mock_repo.get_token_by_name.return_value = None
        self.mock_repo.create_token.side_effect = IntegrityError("stmt", "params", Exception("duplicate"))

        result = self.service.create_token("acme", "user@acme.com", name="Claude", expires_in_days=30)

        assert result["status_code"] == 409
        assert result["error"] == "translated:errors.auth.mcp_pat_name_exists"
        self.mock_repo.rollback.assert_called_once()

    def test_authenticate_token_updates_last_used(self):
        token = McpPersonalAccessToken(
            id=3,
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Claude",
            token_hash="x" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        raw_token = "iatmcp_test"
        self.mock_repo.get_active_token_by_hash.return_value = token

        result = self.service.authenticate_token("acme", raw_token)

        assert result["success"] is True
        assert result["user_identifier"] == "user@acme.com"
        assert token.last_used_at is not None
        self.mock_repo.save_token.assert_called_once_with(token)

    def test_revoke_token_marks_revoked(self):
        token = McpPersonalAccessToken(
            id=4,
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="PyCharm",
            token_hash="y" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        self.mock_repo.get_token_by_id.return_value = token

        result = self.service.revoke_token("acme", "user@acme.com", 4)

        assert result["data"]["revoked_at"] is not None
        self.mock_repo.save_token.assert_called_once_with(token)
