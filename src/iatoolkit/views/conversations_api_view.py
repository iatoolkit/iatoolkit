# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The person's conversations (BL-001).

    GET    /<co>/api/conversations                 list (?archived=1&q=...&before=ISO&limit=50);
                                                    q searches titles and messages
    POST   /<co>/api/conversations                 create an empty one ({"title"})
    GET    /<co>/api/conversations/<id>            one conversation
    PATCH  /<co>/api/conversations/<id>            rename ({"title"}) or archive/restore ({"status"})
    DELETE /<co>/api/conversations/<id>            soft delete
    GET    /<co>/api/conversations/<id>/messages   its messages, answers rendered again
    POST   /<co>/api/conversations/<id>/title      a short title by the conversation_title system agent

Every route is scoped by company and owner: someone else's conversation is 404.
"""

from __future__ import annotations

import logging
from datetime import datetime

from flask import jsonify, request
from flask.views import MethodView
from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.models import Conversation
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.conversation_service import ConversationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.common.user_errors import unexpected_error_message


class ConversationsApiView(MethodView):
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 conversation_service: ConversationService,
                 i18n_service: I18nService,
                 llm_client: llmClient,
                 config_service: ConfigurationService = None):
        self.auth_service = auth_service
        self.conversation_service = conversation_service
        self.i18n_service = i18n_service
        self.llm_client = llm_client
        self.config_service = config_service

    # ------------------------------------------------------------------ helpers
    def _user(self, company_short_name: str):
        auth_result = self.auth_service.verify_for_company(company_short_name)
        if not auth_result.get("success"):
            return None, (jsonify(auth_result), auth_result.get("status_code") or 401)
        return auth_result.get("user_identifier"), None

    def _not_found(self):
        return jsonify({"error_message": self.i18n_service.t("errors.conversations.not_found")}), 404

    def _unexpected(self, e: Exception):
        logging.exception(f"conversations api: {e}")
        return jsonify({"error_message": unexpected_error_message(
            self.i18n_service, e, where="conversations_api_view")}), 500

    def _file_retention_days(self, company_short_name: str) -> int:
        """How long generated files are kept (enterprise deletes them after it)."""
        try:
            parameters = self.config_service.get_configuration(company_short_name, "parameters") or {}
            days = int(((parameters.get("generated_downloads") or {}).get("retention_days")) or 0)
        except Exception:
            days = 0
        return days if days > 0 else ConversationService.DEFAULT_FILE_RETENTION_DAYS

    @staticmethod
    def _parse_before(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    # ------------------------------------------------------------------ routes
    def get(self, company_short_name: str, conversation_id: str | None = None, resource: str | None = None):
        try:
            user_identifier, error = self._user(company_short_name)
            if error:
                return error
            if conversation_id is None:
                limit = request.args.get("limit", type=int) or ConversationService.PAGE_SIZE
                archived = request.args.get("archived") in ("1", "true", "yes")
                before = self._parse_before(request.args.get("before"))
                search = str(request.args.get("q") or "").strip()
                if search:
                    # Title or messages; each result says where it matched.
                    found = self.conversation_service.search_for_user(
                        company_short_name, user_identifier, search, archived=archived, before=before,
                        limit=limit + 1)
                    conversations = [dict(item.to_dict(), match=match) for item, match in found[:limit]]
                    return jsonify({"conversations": conversations, "has_more": len(found) > limit}), 200
                items = self.conversation_service.list_for_user(
                    company_short_name, user_identifier, archived=archived, before=before, limit=limit + 1)
                return jsonify({
                    "conversations": [item.to_dict() for item in items[:limit]],
                    "has_more": len(items) > limit,
                }), 200

            conversation = self.conversation_service.get_for_user(company_short_name, user_identifier,
                                                                  conversation_id)
            if conversation is None:
                return self._not_found()
            if resource == "messages":
                messages = self.conversation_service.messages_for_display(
                    conversation,
                    answer_formatter=lambda text, parts: self.llm_client.format_answer(text or "", parts=parts),
                    file_retention_days=self._file_retention_days(company_short_name),
                )
                return jsonify({"conversation": conversation.to_dict(), "messages": messages}), 200
            return jsonify({"conversation": conversation.to_dict()}), 200
        except Exception as e:
            return self._unexpected(e)

    def post(self, company_short_name: str, conversation_id: str | None = None, resource: str | None = None):
        try:
            user_identifier, error = self._user(company_short_name)
            if error:
                return error
            if conversation_id is not None:
                return self._post_on_conversation(company_short_name, user_identifier, conversation_id, resource)
            data = request.get_json(silent=True) or {}
            # The chat creates the conversation before its first turn, titled
            # with the question cut short until the title agent names it.
            title = str(data.get("title") or "") or self.conversation_service.initial_title(data.get("question"))
            conversation = self.conversation_service.create(
                company_short_name, user_identifier, title=title,
                source=str(data.get("source") or "chat_ui"), model=data.get("model") or None)
            return jsonify({"conversation": conversation.to_dict()}), 201
        except Exception as e:
            return self._unexpected(e)

    def _post_on_conversation(self, company_short_name, user_identifier, conversation_id, resource):
        conversation = self.conversation_service.get_for_user(company_short_name, user_identifier, conversation_id)
        if conversation is None or resource != "title":
            return self._not_found()
        # POST .../title: the chat asks for it once the first answer is on screen,
        # so writing it never delays an answer. Kept as is when the person chose it.
        self.conversation_service.generate_title(company_short_name, user_identifier, conversation)
        return jsonify({"conversation": conversation.to_dict()}), 200

    def patch(self, company_short_name: str, conversation_id: str | None = None, resource: str | None = None):
        try:
            user_identifier, error = self._user(company_short_name)
            if error:
                return error
            conversation = self.conversation_service.get_for_user(company_short_name, user_identifier,
                                                                  conversation_id)
            if conversation is None or resource is not None:
                return self._not_found()
            data = request.get_json(silent=True) or {}
            if "title" in data:
                try:
                    self.conversation_service.rename(conversation, str(data.get("title") or ""))
                except IAToolkitException:
                    return jsonify({"error_message": self.i18n_service.t("errors.conversations.empty_title")}), 400
            status = data.get("status")
            if status == Conversation.STATUS_ARCHIVED:
                self.conversation_service.archive(conversation)
            elif status == Conversation.STATUS_ACTIVE:
                self.conversation_service.restore(conversation)
            elif status is not None:
                return jsonify({"error_message": "status must be active or archived"}), 400
            return jsonify({"conversation": conversation.to_dict()}), 200
        except Exception as e:
            return self._unexpected(e)

    def delete(self, company_short_name: str, conversation_id: str | None = None, resource: str | None = None):
        try:
            user_identifier, error = self._user(company_short_name)
            if error:
                return error
            conversation = self.conversation_service.get_for_user(company_short_name, user_identifier,
                                                                  conversation_id)
            if conversation is None or resource is not None:
                return self._not_found()
            self.conversation_service.delete(conversation)
            return jsonify({"deleted": True}), 200
        except Exception as e:
            return self._unexpected(e)
