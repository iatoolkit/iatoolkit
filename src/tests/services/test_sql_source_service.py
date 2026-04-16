import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.repositories.models import Company, SqlSource
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.sql_source_repo import SqlSourceRepo
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.sql_source_service import SqlSourceService


class TestSqlSourceService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.sql_source_repo = MagicMock(spec=SqlSourceRepo)
        self.sql_service = MagicMock(spec=SqlService)
        self.secret_provider = MagicMock(spec=SecretProvider)

        self.service = SqlSourceService(
            profile_repo=self.profile_repo,
            sql_source_repo=self.sql_source_repo,
            sql_service=self.sql_service,
            secret_provider=self.secret_provider,
        )

        self.company_short_name = "acme"
        self.company = Company(id=7, short_name=self.company_short_name, name="Acme")
        self.profile_repo.get_company_by_short_name.return_value = self.company

    def test_list_sources_uses_active_filter_by_default(self):
        row = SqlSource(company_id=self.company.id, database="wealth", source=SqlSource.SOURCE_USER)
        self.sql_source_repo.list_by_company.return_value = [row]

        result = self.service.list_sources(self.company_short_name)

        assert len(result) == 1
        self.sql_source_repo.list_by_company.assert_called_once_with(self.company.id, active_only=True)

    def test_create_source_raises_duplicate_error(self):
        self.sql_source_repo.get_by_database.return_value = SqlSource(
            id=10,
            company_id=self.company.id,
            database="wealth",
            source=SqlSource.SOURCE_USER,
        )

        with pytest.raises(IAToolkitException) as exc_info:
            self.service.create_source(
                self.company_short_name,
                {
                    "database": "wealth",
                    "connection_type": "direct",
                    "connection_string_env": "WEALTH_DATABASE_URI",
                },
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DUPLICATE_ENTRY

    def test_update_source_moves_ownership_to_user(self):
        existing = SqlSource(
            id=33,
            company_id=self.company.id,
            database="wealth",
            connection_type=SqlSource.CONNECTION_DIRECT,
            connection_string_env="WEALTH_DATABASE_URI",
            schema="wealth",
            source=SqlSource.SOURCE_YAML,
            is_active=True,
        )
        self.sql_source_repo.get_by_id.return_value = existing
        self.sql_source_repo.create_or_update.side_effect = lambda source: source
        self.sql_source_repo.list_by_company.return_value = []

        result = self.service.update_source(
            self.company_short_name,
            existing.id,
            {"description": "Updated by GUI"},
        )

        assert result["description"] == "Updated by GUI"
        assert result["source"] == SqlSource.SOURCE_USER
        self.sql_service.clear_company_connections.assert_called_once_with(self.company_short_name)

    def test_sync_from_yaml_upserts_yaml_rows_and_keeps_user_rows(self):
        existing_yaml_keep = SqlSource(
            id=1,
            company_id=self.company.id,
            database="wealth",
            connection_type=SqlSource.CONNECTION_DIRECT,
            connection_string_env="WEALTH_DATABASE_URI",
            schema="wealth",
            source=SqlSource.SOURCE_YAML,
            is_active=True,
        )
        existing_yaml_remove = SqlSource(
            id=2,
            company_id=self.company.id,
            database="legacy",
            connection_type=SqlSource.CONNECTION_DIRECT,
            connection_string_env="LEGACY_DATABASE_URI",
            schema="public",
            source=SqlSource.SOURCE_YAML,
            is_active=True,
        )
        existing_user = SqlSource(
            id=3,
            company_id=self.company.id,
            database="manual",
            connection_type=SqlSource.CONNECTION_DIRECT,
            connection_string_env="MANUAL_DATABASE_URI",
            schema="public",
            source=SqlSource.SOURCE_USER,
            is_active=True,
        )

        self.sql_source_repo.list_by_company.return_value = [
            existing_yaml_keep,
            existing_yaml_remove,
            existing_user,
        ]
        self.sql_source_repo.create_or_update.side_effect = lambda source: source

        result = self.service.sync_from_yaml(
            self.company_short_name,
            [
                {
                    "database": "wealth",
                    "connection_type": "direct",
                    "connection_string_env": "WEALTH_DATABASE_URI",
                    "schema": "wealth",
                    "description": "Primary wealth model",
                },
                {
                    "database": "transactions",
                    "connection_type": "bridge",
                    "bridge_id": "bridge-wealth",
                    "schema": "wealth",
                    "description": "Bridge source",
                },
                {
                    "database": "manual",
                    "connection_type": "direct",
                    "connection_string_env": "MANUAL_DATABASE_URI",
                },
            ],
        )

        assert result == {"upserted": 2, "deleted": 1, "skipped": 1}
        assert self.sql_source_repo.create_or_update.call_count == 2
        self.sql_source_repo.delete.assert_called_once_with(existing_yaml_remove)

        updated_wealth = self.sql_source_repo.create_or_update.call_args_list[0][0][0]
        assert updated_wealth.database == "wealth"
        assert updated_wealth.description == "Primary wealth model"
        assert updated_wealth.source == SqlSource.SOURCE_YAML

        created_transactions = self.sql_source_repo.create_or_update.call_args_list[1][0][0]
        assert created_transactions.database == "transactions"
        assert created_transactions.connection_type == SqlSource.CONNECTION_BRIDGE
        assert created_transactions.bridge_id == "bridge-wealth"
        assert created_transactions.source == SqlSource.SOURCE_YAML

    def test_refresh_runtime_registers_valid_sources_and_skips_invalid(self):
        direct_ok = SqlSource(
            company_id=self.company.id,
            database="wealth",
            connection_type=SqlSource.CONNECTION_DIRECT,
            connection_string_env="WEALTH_DATABASE_URI",
            schema="wealth",
            source=SqlSource.SOURCE_USER,
            is_active=True,
        )
        direct_missing_secret = SqlSource(
            company_id=self.company.id,
            database="no_secret",
            connection_type=SqlSource.CONNECTION_DIRECT,
            connection_string_env="MISSING_URI",
            schema="public",
            source=SqlSource.SOURCE_USER,
            is_active=True,
        )
        bridge_ok = SqlSource(
            company_id=self.company.id,
            database="bridge_db",
            connection_type=SqlSource.CONNECTION_BRIDGE,
            bridge_id="bridge-01",
            schema="public",
            source=SqlSource.SOURCE_USER,
            is_active=True,
        )
        bridge_missing_id = SqlSource(
            company_id=self.company.id,
            database="bridge_bad",
            connection_type=SqlSource.CONNECTION_BRIDGE,
            bridge_id=None,
            schema="public",
            source=SqlSource.SOURCE_USER,
            is_active=True,
        )

        self.sql_source_repo.list_by_company.return_value = [
            direct_ok,
            direct_missing_secret,
            bridge_ok,
            bridge_missing_id,
        ]

        def secret_side_effect(_company_short_name, secret_ref, default=None):
            if secret_ref == "WEALTH_DATABASE_URI":
                return "postgresql://user:pwd@localhost/wealth"
            return default

        self.secret_provider.get_secret.side_effect = secret_side_effect

        result = self.service.refresh_runtime(self.company_short_name)

        assert result == {"registered": 2, "skipped": 2}
        self.sql_service.clear_company_connections.assert_called_once_with(self.company_short_name)
        assert self.sql_service.register_database.call_count == 2

        first_cfg = self.sql_service.register_database.call_args_list[0][0][2]
        assert first_cfg["connection_type"] == SqlSource.CONNECTION_DIRECT
        assert first_cfg["db_uri"].startswith("postgresql://")

        second_cfg = self.sql_service.register_database.call_args_list[1][0][2]
        assert second_cfg["connection_type"] == SqlSource.CONNECTION_BRIDGE
        assert second_cfg["bridge_id"] == "bridge-01"
