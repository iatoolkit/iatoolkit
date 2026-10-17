# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject
from sqlalchemy import desc, func

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (
    LLMQuery,
    MemoryQuestion,
    MemoryQuestionCandidate,
    MemoryQuestionScanCursor,
)


class MemoryQuestionRepo:
    """Memoria's unanswered questions (BL-005, Fase 1) and what the scan reads."""

    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def rollback(self) -> None:
        self.session.rollback()

    def add(self, entity):
        self.session.add(entity)
        return entity

    # --- questions -------------------------------------------------------------

    def list_questions(self, company_id: int, status: str | None = MemoryQuestion.STATUS_OPEN,
                       limit: int = 200) -> list[MemoryQuestion]:
        query = self.session.query(MemoryQuestion).filter(MemoryQuestion.company_id == company_id)
        if status:
            query = query.filter(MemoryQuestion.status == status)
        return (
            query.order_by(desc(MemoryQuestion.times_asked), desc(MemoryQuestion.last_asked_at), desc(MemoryQuestion.id))
            .limit(limit)
            .all()
        )

    def claim_open(self, company_id: int, question_id: int, status: str, resolved_by: str, resolved_at) -> bool:
        """Resolves the question only if it is still open, in one UPDATE: of two people answering at
        once, exactly one wins (Fase 0, R17). Commits."""
        claimed = (
            self.session.query(MemoryQuestion)
            .filter(MemoryQuestion.company_id == company_id, MemoryQuestion.id == question_id,
                    MemoryQuestion.status == MemoryQuestion.STATUS_OPEN)
            .update({MemoryQuestion.status: status, MemoryQuestion.resolved_by: resolved_by,
                     MemoryQuestion.resolved_at: resolved_at}, synchronize_session=False)
        )
        self.commit()
        return bool(claimed)

    def reopen(self, company_id: int, question_id: int) -> None:
        """Undoes a claim whose answer could not be saved."""
        (
            self.session.query(MemoryQuestion)
            .filter(MemoryQuestion.company_id == company_id, MemoryQuestion.id == question_id)
            .update({MemoryQuestion.status: MemoryQuestion.STATUS_OPEN, MemoryQuestion.resolved_by: None,
                     MemoryQuestion.resolved_at: None}, synchronize_session=False)
        )
        self.commit()

    def get_question(self, company_id: int, question_id: int) -> MemoryQuestion | None:
        return (
            self.session.query(MemoryQuestion)
            .filter(MemoryQuestion.company_id == company_id, MemoryQuestion.id == question_id)
            .first()
        )

    def count_open(self, company_id: int) -> int:
        return (
            self.session.query(MemoryQuestion)
            .filter(MemoryQuestion.company_id == company_id, MemoryQuestion.status == MemoryQuestion.STATUS_OPEN)
            .count()
        )

    # --- what the scan reads ---------------------------------------------------

    def get_cursor(self, company_id: int) -> MemoryQuestionScanCursor:
        cursor = (
            self.session.query(MemoryQuestionScanCursor)
            .filter(MemoryQuestionScanCursor.company_id == company_id)
            .first()
        )
        if cursor is None:
            cursor = MemoryQuestionScanCursor(company_id=company_id, last_query_id=0)
            self.session.add(cursor)
            self.commit()
        return cursor

    def list_queries_after(self, company_id: int, last_query_id: int, limit: int) -> list[LLMQuery]:
        return (
            self.session.query(LLMQuery)
            .filter(LLMQuery.company_id == company_id, LLMQuery.id > int(last_query_id or 0))
            .order_by(LLMQuery.id.asc())
            .limit(limit)
            .all()
        )

    def last_query_id_before(self, company_id: int, moment) -> int:
        """The newest iat_queries.id of the company created before `moment` (0 when none)."""
        value = (
            self.session.query(func.max(LLMQuery.id))
            .filter(LLMQuery.company_id == company_id, LLMQuery.created_at < moment)
            .scalar()
        )
        return int(value or 0)

    def has_queries_after(self, company_id: int, last_query_id: int) -> bool:
        return (
            self.session.query(LLMQuery.id)
            .filter(LLMQuery.company_id == company_id, LLMQuery.id > int(last_query_id or 0))
            .first()
            is not None
        )

    def find_cursor(self, company_id: int) -> MemoryQuestionScanCursor | None:
        return (
            self.session.query(MemoryQuestionScanCursor)
            .filter(MemoryQuestionScanCursor.company_id == company_id)
            .first()
        )

    def list_pending_candidates(self, company_id: int, limit: int) -> list[MemoryQuestionCandidate]:
        return (
            self.session.query(MemoryQuestionCandidate)
            .filter(MemoryQuestionCandidate.company_id == company_id, MemoryQuestionCandidate.processed_at.is_(None))
            .order_by(MemoryQuestionCandidate.id.asc())
            .limit(limit)
            .all()
        )

    def has_pending_candidates(self, company_id: int) -> bool:
        return (
            self.session.query(MemoryQuestionCandidate.id)
            .filter(MemoryQuestionCandidate.company_id == company_id, MemoryQuestionCandidate.processed_at.is_(None))
            .first()
            is not None
        )
