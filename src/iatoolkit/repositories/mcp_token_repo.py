from __future__ import annotations

from datetime import datetime

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import McpToken


class McpTokenRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.session = db_manager.get_session()

    def create_token(self, token: McpToken) -> McpToken:
        self.session.add(token)
        self.session.commit()
        return token

    def save_token(self, token: McpToken) -> McpToken:
        self.session.add(token)
        self.session.commit()
        return token

    def rollback(self) -> None:
        self.session.rollback()

    def list_tokens(
        self,
        company_id: int,
        *,
        subject_type: str | None = None,
        subject_identifier: str | None = None,
    ) -> list[McpToken]:
        query = self.session.query(McpToken).filter_by(company_id=company_id)
        if subject_type:
            query = query.filter_by(subject_type=subject_type)
        if subject_identifier:
            query = query.filter_by(subject_identifier=subject_identifier)
        return query.order_by(McpToken.created_at.desc()).all()

    def list_tokens_for_user(self, company_id: int, user_identifier: str) -> list[McpToken]:
        return self.list_tokens(
            company_id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier=user_identifier,
        )

    def list_service_tokens(self, company_id: int) -> list[McpToken]:
        return self.list_tokens(company_id, subject_type=McpToken.SUBJECT_TYPE_SERVICE)

    def get_token_by_id(
        self,
        company_id: int,
        token_id: int,
        *,
        subject_type: str | None = None,
        subject_identifier: str | None = None,
    ) -> McpToken | None:
        query = self.session.query(McpToken).filter_by(company_id=company_id, id=token_id)
        if subject_type:
            query = query.filter_by(subject_type=subject_type)
        if subject_identifier:
            query = query.filter_by(subject_identifier=subject_identifier)
        return query.first()

    def get_token_for_user(self, company_id: int, user_identifier: str, token_id: int) -> McpToken | None:
        return self.get_token_by_id(
            company_id,
            token_id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier=user_identifier,
        )

    def get_service_token_by_id(self, company_id: int, token_id: int) -> McpToken | None:
        return self.get_token_by_id(company_id, token_id, subject_type=McpToken.SUBJECT_TYPE_SERVICE)

    def get_token_by_name(
        self,
        company_id: int,
        name: str,
        *,
        subject_type: str,
        subject_identifier: str,
    ) -> McpToken | None:
        return (
            self.session.query(McpToken)
            .filter_by(
                company_id=company_id,
                subject_type=subject_type,
                subject_identifier=subject_identifier,
                name=name,
            )
            .first()
        )

    def get_active_token_by_hash(self, company_id: int, token_hash: str) -> McpToken | None:
        now = datetime.now()
        return (
            self.session.query(McpToken)
            .filter(
                McpToken.company_id == company_id,
                McpToken.token_hash == token_hash,
                McpToken.revoked_at.is_(None),
                McpToken.expires_at > now,
            )
            .first()
        )
