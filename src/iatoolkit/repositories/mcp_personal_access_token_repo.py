from __future__ import annotations

from datetime import datetime

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import McpPersonalAccessToken


class McpPersonalAccessTokenRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.session = db_manager.get_session()

    def create_token(self, token: McpPersonalAccessToken) -> McpPersonalAccessToken:
        self.session.add(token)
        self.session.commit()
        return token

    def save_token(self, token: McpPersonalAccessToken) -> McpPersonalAccessToken:
        self.session.add(token)
        self.session.commit()
        return token

    def rollback(self) -> None:
        self.session.rollback()

    def list_tokens_for_user(self, company_id: int, user_identifier: str) -> list[McpPersonalAccessToken]:
        return (
            self.session.query(McpPersonalAccessToken)
            .filter_by(company_id=company_id, user_identifier=user_identifier)
            .order_by(McpPersonalAccessToken.created_at.desc())
            .all()
        )

    def get_token_by_id(self, company_id: int, user_identifier: str, token_id: int) -> McpPersonalAccessToken | None:
        return (
            self.session.query(McpPersonalAccessToken)
            .filter_by(company_id=company_id, user_identifier=user_identifier, id=token_id)
            .first()
        )

    def get_token_by_name(self, company_id: int, user_identifier: str, name: str) -> McpPersonalAccessToken | None:
        return (
            self.session.query(McpPersonalAccessToken)
            .filter_by(company_id=company_id, user_identifier=user_identifier, name=name)
            .first()
        )

    def get_active_token_by_hash(self, company_id: int, token_hash: str) -> McpPersonalAccessToken | None:
        now = datetime.now()
        return (
            self.session.query(McpPersonalAccessToken)
            .filter(
                McpPersonalAccessToken.company_id == company_id,
                McpPersonalAccessToken.token_hash == token_hash,
                McpPersonalAccessToken.revoked_at.is_(None),
                McpPersonalAccessToken.expires_at > now,
            )
            .first()
        )
