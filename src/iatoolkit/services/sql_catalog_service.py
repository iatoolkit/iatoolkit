# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
The SQL schema a person can see, in one place (BL-017).

Two levels, as the MCP always worked: a map of each source (its tables, without
columns) that is cheap enough to travel in every model call, and the columns of
the tables a question needs, asked for when it needs them (`iat_sql_schema` in
the chat, `get_sql_schema` over MCP).

Every filter lives here, so the chat and the MCP cannot show different tables to
the same person: the source must be active, the person must be allowed the
source (BL-010), the table must be one of the source's `included_tables`, and
tables holding resources of their own (enterprise's knowledge tables) must pass
`access.sql_table_filter`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from iatoolkit.common import access

TableFilter = Optional[Callable[[str, str], bool]]


class SqlCatalogService:
    #: Tables one call to `iat_sql_schema` may describe: the columns of a whole
    #: database in one answer is the cost this service exists to avoid.
    MAX_TABLES_PER_REQUEST = 10
    #: One line per table in the map.
    MAP_DESCRIPTION_MAX_CHARS = 200
    SCHEMA_TOOL_NAME = "iat_sql_schema"
    QUERY_TOOL_NAME = "iat_sql_query"

    def __init__(self, company_context_service, sql_source_service, sql_service):
        # Built by CompanyContextService itself (it owns the enriched schema and
        # this owns what of it a person sees), so no injector cycle between them.
        self.company_context_service = company_context_service
        self.sql_source_service = sql_source_service
        self.sql_service = sql_service

    # ------------------------------------------------------------------
    # Scope of a person
    # ------------------------------------------------------------------

    def person_scope(self, company_short_name: str, user_identifier: str | None) -> tuple[list[str] | None, TableFilter]:
        """(allowed databases, table filter) for this person; (None, None) when nothing is restricted."""
        if not user_identifier or not access.Access.registered():
            return None, None
        databases = [str(s.get("database") or "") for s in self._active_sources(company_short_name) if s.get("database")]
        allowed = [d for d in databases
                   if access.can(company_short_name, user_identifier, access.USE, "sql_source", d)]
        table_filter = access.sql_table_filter(company_short_name, user_identifier)
        return (None if len(allowed) == len(databases) else allowed), table_filter

    # ------------------------------------------------------------------
    # The two levels
    # ------------------------------------------------------------------

    def sources(self, company_short_name: str, *, allowed_databases: list[str] | None = None,
                table_filter: TableFilter = None) -> list[dict]:
        """Each visible source with its visible tables (name, kind, description), no columns."""
        allowed = self._allowed_set(allowed_databases)
        if allowed is not None and not allowed:
            return []
        items = []
        for source in self._active_sources(company_short_name):
            database_key = str(source.get("database") or "").strip()
            if not database_key or (allowed is not None and database_key not in allowed):
                continue
            try:
                tables = self.visible_schema(company_short_name, database_key, source=source, table_filter=table_filter)
            except Exception as e:
                logging.warning(f"Could not read the schema of '{database_key}' for '{company_short_name}': {e}")
                continue
            if not tables:
                continue
            items.append({
                "database_key": database_key,
                "dialect": self._dialect(company_short_name, database_key),
                "description": str(source.get("description") or "").strip(),
                "tables": [
                    {
                        "name": name,
                        "object_type": data.get("object_type") or "table",
                        "description": self._one_line(data.get("description")),
                    }
                    for name, data in tables.items()
                ],
            })
        return items

    def describe(self, company_short_name: str, database_key: str, table_names: list[str] | None, *,
                 allowed_databases: list[str] | None = None, table_filter: TableFilter = None) -> dict:
        """The columns of the requested tables of one source, or why they cannot be given."""
        database_key = str(database_key or "").strip()
        source = self._source(company_short_name, database_key)
        allowed = self._allowed_set(allowed_databases)
        if source is None or (allowed is not None and database_key not in allowed):
            return {"database_key": database_key, "error": "unknown_database",
                    "available_databases": [s["database_key"] for s in self.sources(
                        company_short_name, allowed_databases=allowed_databases, table_filter=table_filter)]}

        visible = self.visible_schema(company_short_name, database_key, source=source, table_filter=table_filter)
        requested = [str(name or "").strip() for name in (table_names or []) if str(name or "").strip()]
        if not requested:
            return {"database_key": database_key, "error": "table_names_required",
                    "available_tables": list(visible.keys())}

        index = {}
        for name in visible:
            for candidate in self.company_context_service._table_name_candidates(name):
                index.setdefault(candidate, name)
        found: dict[str, dict] = {}
        unknown: list[str] = []
        for name in requested:
            match = next((index[c] for c in self.company_context_service._table_name_candidates(name) if c in index), None)
            if match is None:
                unknown.append(name)
            elif match not in found:
                found[match] = visible[match]

        omitted = list(found)[self.MAX_TABLES_PER_REQUEST:]
        for name in omitted:
            found.pop(name)
        result = {
            "database_key": database_key,
            "dialect": self._dialect(company_short_name, database_key),
            "tables": found,
        }
        if unknown:
            result["unknown_tables"] = unknown
            result["available_tables"] = list(visible.keys())
        if omitted:
            result["omitted_tables"] = omitted
        return result

    def visible_schema(self, company_short_name: str, database_key: str, *, source: dict | None = None,
                       table_filter: TableFilter = None) -> dict:
        """The enriched schema of one source, narrowed to the tables a person may see."""
        source = source if source is not None else self._source(company_short_name, database_key)
        if source is None:
            return {}
        ccs = self.company_context_service
        schema = ccs.get_enriched_database_schema(company_short_name, database_key) or {}
        included = ccs._resolve_allowed_tables_for_source(source)
        return {
            name: data
            for name, data in schema.items()
            if ccs._table_is_allowed(name, included)
            and (table_filter is None or table_filter(database_key, name))
        }

    # ------------------------------------------------------------------
    # What the model reads
    # ------------------------------------------------------------------

    def render_map(self, sources: list[dict]) -> str:
        if not sources:
            return ""
        parts = []
        for source in sources:
            dialect = f" [dialect={source['dialect']}]" if source.get("dialect") else ""
            lines = [f"### Base SQL (`database_key`): {source['database_key']}{dialect}"]
            if source.get("description"):
                lines.append(f"- Descripcion: {source['description']}")
            lines.append("- Tablas:")
            for table in source.get("tables") or []:
                kind = " (vista)" if table.get("object_type") == "view" else ""
                description = f": {table['description']}" if table.get("description") else ""
                lines.append(f"  - `{table['name']}`{kind}{description}")
            parts.append("\n".join(lines))
        header = (
            "## Bases de datos SQL disponibles\n\n"
            f"Estas son las bases SQL que puedes consultar, con sus tablas. Antes de escribir una consulta, "
            f"pide con `{self.SCHEMA_TOOL_NAME}` las columnas de las tablas que vas a usar (varias en una sola "
            f"llamada); luego consulta con `{self.QUERY_TOOL_NAME}`. Usa solo tablas de esta lista y columnas "
            f"que `{self.SCHEMA_TOOL_NAME}` te haya mostrado.\n"
        )
        return header + "\n\n---\n\n".join(parts)

    def render_tables(self, description: dict) -> str:
        """`describe`'s answer as the model reads it: the columns of each table, or what to do instead."""
        database_key = description.get("database_key") or ""
        error = description.get("error")
        if error == "unknown_database":
            available = ", ".join(f"`{d}`" for d in description.get("available_databases") or []) or "(ninguna)"
            return f"La base `{database_key}` no existe o no tienes acceso. Bases disponibles: {available}."
        if error == "table_names_required":
            return (f"Indica en `table_names` las tablas de `{database_key}` que necesitas (hasta "
                    f"{self.MAX_TABLES_PER_REQUEST}). Tablas: {self._names(description.get('available_tables'))}.")

        dialect = f" [dialect={description['dialect']}]" if description.get("dialect") else ""
        out = [f"### Base SQL (`database_key`): {database_key}{dialect}"]
        for table_name, table_data in (description.get("tables") or {}).items():
            out.append(self._render_table(table_name, table_data))
        if description.get("unknown_tables"):
            out.append(
                f"\nNo existen o no tienes acceso: {self._names(description['unknown_tables'])}. "
                f"Tablas de `{database_key}`: {self._names(description.get('available_tables'))}."
            )
        if description.get("omitted_tables"):
            out.append(
                f"\nSe describen hasta {self.MAX_TABLES_PER_REQUEST} tablas por llamada; pide en otra: "
                f"{self._names(description['omitted_tables'])}."
            )
        return "\n".join(out)

    def _render_table(self, table_name: str, table_data: dict) -> str:
        text = f"\n#### Tabla: `{table_name}`"
        if table_data.get("description"):
            text += f"\n- Descripcion: {table_data['description']}"
        text += "\n- Columnas:"
        for column in table_data.get("columns") or []:
            line = f"\n  - `{column.get('name')}` ({column.get('type', 'unknown')})"
            if column.get("description"):
                line += f": {column['description']}"
            text += line
            if column.get("properties"):
                text += "\n" + self.company_context_service._format_json_schema(column["properties"], 2)
        return text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _active_sources(self, company_short_name: str) -> list[dict]:
        return self.sql_source_service.list_sources(company_short_name, include_inactive=False) or []

    def _source(self, company_short_name: str, database_key: str) -> dict | None:
        return next((s for s in self._active_sources(company_short_name)
                     if str(s.get("database") or "").strip() == database_key), None)

    def _dialect(self, company_short_name: str, database_key: str) -> str:
        try:
            return self.sql_service.get_database_dialect(company_short_name, database_key) or ""
        except Exception:
            return ""

    @staticmethod
    def _allowed_set(allowed_databases: list[str] | None) -> set[str] | None:
        if allowed_databases is None:
            return None
        return {str(d or "").strip() for d in allowed_databases if str(d or "").strip()}

    @classmethod
    def _one_line(cls, description: Any) -> str:
        text = " ".join(str(description or "").split())
        if len(text) <= cls.MAP_DESCRIPTION_MAX_CHARS:
            return text
        return text[:cls.MAP_DESCRIPTION_MAX_CHARS].rstrip() + "…"

    @staticmethod
    def _names(names: list[str] | None) -> str:
        return ", ".join(f"`{n}`" for n in names or []) or "(ninguna)"
