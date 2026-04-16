import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.models import Company, SqlDataset, SqlSource
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.sql_dataset_repo import SqlDatasetRepo
from iatoolkit.repositories.sql_source_repo import SqlSourceRepo
from iatoolkit.services.sql_dataset_service import SqlDatasetService
from iatoolkit.services.sql_service import SqlService


class TestSqlDatasetService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.sql_dataset_repo = MagicMock(spec=SqlDatasetRepo)
        self.sql_source_repo = MagicMock(spec=SqlSourceRepo)
        self.sql_service = MagicMock(spec=SqlService)

        self.service = SqlDatasetService(
            profile_repo=self.profile_repo,
            sql_dataset_repo=self.sql_dataset_repo,
            sql_source_repo=self.sql_source_repo,
            sql_service=self.sql_service,
        )

        self.company_short_name = "acme"
        self.company = Company(id=7, short_name=self.company_short_name, name="Acme")
        self.profile_repo.get_company_by_short_name.return_value = self.company
        self.sql_dataset_repo.get_by_name.return_value = None
        self.sql_dataset_repo.get_by_id.return_value = None
        self.sql_source = SqlSource(
            id=11,
            company_id=self.company.id,
            database="wealth",
            source=SqlSource.SOURCE_USER,
        )
        self.sql_source_repo.get_by_id.return_value = self.sql_source

    def test_list_datasets_uses_active_filter_by_default(self):
        row = SqlDataset(
            id=21,
            company_id=self.company.id,
            sql_source_id=self.sql_source.id,
            name="Open tickets",
            query_mode=SqlDataset.QUERY_MODE_SQL_QUERY,
            query_sql="SELECT * FROM tickets",
            primary_key="ticket_id",
        )
        self.sql_dataset_repo.list_by_company.return_value = [row]

        result = self.service.list_datasets(self.company_short_name)

        assert len(result) == 1
        self.sql_dataset_repo.list_by_company.assert_called_once_with(self.company.id, active_only=True)

    def test_create_dataset_raises_duplicate_error(self):
        self.sql_dataset_repo.get_by_name.return_value = SqlDataset(
            id=10,
            company_id=self.company.id,
            sql_source_id=self.sql_source.id,
            name="Open tickets",
            query_mode=SqlDataset.QUERY_MODE_TABLE_VIEW,
            table_name="tickets",
            primary_key="ticket_id",
        )

        with pytest.raises(IAToolkitException) as exc_info:
            self.service.create_dataset(
                self.company_short_name,
                {
                    "name": "Open tickets",
                    "sql_source_id": self.sql_source.id,
                    "query_mode": "table_view",
                    "table_name": "tickets",
                    "primary_key": "ticket_id",
                },
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DUPLICATE_ENTRY

    def test_create_dataset_requires_table_name_for_table_view(self):
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.create_dataset(
                self.company_short_name,
                {
                    "name": "Open tickets",
                    "sql_source_id": self.sql_source.id,
                    "query_mode": "table_view",
                    "primary_key": "ticket_id",
                },
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.MISSING_PARAMETER

    def test_create_dataset_persists_sql_query_mode(self):
        self.sql_dataset_repo.create_or_update.side_effect = lambda dataset: dataset

        result = self.service.create_dataset(
            self.company_short_name,
            {
                "name": "Open tickets",
                "description": "Tickets to classify",
                "sql_source_id": self.sql_source.id,
                "query_mode": "sql_query",
                "query_sql": "SELECT ticket_id, subject FROM tickets WHERE status = 'open'",
                "primary_key": "ticket_id",
                "selected_columns": ["ticket_id", "subject", "ticket_id"],
                "limit_rows": 500,
                "is_active": True,
            },
        )

        assert result["name"] == "Open tickets"
        assert result["query_mode"] == SqlDataset.QUERY_MODE_SQL_QUERY
        assert result["query_sql"].startswith("SELECT ticket_id")
        assert result["selected_columns"] == ["ticket_id", "subject"]
        assert result["limit_rows"] == 500

    def test_update_dataset_switches_to_table_view_and_clears_sql_query_fields(self):
        existing = SqlDataset(
            id=33,
            company_id=self.company.id,
            sql_source_id=self.sql_source.id,
            name="Open tickets",
            query_mode=SqlDataset.QUERY_MODE_SQL_QUERY,
            query_sql="SELECT ticket_id FROM tickets",
            primary_key="ticket_id",
            selected_columns=["ticket_id"],
            is_active=True,
        )
        self.sql_dataset_repo.get_by_id.return_value = existing
        self.sql_dataset_repo.create_or_update.side_effect = lambda dataset: dataset

        result = self.service.update_dataset(
            self.company_short_name,
            existing.id,
            {
                "query_mode": "table_view",
                "table_name": "tickets",
                "filter_sql": "status = 'open'",
                "order_by_sql": "ticket_id desc",
            },
        )

        assert result["query_mode"] == SqlDataset.QUERY_MODE_TABLE_VIEW
        assert result["table_name"] == "tickets"
        assert result["query_sql"] is None
        assert result["filter_sql"] == "status = 'open'"

    def test_delete_dataset_not_found_maps_to_not_found(self):
        self.sql_dataset_repo.get_by_id.return_value = None

        with pytest.raises(IAToolkitException) as exc_info:
            self.service.delete_dataset(self.company_short_name, 999)

        assert exc_info.value.error_type == IAToolkitException.ErrorType.NOT_FOUND

    def test_preview_dataset_builds_table_view_query_and_returns_rows(self):
        self.sql_service.exec_sql.return_value = [{"ticket_id": 1, "subject": "hello"}]

        result = self.service.preview_dataset(
            self.company_short_name,
            {
                "sql_source_id": self.sql_source.id,
                "query_mode": "table_view",
                "table_name": "tickets",
                "primary_key": "ticket_id",
                "selected_columns": ["ticket_id", "subject"],
                "filter_sql": "status = 'open'",
                "order_by_sql": "ticket_id desc",
                "limit_rows": 50,
            },
            preview_limit=10,
        )

        assert result["database"] == "wealth"
        assert result["row_count"] == 1
        assert result["columns"] == ["ticket_id", "subject"]
        assert 'SELECT "ticket_id", "subject" FROM "tickets"' in result["query"]
        assert result["query"].endswith("LIMIT 10")

    def test_preview_dataset_quotes_reserved_table_and_column_names(self):
        self.sql_service.exec_sql.return_value = [{"orderid": 1, "customerid": "ALFKI"}]

        result = self.service.preview_dataset(
            self.company_short_name,
            {
                "sql_source_id": self.sql_source.id,
                "query_mode": "table_view",
                "table_name": "order",
                "primary_key": "orderid",
                "selected_columns": ["orderid", "customerid"],
                "limit_rows": 5,
            },
            preview_limit=5,
        )

        assert 'SELECT "orderid", "customerid" FROM "order"' in result["query"]
        assert result["query"].endswith("LIMIT 5")

    def test_preview_dataset_rejects_invalid_table_identifier(self):
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.preview_dataset(
                self.company_short_name,
                {
                    "sql_source_id": self.sql_source.id,
                    "query_mode": "table_view",
                    "table_name": "orders where 1=1",
                    "primary_key": "orderid",
                    "selected_columns": ["orderid"],
                },
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER

    def test_preview_dataset_wraps_sql_query_and_caps_preview_limit(self):
        self.sql_service.exec_sql.return_value = [{"ticket_id": 3, "subject": "x"}]

        result = self.service.preview_dataset(
            self.company_short_name,
            {
                "sql_source_id": self.sql_source.id,
                "query_mode": "sql_query",
                "query_sql": "SELECT ticket_id, subject FROM tickets WHERE status = 'open'",
                "primary_key": "ticket_id",
            },
            preview_limit=200,
        )

        assert result["preview_limit"] == 100
        assert result["query"].startswith("SELECT * FROM (SELECT ticket_id, subject FROM tickets")
        self.sql_service.exec_sql.assert_called_once()

    def test_preview_dataset_accepts_multiline_select_query(self):
        self.sql_service.exec_sql.return_value = [{"customerid": "ALFKI"}]

        result = self.service.preview_dataset(
            self.company_short_name,
            {
                "sql_source_id": self.sql_source.id,
                "query_mode": "sql_query",
                "query_sql": "select\n    c.customerid\nfrom sample_db.customers c\nlimit 5",
                "primary_key": "customerid",
            },
            preview_limit=20,
        )

        assert result["row_count"] == 1
        assert "sql_dataset_preview" in result["query"]

    def test_preview_dataset_rejects_non_select_queries(self):
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.preview_dataset(
                self.company_short_name,
                {
                    "sql_source_id": self.sql_source.id,
                    "query_mode": "sql_query",
                    "query_sql": "DELETE FROM tickets",
                    "primary_key": "ticket_id",
                },
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER

    def test_preview_dataset_requires_primary_key_in_selected_columns_for_table_view(self):
        with pytest.raises(IAToolkitException) as exc_info:
            self.service.preview_dataset(
                self.company_short_name,
                {
                    "sql_source_id": self.sql_source.id,
                    "query_mode": "table_view",
                    "table_name": "tickets",
                    "primary_key": "ticket_id",
                    "selected_columns": ["subject"],
                },
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
