# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Erasing a person from a company (BL-034, R9): the right to deletion.

One transaction applies every declaration of personal_data.py to the company's
rows: deletes the person's own content, pseudonymizes the records and shared
content that stay, takes the person off lists, and removes them from the
company's members. The login account is deleted only when no other company has
the person. Rows that point to a deleted row lose the reference (a nullable
foreign key) or go with it (a required one).

After the commit, the files of deleted rows (`storage_key`) and the person's
legacy folder in storage are deleted, and so are the person's pii tokens in
Redis (R11). A receipt (iat_data_erasure_requests) keeps who asked, when and
how many rows each table lost, with the pseudonym, never the person.

A dry run does the same inside the transaction and rolls it back: the counts
are the real ones, and nothing changes.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections import Counter

from injector import inject
from sqlalchemy import delete, func, select, update

from iatoolkit.common.audit_log import emit_audit_event
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Base, DataErasureRequest
from iatoolkit.services.privacy import personal_data
from iatoolkit.services.storage_service import StorageService

PSEUDONYM_PREFIX = "erased-"
_CHUNK = 500


def pseudonym_for(company_short_name: str, identifier: str) -> str:
    """The stable stand-in of a person in a company's records: the same person
    always gets the same one, and it cannot be turned back without the key."""
    secret = (os.getenv("IATOOLKIT_SECRET_KEY") or "iatoolkit").encode("utf-8")
    message = f"{company_short_name}|{str(identifier).strip().lower()}".encode("utf-8")
    return PSEUDONYM_PREFIX + hmac.new(secret, message, hashlib.sha256).hexdigest()[:12]


def is_pseudonym(value) -> bool:
    return isinstance(value, str) and value.startswith(PSEUDONYM_PREFIX)


class CompanyScope:
    """The condition that limits a table to one company's rows, inferred from its
    columns: company_short_name, company_id, or a foreign key to a table that has one."""

    def __init__(self, metadata, company_short_name: str, company_id: int | None):
        self.metadata = metadata
        self.company_short_name = company_short_name
        self.company_id = company_id

    def clause(self, table, via: str | None = None, _depth: int = 0):
        columns = table.c
        if "company_short_name" in columns:
            return columns.company_short_name == self.company_short_name
        if "company_id" in columns and self.company_id is not None:
            return columns.company_id == self.company_id
        if _depth > 2:
            return None
        foreign_keys = [fk for fk in table.foreign_keys if via is None or fk.parent.name == via]
        for fk in foreign_keys:
            parent = fk.column.table
            parent_clause = self.clause(parent, _depth=_depth + 1)
            if parent_clause is not None:
                return fk.parent.in_(select(fk.column).where(parent_clause))
        return None


