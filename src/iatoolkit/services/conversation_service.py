# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Conversations a person can come back to (BL-001).

A conversation groups the turns of the chat: each turn is still one row of
`iat_queries` (audit and cost), and the conversation keeps its messages: what
the person asked and what the assistant answered, linked to that row. Every
read is scoped by company and owner; a conversation of someone else is simply
not found.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.conversation_repo import ConversationRepo
from iatoolkit.repositories.models import Conversation, ConversationMessage
from iatoolkit.repositories.profile_repo import ProfileRepo


class ConversationService:
    #: The title a conversation starts with: the first question, cut short.
    INITIAL_TITLE_CHARS = 60
    MAX_TITLE_CHARS = 120
    PAGE_SIZE = 50
    MAX_PAGE_SIZE = 200

    @inject
    def __init__(self, conversation_repo: ConversationRepo, profile_repo: ProfileRepo):
        self.conversation_repo = conversation_repo
        self.profile_repo = profile_repo

    # ------------------------------------------------------------------ helpers
    def _company(self, company_short_name: str):
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f"company not found: {company_short_name}")
        return company

    @staticmethod
    def _owner(user_identifier: str) -> str:
        owner = str(user_identifier or "").strip()
        if not owner:
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER,
                                     "a conversation needs a user")
        return owner

    @classmethod
    def initial_title(cls, question: str | None, prompt_name: str | None = None) -> str:
        text = re.sub(r"\s+", " ", str(question or "")).strip()
        if not text:
            text = str(prompt_name or "").replace("_", " ").strip()
        if len(text) > cls.INITIAL_TITLE_CHARS:
            cut = text[:cls.INITIAL_TITLE_CHARS].rsplit(" ", 1)[0] or text[:cls.INITIAL_TITLE_CHARS]
            text = cut.rstrip(" ,.;:") + "…"
        return text

    @classmethod
    def clean_title(cls, title: str | None) -> str:
        text = re.sub(r"\s+", " ", str(title or "")).strip().strip('"“”\'').strip()
        return text[:cls.MAX_TITLE_CHARS].strip()

    # ------------------------------------------------------------------ conversations
    def create(self, company_short_name: str, user_identifier: str, *, title: str = "",
               source: str = "chat_ui", model: str | None = None,
               prompt_name: str | None = None) -> Conversation:
        company = self._company(company_short_name)
        conversation = Conversation(
            public_id=uuid.uuid4().hex,
            company_id=company.id,
            owner_user_identifier=self._owner(user_identifier),
            title=self.clean_title(title),
            title_source=Conversation.TITLE_AUTO,
            status=Conversation.STATUS_ACTIVE,
            source=str(source or "chat_ui")[:32],
            model=model,
            prompt_name=prompt_name,
            meta={},
            last_message_at=datetime.now(),
        )
        return self.conversation_repo.add(conversation)

    def get_for_user(self, company_short_name: str, user_identifier: str, conversation_id: str,
                     include_deleted: bool = False) -> Conversation | None:
        """The person's conversation, or None (also for one of somebody else)."""
        public_id = str(conversation_id or "").strip()
        if not public_id:
            return None
        company = self._company(company_short_name)
        return self.conversation_repo.get_for_owner(company.id, self._owner(user_identifier), public_id,
                                                    include_deleted=include_deleted)

    def require_for_user(self, company_short_name: str, user_identifier: str,
                         conversation_id: str) -> Conversation:
        conversation = self.get_for_user(company_short_name, user_identifier, conversation_id)
        if conversation is None:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "conversation not found")
        return conversation

    def list_for_user(self, company_short_name: str, user_identifier: str, *, archived: bool = False,
                      search: str | None = None, before: datetime | None = None,
                      limit: int | None = None) -> list[Conversation]:
        company = self._company(company_short_name)
        size = max(1, min(int(limit or self.PAGE_SIZE), self.MAX_PAGE_SIZE))
        status = Conversation.STATUS_ARCHIVED if archived else Conversation.STATUS_ACTIVE
        return self.conversation_repo.list_for_owner(
            company.id, self._owner(user_identifier), status=status,
            search=str(search or "").strip() or None, before=before, limit=size)

    def rename(self, conversation: Conversation, title: str) -> Conversation:
        clean = self.clean_title(title)
        if not clean:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, "the title is empty")
        conversation.title = clean
        # Renamed by the person: no generated title replaces it any more.
        conversation.title_source = Conversation.TITLE_USER
        return self.conversation_repo.save(conversation)

    def set_generated_title(self, conversation: Conversation, title: str) -> bool:
        """A title written by the system agent; never over one the person chose."""
        clean = self.clean_title(title)
        if not clean or conversation.title_source == Conversation.TITLE_USER:
            return False
        conversation.title = clean
        conversation.title_source = Conversation.TITLE_GENERATED
        self.conversation_repo.save(conversation)
        return True

    def archive(self, conversation: Conversation) -> Conversation:
        conversation.status = Conversation.STATUS_ARCHIVED
        return self.conversation_repo.save(conversation)

    def restore(self, conversation: Conversation) -> Conversation:
        conversation.status = Conversation.STATUS_ACTIVE
        return self.conversation_repo.save(conversation)

    def delete(self, conversation: Conversation) -> Conversation:
        """Soft delete: gone for the person, the turns stay in iat_queries."""
        conversation.status = Conversation.STATUS_DELETED
        return self.conversation_repo.save(conversation)

    def save_meta(self, conversation: Conversation, **values) -> Conversation:
        meta = dict(conversation.meta or {})
        meta.update(values)
        conversation.meta = meta
        return self.conversation_repo.save(conversation)

    # ------------------------------------------------------------------ turns
    def _user_message(self, question: str, user_identifier: str, *, prompt_name: str | None = None,
                      attachments: list | None = None, **meta) -> ConversationMessage:
        message_meta = {key: value for key, value in meta.items() if value is not None}
        if prompt_name:
            message_meta["prompt_name"] = prompt_name
        return ConversationMessage(
            role=ConversationMessage.ROLE_USER,
            author_user_identifier=user_identifier,
            content=str(question or ""),
            attachments_meta=attachments or None,
            meta=message_meta,
        )

    def append_turn(self, conversation: Conversation, *, question: str, answer_text: str,
                    llm_query_id: int | None, user_identifier: str, prompt_name: str | None = None,
                    attachments: list | None = None) -> tuple[ConversationMessage, ConversationMessage]:
        """A turn that ended with an answer: the question and the answer."""
        user_message = self._user_message(question, user_identifier, prompt_name=prompt_name,
                                          attachments=attachments)
        assistant_message = ConversationMessage(
            role=ConversationMessage.ROLE_ASSISTANT,
            content=str(answer_text or ""),
            llm_query_id=llm_query_id,
            meta={},
        )
        self.conversation_repo.add_messages(conversation, [user_message, assistant_message])
        return user_message, assistant_message

    def append_failed_turn(self, conversation: Conversation, *, question: str, error_message: str,
                           user_identifier: str, prompt_name: str | None = None,
                           llm_query_id: int | None = None,
                           attachments: list | None = None) -> tuple[ConversationMessage, ConversationMessage]:
        """A turn that failed: the question, and the error as an event."""
        user_message = self._user_message(question, user_identifier, prompt_name=prompt_name,
                                          attachments=attachments)
        event = ConversationMessage(
            role=ConversationMessage.ROLE_SYSTEM_EVENT,
            content=str(error_message or ""),
            llm_query_id=llm_query_id,
            meta={"event": "error"},
        )
        self.conversation_repo.add_messages(conversation, [user_message, event])
        return user_message, event

    def append_cancelled_turn(self, conversation: Conversation, *, question: str, user_identifier: str,
                              prompt_name: str | None = None,
                              attachments: list | None = None) -> ConversationMessage:
        """A turn the person stopped (BL-023): only the question, marked stopped."""
        user_message = self._user_message(question, user_identifier, prompt_name=prompt_name,
                                          attachments=attachments, stopped=True)
        self.conversation_repo.add_messages(conversation, [user_message])
        return user_message

    def messages(self, conversation: Conversation) -> list[ConversationMessage]:
        return self.conversation_repo.get_messages(conversation)

    def recent_turns(self, conversation: Conversation, limit_messages: int) -> list[ConversationMessage]:
        """The latest messages, oldest first: what a reopened conversation is rebuilt from."""
        newest = self.conversation_repo.get_messages(conversation, limit=limit_messages, newest_first=True)
        return list(reversed(newest))

    # ------------------------------------------------------------------ display
    TOOL_CALL_META_KEYS = ("time", "result")

    @classmethod
    def activity_of(cls, query) -> dict:
        """What the turn did, for the collapsed activity of a reopened answer
        (BL-023): how long it took and which tools ran."""
        stats = query.stats if isinstance(getattr(query, "stats", None), dict) else {}
        stream = stats.get("stream") if isinstance(stats.get("stream"), dict) else {}
        tools = []
        for call in query.function_calls if isinstance(getattr(query, "function_calls", None), list) else []:
            if not isinstance(call, dict):
                continue
            name = next((key for key in call.keys() if key not in cls.TOOL_CALL_META_KEYS), None)
            if not name:
                continue
            result = call.get("result") if isinstance(call.get("result"), dict) else {}
            try:
                ms = int(round(float(call.get("time") or 0) * 1000))
            except (TypeError, ValueError):
                ms = 0
            tools.append({"name": name, "ok": result.get("status") != "error", "ms": ms})
        # "Thought for": until the answer started when the turn was streamed, else the whole turn.
        duration_ms = stream.get("first_text_ms")
        if not isinstance(duration_ms, (int, float)):
            duration_ms = int(stats.get("response_time") or getattr(query, "answer_time", 0) or 0) * 1000
        return {"duration_ms": int(duration_ms), "tools": tools}

    def messages_for_display(self, conversation: Conversation, answer_formatter=None) -> list[dict]:
        """The conversation as the chat draws it: each answer rendered again from
        its turn in iat_queries, with its parts (charts, files) and activity."""
        messages = self.messages(conversation)
        queries = self.conversation_repo.get_queries(
            conversation.company_id, [m.llm_query_id for m in messages if m.llm_query_id])
        shown = []
        for message in messages:
            item = {
                "id": message.id,
                "role": message.role,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            meta = message.meta or {}
            if message.role == ConversationMessage.ROLE_USER:
                item["content"] = message.content
                item["attachments"] = message.attachments_meta or []
                if meta.get("stopped"):
                    item["stopped"] = True
                if meta.get("prompt_name"):
                    item["prompt_name"] = meta["prompt_name"]
            elif message.role == ConversationMessage.ROLE_ASSISTANT:
                query = queries.get(message.llm_query_id)
                response = query.response if query is not None and isinstance(query.response, dict) else {}
                parts = response.get("parts") if isinstance(response.get("parts"), list) else []
                text = query.output if query is not None and query.output is not None else message.content
                item["answer"] = answer_formatter(text, parts) if answer_formatter else text
                item["parts"] = parts
                item["query_id"] = message.llm_query_id
                item["activity"] = self.activity_of(query) if query is not None else {"duration_ms": 0, "tools": []}
            else:
                item["content"] = message.content
                item["event"] = meta.get("event")
            shown.append(item)
        return shown

    # ------------------------------------------------------------------ title
    TITLE_AGENT_KEY = "conversation_title"
    TITLE_ANSWER_CHARS = 1500

    @property
    def system_agent_runner(self):
        runner = getattr(self, "_system_agent_runner", None)
        if runner is None:
            from iatoolkit import current_iatoolkit
            from iatoolkit.services.system_agent_runner import SystemAgentRunner
            runner = current_iatoolkit().get_injector().get(SystemAgentRunner)
            self._system_agent_runner = runner
        return runner

    @system_agent_runner.setter
    def system_agent_runner(self, runner):
        self._system_agent_runner = runner

    @staticmethod
    def _title_from(response) -> str:
        if not isinstance(response, dict):
            return ""
        for key in ("structured_output", "parsed_output"):
            value = response.get(key)
            if isinstance(value, dict) and value.get("title"):
                return str(value["title"])
        return ""

    def generate_title(self, company_short_name: str, user_identifier: str,
                       conversation: Conversation) -> Conversation:
        """A short title written by the `conversation_title` system agent from the
        first question and answer. Only for a title still automatic: one the
        person chose, or one already generated, is kept. Failures keep the
        title as it is."""
        if conversation.title_source != Conversation.TITLE_AUTO:
            return conversation
        messages = self.messages(conversation)
        question = next((m.content for m in messages if m.role == ConversationMessage.ROLE_USER and m.content), "")
        answer = next((m.content for m in messages if m.role == ConversationMessage.ROLE_ASSISTANT and m.content), "")
        if not question or not answer:
            return conversation
        try:
            from iatoolkit.services.system_agent_runner import SystemAgentRunner
            if not SystemAgentRunner.is_enabled(self.TITLE_AGENT_KEY):
                return conversation
            response = self.system_agent_runner.run(
                self._company(company_short_name), self.TITLE_AGENT_KEY,
                {"question": question[:2000], "answer": answer[:self.TITLE_ANSWER_CHARS]},
                user_identifier=user_identifier)
            self.set_generated_title(conversation, self._title_from(response))
        except Exception as e:
            logging.warning("Could not title conversation %s: %s", conversation.public_id, e)
        return conversation

    def is_first_turn(self, conversation: Conversation) -> bool:
        try:
            return self.conversation_repo.count_messages(
                conversation, roles=[ConversationMessage.ROLE_ASSISTANT]) <= 1
        except Exception as e:
            logging.warning("Could not count the messages of conversation %s: %s", conversation.public_id, e)
            return False
