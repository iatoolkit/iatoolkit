from datetime import datetime, timedelta

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.mcp_personal_access_token_repo import McpPersonalAccessTokenRepo
from iatoolkit.repositories.models import Company, McpPersonalAccessToken


class TestMcpPersonalAccessTokenRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager("sqlite:///:memory:")
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = McpPersonalAccessTokenRepo(self.db_manager)

        self.company = Company(name="Acme", short_name="acme")
        self.other_company = Company(name="Other", short_name="other")
        self.session.add_all([self.company, self.other_company])
        self.session.commit()

    def test_create_and_list_tokens_for_user(self):
        older = McpPersonalAccessToken(
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Older",
            token_hash="a" * 64,
            created_at=datetime.now() - timedelta(days=1),
            expires_at=datetime.now() + timedelta(days=10),
        )
        newer = McpPersonalAccessToken(
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Newer",
            token_hash="b" * 64,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=10),
        )
        foreign = McpPersonalAccessToken(
            company_id=self.other_company.id,
            user_identifier="user@acme.com",
            name="Foreign",
            token_hash="c" * 64,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=10),
        )
        self.session.add_all([older, newer, foreign])
        self.session.commit()

        items = self.repo.list_tokens_for_user(self.company.id, "user@acme.com")

        assert [item.name for item in items] == ["Newer", "Older"]

    def test_get_active_token_by_hash_filters_revoked_and_expired(self):
        active = McpPersonalAccessToken(
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Active",
            token_hash="d" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        expired = McpPersonalAccessToken(
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Expired",
            token_hash="e" * 64,
            expires_at=datetime.now() - timedelta(seconds=1),
        )
        revoked = McpPersonalAccessToken(
            company_id=self.company.id,
            user_identifier="user@acme.com",
            name="Revoked",
            token_hash="f" * 64,
            expires_at=datetime.now() + timedelta(days=1),
            revoked_at=datetime.now(),
        )
        self.session.add_all([active, expired, revoked])
        self.session.commit()

        assert self.repo.get_active_token_by_hash(self.company.id, "d" * 64).name == "Active"
        assert self.repo.get_active_token_by_hash(self.company.id, "e" * 64) is None
        assert self.repo.get_active_token_by_hash(self.company.id, "f" * 64) is None
