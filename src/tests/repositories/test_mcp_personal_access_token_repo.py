from datetime import datetime, timedelta

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.mcp_token_repo import McpTokenRepo
from iatoolkit.repositories.models import Company, McpToken


class TestMcpTokenRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager("sqlite:///:memory:")
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = McpTokenRepo(self.db_manager)

        self.company = Company(name="Acme", short_name="acme")
        self.other_company = Company(name="Other", short_name="other")
        self.session.add_all([self.company, self.other_company])
        self.session.commit()

    def test_create_and_list_tokens_for_user(self):
        older = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="Older",
            token_hash="a" * 64,
            created_at=datetime.now() - timedelta(days=1),
            expires_at=datetime.now() + timedelta(days=10),
        )
        newer = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="Newer",
            token_hash="b" * 64,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=10),
        )
        foreign = McpToken(
            company_id=self.other_company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="Foreign",
            token_hash="c" * 64,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=10),
        )
        self.session.add_all([older, newer, foreign])
        self.session.commit()

        items = self.repo.list_tokens_for_user(self.company.id, "user@acme.com")

        assert [item.name for item in items] == ["Newer", "Older"]

    def test_list_service_tokens_filters_subject_type(self):
        service = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier="service:mcp",
            created_by_identifier="admin@acme.com",
            name="Service",
            token_hash="s" * 64,
            expires_at=datetime.now() + timedelta(days=10),
        )
        user = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="admin@acme.com",
            name="User",
            token_hash="u" * 64,
            expires_at=datetime.now() + timedelta(days=10),
        )
        self.session.add_all([service, user])
        self.session.commit()

        items = self.repo.list_service_tokens(self.company.id)

        assert [item.name for item in items] == ["Service"]

    def test_get_active_token_by_hash_filters_revoked_and_expired(self):
        active = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="Active",
            token_hash="d" * 64,
            expires_at=datetime.now() + timedelta(days=1),
        )
        expired = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier="user@acme.com",
            created_by_identifier="user@acme.com",
            name="Expired",
            token_hash="e" * 64,
            expires_at=datetime.now() - timedelta(seconds=1),
        )
        revoked = McpToken(
            company_id=self.company.id,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier="service:mcp",
            created_by_identifier="admin@acme.com",
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
