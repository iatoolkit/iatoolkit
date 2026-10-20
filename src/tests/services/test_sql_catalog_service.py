# The SQL schema a person can see (BL-017): one place for the filters, the map
# that travels in the base context and the columns asked for on demand.

from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.interfaces.asset_storage import AssetRepository
from iatoolkit.common.util import Utility
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.sql_catalog_service import SqlCatalogService
from iatoolkit.services.sql_source_service import SqlSourceService
from iatoolkit.services.sql_service import SqlService


SCHEMAS = {
    "erp": {
        "customers": {"description": "Customers.\nOne per company.", "object_type": "table",
                      "columns": [{"name": "id", "type": "INTEGER", "description": "Key"},
                                  {"name": "name", "type": "TEXT"}]},
        "orders": {"description": "Orders", "object_type": "table",
                   "columns": [{"name": "id", "type": "INTEGER"}, {"name": "customer_id", "type": "INTEGER"}]},
        "v_sales": {"description": "Sales per month", "object_type": "view",
                    "columns": [{"name": "month", "type": "DATE"}]},
        "audit_log": {"description": "Internal", "object_type": "table", "columns": [{"name": "id", "type": "INTEGER"}]},
    },
    "hr": {
        "employees": {"description": "Employees", "columns": [{"name": "id", "type": "INTEGER"}]},
    },
}


def _catalog(sources=None):
    sql_service = MagicMock(spec=SqlService)
    sql_service.get_database_dialect.return_value = "postgresql"
    source_service = MagicMock(spec=SqlSourceService)
    source_service.list_sources.return_value = sources if sources is not None else [
        {"database": "erp", "description": "The ERP", "include_all_tables": False,
         "included_tables": ["customers", "orders", "v_sales"]},
        {"database": "hr", "description": "People"},
    ]
    context_service = CompanyContextService(
        sql_service=sql_service, utility=MagicMock(spec=Utility),
        sql_source_service=source_service, asset_repo=MagicMock(spec=AssetRepository),
    )
    context_service.get_enriched_database_schema = MagicMock(
        side_effect=lambda company, db: {k: dict(v) for k, v in SCHEMAS[db].items()}
    )
    return context_service.sql_catalog


class TestSources:
    def test_the_map_lists_visible_tables_without_columns(self):
        sources = _catalog().sources("acme")

        assert [s["database_key"] for s in sources] == ["erp", "hr"]
        erp = sources[0]
        assert erp["dialect"] == "postgresql"
        assert [t["name"] for t in erp["tables"]] == ["customers", "orders", "v_sales"]  # audit_log not included
        assert erp["tables"][0]["description"] == "Customers. One per company."
        assert "columns" not in erp["tables"][0]

    def test_the_map_respects_the_person_scope(self):
        catalog = _catalog()

        sources = catalog.sources("acme", allowed_databases=["erp"], table_filter=lambda db, t: t != "orders")

        assert [s["database_key"] for s in sources] == ["erp"]
        assert [t["name"] for t in sources[0]["tables"]] == ["customers", "v_sales"]
        assert catalog.sources("acme", allowed_databases=[]) == []

    def test_render_map_explains_the_flow(self):
        catalog = _catalog()

        text = catalog.render_map(catalog.sources("acme"))

        assert "iat_sql_schema" in text and "iat_sql_query" in text
        assert "- `v_sales` (vista): Sales per month" in text
        assert "INTEGER" not in text

    def test_a_long_description_is_one_line_in_the_map(self):
        assert len(SqlCatalogService._one_line("x " * 500)) <= SqlCatalogService.MAP_DESCRIPTION_MAX_CHARS + 1


class TestDescribe:
    def test_describes_only_the_requested_tables(self):
        catalog = _catalog()

        result = catalog.describe("acme", "erp", ["Customers", "public.orders"])

        assert list(result["tables"]) == ["customers", "orders"]
        text = catalog.render_tables(result)
        assert "- `id` (INTEGER): Key" in text
        assert "v_sales" not in text

    def test_a_table_outside_included_tables_is_unknown(self):
        result = _catalog().describe("acme", "erp", ["audit_log", "customers"])

        assert list(result["tables"]) == ["customers"]
        assert result["unknown_tables"] == ["audit_log"]
        assert "audit_log" not in result["available_tables"]

    def test_table_names_are_required(self):
        catalog = _catalog()

        result = catalog.describe("acme", "erp", [])

        assert result["error"] == "table_names_required"
        assert "Indica en `table_names`" in catalog.render_tables(result)

    def test_a_database_the_person_may_not_use_is_unknown(self):
        catalog = _catalog()

        result = catalog.describe("acme", "hr", ["employees"], allowed_databases=["erp"])

        assert result["error"] == "unknown_database"
        assert result["available_databases"] == ["erp"]

    def test_more_tables_than_the_limit_are_left_for_another_call(self):
        catalog = _catalog()
        with patch.object(SqlCatalogService, "MAX_TABLES_PER_REQUEST", 2):
            result = catalog.describe("acme", "erp", ["customers", "orders", "v_sales"])

        assert list(result["tables"]) == ["customers", "orders"]
        assert result["omitted_tables"] == ["v_sales"]


class TestPersonScope:
    def test_without_groups_nothing_is_restricted(self):
        with patch("iatoolkit.services.sql_catalog_service.access.Access.registered", return_value=False):
            assert _catalog().person_scope("acme", "u1") == (None, None)

    def test_with_groups_the_allowed_sources_and_table_filter_apply(self):
        table_filter = MagicMock()
        with patch("iatoolkit.services.sql_catalog_service.access.Access.registered", return_value=True), \
                patch("iatoolkit.services.sql_catalog_service.access.can",
                      side_effect=lambda c, u, level, kind, key: key == "erp"), \
                patch("iatoolkit.services.sql_catalog_service.access.sql_table_filter", return_value=table_filter):
            assert _catalog().person_scope("acme", "u1") == (["erp"], table_filter)


class TestSchemaTool:
    def test_the_tool_answers_with_the_person_scope(self):
        from iatoolkit.services.tool_service import ToolService

        catalog = _catalog()
        tool_service = ToolService.__new__(ToolService)
        tool_service._company_context_service = catalog.company_context_service

        with patch.object(SqlCatalogService, "person_scope", return_value=(["erp"], None)):
            answer = tool_service._handle_sql_schema_tool("acme", "hr", ["employees"], user_identifier="u1")
            assert "no existe o no tienes acceso" in answer
            answer = tool_service._handle_sql_schema_tool("acme", "erp", ["orders"], user_identifier="u1")

        assert "#### Tabla: `orders`" in answer

    def test_the_schema_tool_follows_the_query_tool_access(self):
        from iatoolkit.services.resource_access_scope import SQL_TOOLS, tool_access_key

        assert tool_access_key("iat_sql_schema") == "iat_sql_query"
        assert tool_access_key("iat_document_search") == "iat_document_search"
        assert "iat_sql_schema" in SQL_TOOLS

    def test_the_tool_is_declared_and_forced_with_sql_sources(self):
        from iatoolkit.services.system_tools import SYSTEM_TOOLS_DEFINITIONS

        tool = next(t for t in SYSTEM_TOOLS_DEFINITIONS if t["function_name"] == "iat_sql_schema")
        assert tool["parameters"]["required"] == ["database_key", "table_names"]
        assert tool["routing"]["force_include_capability"] == "has_sql_sources"
