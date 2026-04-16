# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import re

from injector import inject, singleton

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.models import Company, SqlDataset
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.sql_dataset_repo import SqlDatasetRepo
from iatoolkit.repositories.sql_source_repo import SqlSourceRepo
from iatoolkit.services.sql_service import SqlService


@singleton
class SqlDatasetService:
    _SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

    @inject
    def __init__(
        self,
        profile_repo: ProfileRepo,
        sql_dataset_repo: SqlDatasetRepo,
        sql_source_repo: SqlSourceRepo,
        sql_service: SqlService,
    ):
        self.profile_repo = profile_repo
        self.sql_dataset_repo = sql_dataset_repo
        self.sql_source_repo = sql_source_repo
        self.sql_service = sql_service

    def _get_company(self, company_short_name: str) -> Company:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_NAME,
                f"Company '{company_short_name}' not found",
            )
        return company

    @staticmethod
    def _normalize_name(name: str | None) -> str:
        return str(name or "").strip()

    @staticmethod
    def _normalize_query_mode(query_mode: str | None) -> str:
        normalized = str(query_mode or SqlDataset.QUERY_MODE_TABLE_VIEW).strip().lower()
        if normalized in {SqlDataset.QUERY_MODE_TABLE_VIEW, SqlDataset.QUERY_MODE_SQL_QUERY}:
            return normalized
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"query_mode must be one of {[SqlDataset.QUERY_MODE_SQL_QUERY, SqlDataset.QUERY_MODE_TABLE_VIEW]}",
        )

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _normalize_selected_columns(value) -> list[str]:
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "selected_columns must be a list",
            )

        normalized = []
        seen = set()
        for item in value:
            column = str(item or "").strip()
            if not column or column in seen:
                continue
            seen.add(column)
            normalized.append(column)
        return normalized

    @staticmethod
    def _normalize_limit_rows(value) -> int | None:
        if value in (None, "", 0):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "limit_rows must be an integer",
            )
        if normalized <= 0:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "limit_rows must be greater than zero",
            )
        return normalized

    @staticmethod
    def _normalize_sql_source_id(value) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "sql_source_id must be an integer",
            )
        if normalized <= 0:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "sql_source_id must be greater than zero",
            )
        return normalized

    @staticmethod
    def _normalize_preview_limit(value, default: int = 20, max_limit: int = 100) -> int:
        if value in (None, "", 0):
            return default
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "preview_limit must be an integer",
            )
        if normalized <= 0:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "preview_limit must be greater than zero",
            )
        return min(normalized, max_limit)

    def _get_sql_source(self, company_id: int, sql_source_id: int):
        source = self.sql_source_repo.get_by_id(company_id, sql_source_id)
        if not source:
            raise IAToolkitException(
                IAToolkitException.ErrorType.NOT_FOUND,
                "SQL source not found",
            )
        return source

    @staticmethod
    def _assert_sql_fragment_safe(fragment: str | None, field_name: str) -> str | None:
        normalized = str(fragment or "").strip()
        if not normalized:
            return None
        trimmed = normalized.rstrip(";").strip()
        if ";" in trimmed:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"{field_name} cannot contain multiple SQL statements",
            )
        return trimmed

    @classmethod
    def _quote_identifier_path(cls, value: str, field_name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                f"Missing required field: {field_name}",
            )

        parts = [part.strip() for part in normalized.split(".")]
        if any(not part for part in parts):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"{field_name} is not a valid SQL identifier",
            )

        quoted_parts = []
        for part in parts:
            if not cls._SIMPLE_IDENTIFIER_RE.match(part):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"{field_name} is not a valid SQL identifier",
                )
            quoted_parts.append(f'"{part}"')
        return ".".join(quoted_parts)

    def _assert_safe_preview_query(self, query_sql: str | None) -> str:
        normalized = self._assert_sql_fragment_safe(query_sql, "query_sql")
        if not normalized:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field for sql_query mode: query_sql",
            )

        lowered = normalized.lstrip().lower()
        if not re.match(r"^select\b", lowered):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "Only SELECT queries are allowed for SQL dataset preview",
            )

        forbidden = re.search(r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|merge|call|copy)\b", lowered)
        if forbidden:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "Preview query contains a forbidden SQL operation",
            )
        return normalized

    def _build_table_view_query(
        self,
        *,
        table_name: str,
        selected_columns: list[str],
        filter_sql: str | None,
        order_by_sql: str | None,
        limit_rows: int | None,
    ) -> str:
        table_ref = self._quote_identifier_path(table_name, "table_name")
        columns = [
            "*" if str(column).strip() == "*" else self._quote_identifier_path(str(column), "selected_columns")
            for column in (selected_columns or ["*"])
        ]
        query = f"SELECT {', '.join(columns)} FROM {table_ref}"

        safe_filter = self._assert_sql_fragment_safe(filter_sql, "filter_sql")
        if safe_filter:
            query += f" WHERE {safe_filter}"

        safe_order = self._assert_sql_fragment_safe(order_by_sql, "order_by_sql")
        if safe_order:
            query += f" ORDER BY {safe_order}"

        if limit_rows:
            query += f" LIMIT {int(limit_rows)}"
        return query

    def _validate_dataset_fields(
        self,
        *,
        company_id: int,
        sql_source_id: int,
        name: str,
        query_mode: str,
        table_name: str | None,
        query_sql: str | None,
        primary_key: str,
    ) -> None:
        if not name:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field: name",
            )

        self._get_sql_source(company_id, sql_source_id)

        if not primary_key:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field: primary_key",
            )

        if query_mode == SqlDataset.QUERY_MODE_TABLE_VIEW and not table_name:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field for table_view mode: table_name",
            )

        if query_mode == SqlDataset.QUERY_MODE_SQL_QUERY and not query_sql:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field for sql_query mode: query_sql",
            )

    def list_datasets(self, company_short_name: str, include_inactive: bool = False) -> list[dict]:
        company = self._get_company(company_short_name)
        rows = self.sql_dataset_repo.list_by_company(company.id, active_only=not include_inactive)
        return [row.to_dict() for row in rows]

    def create_dataset(self, company_short_name: str, payload: dict) -> dict:
        company = self._get_company(company_short_name)
        payload = payload or {}

        name = self._normalize_name(payload.get("name"))
        existing = self.sql_dataset_repo.get_by_name(company.id, name)
        if existing:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DUPLICATE_ENTRY,
                f"SQL dataset '{name}' already exists",
            )

        sql_source_id = self._normalize_sql_source_id(payload.get("sql_source_id"))
        query_mode = self._normalize_query_mode(payload.get("query_mode"))
        table_name = self._normalize_optional_text(payload.get("table_name"))
        query_sql = self._normalize_optional_text(payload.get("query_sql"))
        primary_key = self._normalize_name(payload.get("primary_key"))

        self._validate_dataset_fields(
            company_id=company.id,
            sql_source_id=sql_source_id,
            name=name,
            query_mode=query_mode,
            table_name=table_name,
            query_sql=query_sql,
            primary_key=primary_key,
        )

        dataset = SqlDataset(
            company_id=company.id,
            sql_source_id=sql_source_id,
            name=name,
            description=self._normalize_optional_text(payload.get("description")),
            query_mode=query_mode,
            table_name=table_name if query_mode == SqlDataset.QUERY_MODE_TABLE_VIEW else None,
            query_sql=query_sql if query_mode == SqlDataset.QUERY_MODE_SQL_QUERY else None,
            primary_key=primary_key,
            selected_columns=self._normalize_selected_columns(payload.get("selected_columns")),
            filter_sql=self._normalize_optional_text(payload.get("filter_sql")) if query_mode == SqlDataset.QUERY_MODE_TABLE_VIEW else None,
            order_by_sql=self._normalize_optional_text(payload.get("order_by_sql")) if query_mode == SqlDataset.QUERY_MODE_TABLE_VIEW else None,
            limit_rows=self._normalize_limit_rows(payload.get("limit_rows")),
            is_active=bool(payload.get("is_active", True)),
            source=SqlDataset.SOURCE_USER,
        )

        persisted = self.sql_dataset_repo.create_or_update(dataset)
        return persisted.to_dict()

    def update_dataset(self, company_short_name: str, dataset_id: int, payload: dict) -> dict:
        company = self._get_company(company_short_name)
        payload = payload or {}

        dataset = self.sql_dataset_repo.get_by_id(company.id, dataset_id)
        if not dataset:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "SQL dataset not found")

        if "name" in payload:
            new_name = self._normalize_name(payload.get("name"))
            if not new_name:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.MISSING_PARAMETER,
                    "Missing required field: name",
                )
            collision = self.sql_dataset_repo.get_by_name(company.id, new_name)
            if collision and collision.id != dataset.id:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.DUPLICATE_ENTRY,
                    f"SQL dataset '{new_name}' already exists",
                )
            dataset.name = new_name

        if "description" in payload:
            dataset.description = self._normalize_optional_text(payload.get("description"))

        if "sql_source_id" in payload:
            dataset.sql_source_id = self._normalize_sql_source_id(payload.get("sql_source_id"))

        if "query_mode" in payload:
            dataset.query_mode = self._normalize_query_mode(payload.get("query_mode"))

        if "table_name" in payload:
            dataset.table_name = self._normalize_optional_text(payload.get("table_name"))

        if "query_sql" in payload:
            dataset.query_sql = self._normalize_optional_text(payload.get("query_sql"))

        if "primary_key" in payload:
            dataset.primary_key = self._normalize_name(payload.get("primary_key"))

        if "selected_columns" in payload:
            dataset.selected_columns = self._normalize_selected_columns(payload.get("selected_columns"))

        if "filter_sql" in payload:
            dataset.filter_sql = self._normalize_optional_text(payload.get("filter_sql"))

        if "order_by_sql" in payload:
            dataset.order_by_sql = self._normalize_optional_text(payload.get("order_by_sql"))

        if "limit_rows" in payload:
            dataset.limit_rows = self._normalize_limit_rows(payload.get("limit_rows"))

        if "is_active" in payload:
            dataset.is_active = bool(payload.get("is_active"))

        self._validate_dataset_fields(
            company_id=company.id,
            sql_source_id=dataset.sql_source_id,
            name=self._normalize_name(dataset.name),
            query_mode=self._normalize_query_mode(dataset.query_mode),
            table_name=self._normalize_optional_text(dataset.table_name),
            query_sql=self._normalize_optional_text(dataset.query_sql),
            primary_key=self._normalize_name(dataset.primary_key),
        )

        if dataset.query_mode == SqlDataset.QUERY_MODE_TABLE_VIEW:
            dataset.query_sql = None
        else:
            dataset.table_name = None
            dataset.filter_sql = None
            dataset.order_by_sql = None

        dataset.source = SqlDataset.SOURCE_USER

        persisted = self.sql_dataset_repo.create_or_update(dataset)
        return persisted.to_dict()

    def delete_dataset(self, company_short_name: str, dataset_id: int) -> None:
        company = self._get_company(company_short_name)
        dataset = self.sql_dataset_repo.get_by_id(company.id, dataset_id)
        if not dataset:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "SQL dataset not found")

        self.sql_dataset_repo.delete(dataset)

    def preview_dataset(self, company_short_name: str, payload: dict, preview_limit: int | None = None) -> dict:
        company = self._get_company(company_short_name)
        payload = payload or {}

        sql_source_id = self._normalize_sql_source_id(payload.get("sql_source_id"))
        query_mode = self._normalize_query_mode(payload.get("query_mode"))
        table_name = self._normalize_optional_text(payload.get("table_name"))
        query_sql = self._normalize_optional_text(payload.get("query_sql"))
        primary_key = self._normalize_name(payload.get("primary_key"))
        selected_columns = self._normalize_selected_columns(payload.get("selected_columns"))
        filter_sql = self._normalize_optional_text(payload.get("filter_sql"))
        order_by_sql = self._normalize_optional_text(payload.get("order_by_sql"))
        limit_rows = self._normalize_limit_rows(payload.get("limit_rows"))
        effective_preview_limit = self._normalize_preview_limit(preview_limit)

        self._validate_dataset_fields(
            company_id=company.id,
            sql_source_id=sql_source_id,
            name=self._normalize_name(payload.get("name")) or "__preview__",
            query_mode=query_mode,
            table_name=table_name,
            query_sql=query_sql,
            primary_key=primary_key,
        )

        source = self._get_sql_source(company.id, sql_source_id)

        if query_mode == SqlDataset.QUERY_MODE_TABLE_VIEW:
            if selected_columns and primary_key not in selected_columns:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "selected_columns must include the primary_key for table_view mode",
                )
            query = self._build_table_view_query(
                table_name=table_name or "",
                selected_columns=selected_columns,
                filter_sql=filter_sql,
                order_by_sql=order_by_sql,
                limit_rows=min(limit_rows, effective_preview_limit) if limit_rows else effective_preview_limit,
            )
        else:
            base_query = self._assert_safe_preview_query(query_sql)
            query = f"SELECT * FROM ({base_query}) AS sql_dataset_preview LIMIT {effective_preview_limit}"

        rows = self.sql_service.exec_sql(
            company_short_name=company_short_name,
            database_key=source.database,
            query=query,
            format="dict",
        )
        rows = rows if isinstance(rows, list) else []
        columns = list(rows[0].keys()) if rows else list(selected_columns)

        if rows and primary_key not in columns:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "Preview result does not include the configured primary_key column",
            )

        return {
            "database": source.database,
            "query_mode": query_mode,
            "primary_key": primary_key,
            "query": query,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "preview_limit": effective_preview_limit,
        }
