# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from datetime import datetime

from injector import inject
from sqlalchemy import or_

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Conversation, ConversationMessage, LLMQuery


class ConversationRepo:
    """Conversations and their messages (BL-001). Every read is scoped by
    company and owner: the service never asks for a conversation by id alone."""

    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    @property
    def session(self):
        return self.db_manager.get_session()

    # ------------------------------------------------------------ conversations
    def add(self, conversation: Conversation) -> Conversation:
        self.session.add(conversation)
        self.session.commit()
        return conversation

    def save(self, conversation: Conversation) -> Conversation:
        self.session.add(conversation)
        self.session.commit()
        return conversation

    def get_for_owner(self, company_id: int, owner_user_identifier: str, public_id: str,
                      include_deleted: bool = False) -> Conversation | None:
        query = self.session.query(Conversation).filter(
            Conversation.company_id == company_id,
            Conversation.owner_user_identifier == owner_user_identifier,
            Conversation.public_id == public_id,
        )
        if not include_deleted:
            query = query.filter(Conversation.status != Conversation.STATUS_DELETED)
        return query.first()

    def list_for_owner(self, company_id: int, owner_user_identifier: str, *, status: str,
                       search: str | None = None, before: datetime | None = None,
                       limit: int = 50) -> list[Conversation]:
        query = self.session.query(Conversation).filter(
            Conversation.company_id == company_id,
            Conversation.owner_user_identifier == owner_user_identifier,
            Conversation.status == status,
        )
        if search:
            # The title or what was said in it (BL-001): the person's questions
            # and the assistant's answers as written.
            pattern = f"%{search}%"
            in_messages = (self.session.query(ConversationMessage.id)
                           .filter(ConversationMessage.conversation_id == Conversation.id,
                                   ConversationMessage.role.in_([ConversationMessage.ROLE_USER,
                                                                 ConversationMessage.ROLE_ASSISTANT]),
                                   ConversationMessage.content.ilike(pattern))
                           .exists())
            query = query.filter(or_(Conversation.title.ilike(pattern), in_messages))
        if before is not None:
            query = query.filter(Conversation.last_message_at < before)
        return (query.order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
                .limit(limit).all())

    def matching_messages(self, conversation_ids: list[int], search: str) -> dict[int, ConversationMessage]:
        """The latest message of each conversation that says `search`."""
        if not conversation_ids or not search:
            return {}
        rows = (self.session.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id.in_(conversation_ids),
                        ConversationMessage.role.in_([ConversationMessage.ROLE_USER,
                                                      ConversationMessage.ROLE_ASSISTANT]),
                        ConversationMessage.content.ilike(f"%{search}%"))
                .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
                .all())
        found: dict[int, ConversationMessage] = {}
        for row in rows:
            found.setdefault(row.conversation_id, row)
        return found

    # ------------------------------------------------------------ messages
    def add_messages(self, conversation: Conversation, messages: list[ConversationMessage]):
        for message in messages:
            message.conversation_id = conversation.id
            message.company_id = conversation.company_id
            self.session.add(message)
        conversation.last_message_at = datetime.now()
        self.session.add(conversation)
        self.session.commit()

    def get_messages(self, conversation: Conversation, *, limit: int | None = None,
                     newest_first: bool = False) -> list[ConversationMessage]:
        order = ConversationMessage.created_at.desc() if newest_first else ConversationMessage.created_at.asc()
        tie = ConversationMessage.id.desc() if newest_first else ConversationMessage.id.asc()
        query = (self.session.query(ConversationMessage)
                 .filter(ConversationMessage.conversation_id == conversation.id)
                 .order_by(order, tie))
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_queries(self, company_id: int, query_ids: list[int]) -> dict[int, LLMQuery]:
        if not query_ids:
            return {}
        rows = (self.session.query(LLMQuery)
                .filter(LLMQuery.company_id == company_id, LLMQuery.id.in_(query_ids))
                .all())
        return {row.id: row for row in rows}

    def count_messages(self, conversation: Conversation, roles: list[str] | None = None) -> int:
        query = self.session.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation.id)
        if roles:
            query = query.filter(or_(*[ConversationMessage.role == role for role in roles]))
        return query.count()

    def rollback(self):
        self.session.rollback()
