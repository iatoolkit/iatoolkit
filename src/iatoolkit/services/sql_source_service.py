# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging

from injector import inject, singleton

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import normalize_secret_ref, resolve_secret
from iatoolkit.repositories.models import Company, SqlSource
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.sql_source_repo import SqlSourceRepo
from iatoolkit.services.sql_service import SqlService


@singleton
class SqlSourceService:
    @inject
    def __init__(
        self,
        profile_repo: ProfileRepo,
        sql_source_repo: SqlSourceRepo,
        sql_service: SqlService,
        secret_provider: SecretProvider,
    ):
        self.profile_repo = profile_repo
        self.sql_source_repo = sql_source_repo
        self.sql_service = sql_service
        self.secret_provider = secret_provider

    def _get_company(self, company_short_name: str) -> Company:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_NAME,
                f"Company '{company_short_name}' not found",
            )
        return company

    @staticmethod
    def _normalize_database(database: str | None) -> str:
        return str(database or "").strip()

    @staticmethod
    def _normalize_connection_type(connection_type: str | None) -> str:
        normalized = str(connection_type or SqlSource.CONNECTION_DIRECT).strip().lower()
        if normalized in {SqlSource.CONNECTION_DIRECT, SqlSource.CONNECTION_BRIDGE}:
            return normalized
        return SqlSource.CONNECTION_DIRECT

    @staticmethod
    def _normalize_source(source: str | None) -> str:
        normalized = str(source or SqlSource.SOURCE_USER).strip().upper()
        if normalized in {SqlSource.SOURCE_YAML, SqlSource.SOURCE_USER}:
            return normalized
        return SqlSource.SOURCE_USER

    @staticmethod
    def _normalize_schema(schema_name: str | None) -> str:
        normalized = str(schema_name or "").strip()
        return normalized or "public"

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    def _validate_source_fields(
        self,
        *,
        database: str,
        connection_type: str,
        connection_string_env: str | None,
        bridge_id: str | None,
    ) -> None:
        if not database:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field: database",
            )

        if connection_type == SqlSource.CONNECTION_DIRECT and not connection_string_env:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field for direct connection: connection_string_env",
            )

        if connection_type == SqlSource.CONNECTION_BRIDGE and not bridge_id:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "Missing required field for bridge connection: bridge_id",
            )

    def list_sources(self, company_short_name: str, include_inactive: bool = False) -> list[dict]:
        company = self._get_company(company_short_name)
        rows = self.sql_source_repo.list_by_company(company.id, active_only=not include_inactive)
        return [row.to_dict() for row in rows]

    def create_source(self, company_short_name: str, payload: dict) -> dict:
        company = self._get_company(company_short_name)
        payload = payload or {}

        database = self._normalize_database(payload.get("database"))
        existing = self.sql_source_repo.get_by_database(company.id, database)
        if existing:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DUPLICATE_ENTRY,
                f"SQL source '{database}' already exists",
            )

        connection_type = self._normalize_connection_type(payload.get("connection_type"))
        connection_string_env = normalize_secret_ref(
            payload.get("connection_string_env") or payload.get("connection_string_secret_ref")
        ) or None
        bridge_id = self._normalize_optional_text(payload.get("bridge_id"))
        self._validate_source_fields(
            database=database,
            connection_type=connection_type,
            connection_string_env=connection_string_env,
            bridge_id=bridge_id,
        )

        source = SqlSource(
            company_id=company.id,
            database=database,
            connection_type=connection_type,
            connection_string_env=connection_string_env,
            schema=self._normalize_schema(payload.get("schema")),
            description=self._normalize_optional_text(payload.get("description")),
            bridge_id=bridge_id,
            source=self._normalize_source(payload.get("source") or SqlSource.SOURCE_USER),
            is_active=bool(payload.get("is_active", True)),
        )

        persisted = self.sql_source_repo.create_or_update(source)
        self.refresh_runtime(company_short_name)
        return persisted.to_dict()

    def update_source(self, company_short_name: str, source_id: int, payload: dict) -> dict:
        company = self._get_company(company_short_name)
        payload = payload or {}

        source = self.sql_source_repo.get_by_id(company.id, source_id)
        if not source:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "SQL source not found")

        if "database" in payload:
            new_database = self._normalize_database(payload.get("database"))
            if not new_database:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.MISSING_PARAMETER,
                    "Missing required field: database",
                )
            collision = self.sql_source_repo.get_by_database(company.id, new_database)
            if collision and collision.id != source.id:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.DUPLICATE_ENTRY,
                    f"SQL source '{new_database}' already exists",
                )
            source.database = new_database

        if "connection_type" in payload:
            source.connection_type = self._normalize_connection_type(payload.get("connection_type"))

        if "connection_string_env" in payload or "connection_string_secret_ref" in payload:
            source.connection_string_env = normalize_secret_ref(
                payload.get("connection_string_env") or payload.get("connection_string_secret_ref")
            ) or None

        if "schema" in payload:
            source.schema = self._normalize_schema(payload.get("schema"))

        if "description" in payload:
            source.description = self._normalize_optional_text(payload.get("description"))

        if "bridge_id" in payload:
            source.bridge_id = self._normalize_optional_text(payload.get("bridge_id"))

        if "is_active" in payload:
            source.is_active = bool(payload.get("is_active"))

        # Once edited via API, ownership moves to USER.
        source.source = SqlSource.SOURCE_USER

        self._validate_source_fields(
            database=self._normalize_database(source.database),
            connection_type=self._normalize_connection_type(source.connection_type),
            connection_string_env=normalize_secret_ref(source.connection_string_env) or None,
            bridge_id=self._normalize_optional_text(source.bridge_id),
        )

        persisted = self.sql_source_repo.create_or_update(source)
        self.refresh_runtime(company_short_name)
        return persisted.to_dict()

    def delete_source(self, company_short_name: str, source_id: int) -> None:
        company = self._get_company(company_short_name)
        source = self.sql_source_repo.get_by_id(company.id, source_id)
        if not source:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "SQL source not found")

        self.sql_source_repo.delete(source)
        self.refresh_runtime(company_short_name)

    def sync_from_yaml(self, company_short_name: str, sql_sources: list[dict] | None) -> dict:
        company = self._get_company(company_short_name)
        sources_from_yaml = sql_sources or []
        if not isinstance(sources_from_yaml, list):
            sources_from_yaml = []

        existing_rows = self.sql_source_repo.list_by_company(company.id, active_only=False)
        by_database = {self._normalize_database(row.database): row for row in existing_rows}

        desired_yaml_dbs: set[str] = set()
        upserted = 0
        skipped = 0

        for raw in sources_from_yaml:
            if not isinstance(raw, dict):
                skipped += 1
                continue

            database = self._normalize_database(raw.get("database"))
            if not database:
                skipped += 1
                continue

            desired_yaml_dbs.add(database)
            existing = by_database.get(database)
            if existing and existing.source == SqlSource.SOURCE_USER:
                skipped += 1
                logging.warning(
                    "Skipping YAML SQL source '%s' for '%s': owned by USER source.",
                    database,
                    company_short_name,
                )
                continue

            connection_type = self._normalize_connection_type(raw.get("connection_type"))
            connection_string_env = normalize_secret_ref(
                raw.get("connection_string_secret_ref") or raw.get("connection_string_env")
            ) or None
            bridge_id = self._normalize_optional_text(raw.get("bridge_id"))

            try:
                self._validate_source_fields(
                    database=database,
                    connection_type=connection_type,
                    connection_string_env=connection_string_env,
                    bridge_id=bridge_id,
                )
            except IAToolkitException as exc:
                skipped += 1
                logging.warning(
                    "Skipping invalid YAML SQL source '%s' for '%s': %s",
                    database,
                    company_short_name,
                    exc,
                )
                continue

            target = existing or SqlSource(company_id=company.id, database=database)
            target.connection_type = connection_type
            target.connection_string_env = connection_string_env
            target.schema = self._normalize_schema(raw.get("schema"))
            target.description = self._normalize_optional_text(raw.get("description"))
            target.bridge_id = bridge_id
            target.source = SqlSource.SOURCE_YAML
            target.is_active = bool(raw.get("is_active", True))

            persisted = self.sql_source_repo.create_or_update(target)
            by_database[database] = persisted
            upserted += 1

        deleted = 0
        for row in list(by_database.values()):
            database = self._normalize_database(row.database)
            if row.source != SqlSource.SOURCE_YAML:
                continue
            if database in desired_yaml_dbs:
                continue
            self.sql_source_repo.delete(row)
            deleted += 1

        return {
            "upserted": upserted,
            "deleted": deleted,
            "skipped": skipped,
        }

    def refresh_runtime(self, company_short_name: str) -> dict:
        company = self._get_company(company_short_name)
        self.sql_service.clear_company_connections(company_short_name)

        active_sources = self.sql_source_repo.list_by_company(company.id, active_only=True)
        registered = 0
        skipped = 0

        for src in active_sources:
            db_name = self._normalize_database(src.database)
            connection_type = self._normalize_connection_type(src.connection_type)
            schema_name = self._normalize_schema(src.schema)

            db_config = {
                "database": db_name,
                "schema": schema_name,
                "connection_type": connection_type,
                "bridge_id": self._normalize_optional_text(src.bridge_id),
            }

            if connection_type == SqlSource.CONNECTION_DIRECT:
                secret_ref = normalize_secret_ref(src.connection_string_env)
                db_uri = resolve_secret(self.secret_provider, company_short_name, secret_ref)
                if not db_uri:
                    skipped += 1
                    logging.error(
                        "Skipping SQL source '%s' for '%s': missing secret '%s'.",
                        db_name,
                        company_short_name,
                        secret_ref,
                    )
                    continue
                db_config["db_uri"] = db_uri

            elif connection_type == SqlSource.CONNECTION_BRIDGE:
                if not db_config.get("bridge_id"):
                    skipped += 1
                    logging.error(
                        "Skipping SQL source '%s' for '%s': missing bridge_id.",
                        db_name,
                        company_short_name,
                    )
                    continue

            self.sql_service.register_database(company_short_name, db_name, db_config)
            registered += 1

        return {"registered": registered, "skipped": skipped}