class PrivacyErasureService:
    @inject
    def __init__(self, db_manager: DatabaseManager, storage_service: StorageService):
        self.db_manager = db_manager
        self.storage_service = storage_service

    @property
    def metadata(self):
        return Base.metadata

    # ------------------------------------------------------------------ public

    def erase(self, company_short_name: str, identifier: str, *, requested_by: str,
              dry_run: bool = False) -> dict:
        identifier = str(identifier or "").strip()
        if not identifier or ("@" not in identifier and ":" in identifier):
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                     "Indica el identificador (correo) de una persona.")
        if is_pseudonym(identifier):
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                     "Ese identificador ya es un seudónimo.")

        session = self.db_manager.get_session()
        company_id = self._company_id(session, company_short_name)
        if company_id is None:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND,
                                     f"La empresa '{company_short_name}' no existe.")

        scope = CompanyScope(self.metadata, company_short_name, company_id)
        pseudonym = pseudonym_for(company_short_name, identifier)
        counts: Counter = Counter()
        storage_keys: list[str] = []
        try:
            for item in personal_data.acting(personal_data.DELETE):
                self._delete_declared(session, scope, item, identifier, counts, storage_keys)
            for item in personal_data.acting(personal_data.PSEUDONYMIZE):
                self._pseudonymize_declared(session, scope, item, identifier, pseudonym, counts)
            for item in personal_data.acting(personal_data.REMOVE_FROM_LIST):
                self._remove_from_lists(session, scope, item, identifier, counts)
            account_outcome = self._leave_company(session, company_id, identifier, counts, storage_keys)

            summary = {key: value for key, value in sorted(counts.items()) if value}
            result = {
                "company_short_name": company_short_name,
                "pseudonym": pseudonym,
                "dry_run": dry_run,
                "account": account_outcome,
                "summary": summary,
                "rows": sum(summary.values()),
                "files": len(set(storage_keys)),
            }
            if dry_run:
                session.rollback()
                return result

            receipt = DataErasureRequest(
                company_short_name=company_short_name, pseudonym=pseudonym,
                requested_by=str(requested_by or "-"), status="completed",
                account_outcome=account_outcome, summary=summary, files_deleted=0)
            session.add(receipt)
            session.commit()
        except Exception:
            session.rollback()
            raise

        files_deleted = self._delete_files(company_short_name, identifier, storage_keys)
        self._forget_tokens(company_short_name, identifier)
        if files_deleted:
            try:
                receipt.files_deleted = files_deleted
                session.commit()
            except Exception as exc:
                session.rollback()
                logging.warning("privacy erasure: could not record the files deleted: %s", exc)

        result.update(files=files_deleted, receipt_id=receipt.id)
        logging.info("event=data_erased company=%s pseudonym=%s rows=%s files=%s account=%s requested_by=%s",
                     company_short_name, pseudonym, result["rows"], files_deleted, account_outcome, requested_by)
        emit_audit_event("data_erasure", company=company_short_name, user=requested_by,
                         pseudonym=pseudonym, rows=result["rows"], files=files_deleted,
                         account=account_outcome)
        return result

    def list_receipts(self, company_short_name: str, limit: int = 50) -> list[dict]:
        session = self.db_manager.get_session()
        rows = (session.query(DataErasureRequest)
                .filter(DataErasureRequest.company_short_name == company_short_name)
                .order_by(DataErasureRequest.id.desc())
                .limit(limit).all())
        return [{
            "id": row.id, "pseudonym": row.pseudonym, "requested_by": row.requested_by,
            "account": row.account_outcome, "rows": sum((row.summary or {}).values()),
            "summary": row.summary or {}, "files": row.files_deleted,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        } for row in rows]

    # ------------------------------------------------------------ declarations

    def _table(self, name: str):
        for table in self.metadata.tables.values():
            if table.name == name:
                return table
        return None

    def _match(self, table, item, identifier: str, user_id: int | None = None):
        column = table.c[item.column]
        if item.match == personal_data.MATCH_USER_ID:
            if user_id is None:
                return None
            clause = column == user_id
        else:
            clause = func.lower(column) == identifier.lower()
        for name, value in item.where:
            clause = clause & (table.c[name] == value)
        return clause

    def _scoped(self, scope: CompanyScope, table, item, identifier: str):
        table_scope = scope.clause(table, item.via)
        if table_scope is None:
            logging.warning("privacy erasure: %s has no company scope; skipped", table.name)
            return None
        match = self._match(table, item, identifier)
        return None if match is None else (table_scope & match)

    def _delete_declared(self, session, scope, item, identifier, counts, storage_keys) -> None:
        table = self._table(item.table)
        if table is None:
            return
        clause = self._scoped(scope, table, item, identifier)
        if clause is not None:
            self.delete_rows(session, table, clause, counts, storage_keys)

    def _pseudonymize_declared(self, session, scope, item, identifier, pseudonym, counts) -> None:
        table = self._table(item.table)
        if table is None:
            return
        clause = self._scoped(scope, table, item, identifier)
        if clause is None:
            return
        values = {item.column: pseudonym}
        values.update(dict(item.scrub))
        changed = session.execute(update(table).where(clause).values(values)).rowcount or 0
        counts[f"{table.name}.{item.column}"] += changed

    def _remove_from_lists(self, session, scope, item, identifier, counts) -> None:
        table = self._table(item.table)
        if table is None:
            return
        table_scope = scope.clause(table, item.via)
        if table_scope is None:
            return
        pk = self._primary_key(table)
        column = table.c[item.column]
        wanted = identifier.lower()
        for row_id, values in session.execute(select(pk, column).where(table_scope)).all():
            if not isinstance(values, list):
                continue
            kept = [value for value in values if str(value).strip().lower() != wanted]
            if len(kept) != len(values):
                session.execute(update(table).where(pk == row_id).values({item.column: kept}))
                counts[f"{table.name}.{item.column}"] += 1

    # ------------------------------------------------------------- the account

    def _leave_company(self, session, company_id: int, identifier: str, counts, storage_keys) -> str:
        users = self._table("iat_users")
        memberships = self._table("iat_user_company")
        if users is None or memberships is None:
            return "not_found"
        wanted = identifier.lower()
        user_ids = [row[0] for row in session.execute(
            select(users.c.id).where((func.lower(users.c.email) == wanted)
                                     | (func.lower(users.c.google_email) == wanted))).all()]
        if not user_ids:
            return "not_found"

        outcome = "left_company"
        for user_id in user_ids:
            removed = session.execute(delete(memberships).where(
                (memberships.c.user_id == user_id) & (memberships.c.company_id == company_id))).rowcount or 0
            counts["iat_user_company"] += removed
            others = session.execute(select(func.count()).select_from(memberships).where(
                memberships.c.user_id == user_id)).scalar() or 0
            if others == 0:
                self.delete_rows(session, users, users.c.id == user_id, counts, storage_keys)
                outcome = "deleted"
        return outcome

    # ------------------------------------------------- rows and their children

    @staticmethod
    def _primary_key(table):
        columns = list(table.primary_key.columns)
        if len(columns) != 1:
            raise ValueError(f"{table.name} has no single-column primary key")
        return columns[0]

    def delete_rows(self, session, table, clause, counts, storage_keys, _depth: int = 0) -> int:
        """Deletes the rows and deals with what points to them: a nullable foreign
        key is set to NULL, a required one takes its rows along."""
        if _depth > 6:
            raise ValueError(f"privacy erasure: foreign keys too deep at {table.name}")
        if not table.primary_key.columns or len(table.primary_key.columns) != 1:
            deleted = session.execute(delete(table).where(clause)).rowcount or 0
            counts[table.name] += deleted
            return deleted

        pk = self._primary_key(table)
        has_files = "storage_key" in table.c
        selected = [pk, table.c.storage_key] if has_files else [pk]
        rows = session.execute(select(*selected).where(clause)).all()
        if not rows:
            return 0
        ids = [row[0] for row in rows]
        if has_files:
            storage_keys.extend(row[1] for row in rows if row[1])

        for start in range(0, len(ids), _CHUNK):
            chunk = ids[start:start + _CHUNK]
            self._detach_children(session, table, chunk, counts, storage_keys, _depth)
            session.execute(delete(table).where(pk.in_(chunk)))
        counts[table.name] += len(ids)
        return len(ids)

    def _detach_children(self, session, table, ids, counts, storage_keys, depth) -> None:
        for child in self.metadata.tables.values():
            for fk in child.foreign_keys:
                if fk.column.table is not table:
                    continue
                column = fk.parent
                if child is table and column is fk.column:
                    continue
                if column.nullable:
                    changed = session.execute(
                        update(child).where(column.in_(ids)).values({column.name: None})).rowcount or 0
                    if changed:
                        counts[f"{child.name}.{column.name}=NULL"] += changed
                else:
                    self.delete_rows(session, child, column.in_(ids), counts, storage_keys, depth + 1)

    # ---------------------------------------------------------- outside the DB

    @staticmethod
    def _company_id(session, company_short_name: str) -> int | None:
        companies = None
        for table in Base.metadata.tables.values():
            if table.name == "iat_companies":
                companies = table
        if companies is None:
            return None
        return session.execute(select(companies.c.id).where(
            companies.c.short_name == company_short_name)).scalar()

    def _delete_files(self, company_short_name: str, identifier: str, storage_keys: list[str]) -> int:
        keys = list(dict.fromkeys(key for key in storage_keys if key))
        # The person's folder of the retired per-user Memoria: companies/<c>/users/<u>/.
        for name in dict.fromkeys((identifier, identifier.lower())):
            prefix = f"companies/{company_short_name}/users/{name}/"
            try:
                for entry in self.storage_service.list_files(company_short_name, prefix=prefix) or []:
                    key = entry.get("path") if isinstance(entry, dict) else entry
                    if key and str(key).startswith(prefix):
                        keys.append(str(key))
            except Exception as exc:
                logging.info("privacy erasure: no legacy folder listed for %s: %s", company_short_name, exc)
        deleted = 0
        for key in dict.fromkeys(keys):
            try:
                self.storage_service.delete_file(company_short_name, key)
                deleted += 1
            except Exception as exc:
                logging.warning("privacy erasure: could not delete file %s of %s: %s", key, company_short_name, exc)
        return deleted

    @staticmethod
    def _forget_tokens(company_short_name: str, identifier: str) -> None:
        try:
            from iatoolkit.infra.redis_session_manager import RedisSessionManager
            from iatoolkit.services.pii_masking_service import PiiMaskingService

            for name in dict.fromkeys((identifier, identifier.lower())):
                RedisSessionManager.remove(f"{PiiMaskingService.VAULT_PREFIX}:{company_short_name}:{name}")
        except Exception as exc:
            logging.info("privacy erasure: pii tokens of %s not removed: %s", company_short_name, exc)

