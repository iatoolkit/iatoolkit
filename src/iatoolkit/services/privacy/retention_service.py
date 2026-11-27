# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
How long a company keeps personal data (BL-034, R9).

Set per company in company.yaml; nothing is set by default, and what is not
set is never touched:

    privacy:
      retention:
        conversations_days: 365   # questions, answers, conversations, feedback: deleted
        audit_days: 730           # access log, tool calls, MCP requests: pseudonymized

Each declaration of personal_data.py with a retention category applies its own
action to the company's rows older than the limit, dated by its own column:
DELETE removes them (and their files), PSEUDONYMIZE replaces each person by the
same pseudonym an erasure would use. A daily job runs it for every company
(Enterprise: the `privacy_retention` platform job); `flask privacy-retention`
runs it by hand. A dry run counts and changes nothing.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta

from injector import inject
from sqlalchemy import and_, distinct, select, update

from iatoolkit.common.audit_log import emit_audit_event
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.privacy import personal_data
from iatoolkit.services.privacy.erasure_service import (
    PSEUDONYM_PREFIX, CompanyScope, PrivacyErasureService, pseudonym_for,
)

SETTING_KEYS = {
    personal_data.RETENTION_CONVERSATIONS: "conversations_days",
    personal_data.RETENTION_AUDIT: "audit_days",
}


def parse_retention(privacy_config) -> tuple[dict[str, int], list[str]]:
    """The days per category a company.yaml `privacy` section sets, and its errors."""
    days, errors = {}, []
    retention = (privacy_config or {}).get("retention") if isinstance(privacy_config, dict) else None
    if retention is None:
        return days, errors
    if not isinstance(retention, dict):
        return days, ["privacy.retention: Must be a dictionary."]
    known = set(SETTING_KEYS.values())
    for key in sorted(set(retention) - known):
        errors.append(f"privacy.retention.{key}: Unknown key. Use one of {sorted(known)}.")
    for category, key in SETTING_KEYS.items():
        value = retention.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"privacy.retention.{key}: Must be a whole number of days, 1 or more.")
            continue
        days[category] = value
    return days, errors


class PrivacyRetentionService:
    @inject
    def __init__(self, db_manager: DatabaseManager, configuration_service: ConfigurationService,
                 erasure_service: PrivacyErasureService):
        self.db_manager = db_manager
        self.configuration_service = configuration_service
        self.erasure_service = erasure_service

    def settings(self, company_short_name: str) -> dict[str, int]:
        try:
            privacy = self.configuration_service.get_configuration(company_short_name, "privacy")
        except Exception as exc:
            logging.warning("privacy retention: no configuration for %s: %s", company_short_name, exc)
            return {}
        days, errors = parse_retention(privacy)
        for error in errors:
            logging.warning("privacy retention: %s: %s", company_short_name, error)
        return days

    def apply(self, company_short_name: str, *, dry_run: bool = False, now: datetime | None = None) -> dict:
        days = self.settings(company_short_name)
        result = {"company_short_name": company_short_name, "dry_run": dry_run,
                  "retention": days, "summary": {}, "rows": 0, "files": 0}
        if not days:
            result["status"] = "not_configured"
            return result

        session = self.db_manager.get_session()
        company_id = self.erasure_service._company_id(session, company_short_name)
        if company_id is None:
            result["status"] = "company_not_found"
            return result

        scope = CompanyScope(self.erasure_service.metadata, company_short_name, company_id)
        now = now or datetime.now()
        counts: Counter = Counter()
        storage_keys: list[str] = []
        try:
            for item in personal_data.declared():
                if item.retention not in days or item.action not in (personal_data.DELETE, personal_data.PSEUDONYMIZE):
                    continue
                table = self.erasure_service._table(item.table)
                if table is None:
                    continue
                table_scope = scope.clause(table, item.via)
                if table_scope is None:
                    continue
                cutoff = now - timedelta(days=days[item.retention])
                old = and_(table_scope, table.c[item.age_column] < cutoff)
                if item.action == personal_data.DELETE:
                    self.erasure_service.delete_rows(session, table, old, counts, storage_keys)
                else:
                    self._pseudonymize_old(session, table, item, old, company_short_name, counts)
            if dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception:
            session.rollback()
            raise

        files = 0 if dry_run else self._delete_files(company_short_name, storage_keys)
        summary = {key: value for key, value in sorted(counts.items()) if value}
        result.update(status="dry_run" if dry_run else "completed", summary=summary,
                      rows=sum(summary.values()), files=files if not dry_run else len(set(storage_keys)))
        if not dry_run and result["rows"]:
            logging.info("event=privacy_retention company=%s rows=%s files=%s", company_short_name,
                         result["rows"], files)
            emit_audit_event("privacy_retention", company=company_short_name, rows=result["rows"], files=files)
        return result

    @staticmethod
    def _pseudonymize_old(session, table, item, old_clause, company_short_name: str, counts) -> None:
        column = table.c[item.column]
        clause = and_(old_clause, column.isnot(None), ~column.like(f"{PSEUDONYM_PREFIX}%"))
        for name, value in item.where:
            clause = and_(clause, table.c[name] == value)
        identities = [row[0] for row in session.execute(select(distinct(column)).where(clause)).all()]
        for identity in identities:
            text = str(identity or "").strip()
            # Service principals ("service:mcp") are not people.
            if not text or ("@" not in text and ":" in text):
                continue
            values = {item.column: pseudonym_for(company_short_name, text)}
            values.update(dict(item.scrub))
            changed = session.execute(update(table).where(and_(clause, column == identity))
                                      .values(values)).rowcount or 0
            counts[f"{table.name}.{item.column}"] += changed

    def _delete_files(self, company_short_name: str, storage_keys: list[str]) -> int:
        deleted = 0
        for key in dict.fromkeys(key for key in storage_keys if key):
            try:
                self.erasure_service.storage_service.delete_file(company_short_name, key)
                deleted += 1
            except Exception as exc:
                logging.warning("privacy retention: could not delete file %s of %s: %s", key, company_short_name, exc)
        return deleted
