# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


import logging
import json
from typing import Dict, Any, Optional
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.repositories.models import Company
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from injector import inject


class HistoryManagerService:
    """
    Manages conversation history for LLMs in a unified way.
    Handles:
    1. Server-side history (e.g., OpenAI response_ids).
    2. Client-side history (e.g., Gemini message lists).
    3. Database persistence retrieval (full chat history).
    """
    TYPE_SERVER_SIDE = 'server_side'  # For models like OpenAI
    TYPE_CLIENT_SIDE = 'client_side'  # For models like Gemini and Deepseek

    GEMINI_MAX_TOKENS_CONTEXT_HISTORY = 200000


    @inject
    def __init__(self,
                 session_context: UserSessionContextService,
                 i18n: I18nService,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 llm_client: Optional[llmClient] = None):
        self.session_context = session_context
        self.i18n = i18n
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.llm_client = llm_client

    def initialize_context(self,
                           company_short_name: str,
                           user_identifier: str,
                           history_type: str,
                           prepared_context: str,
                           company: Company, model: str) -> Dict[str, Any]:
        """
        Initializes a new conversation history.
        """
        # 1. Clear existing history
        self.session_context.clear_llm_history(company_short_name, user_identifier, model=model)

        if history_type == self.TYPE_SERVER_SIDE:
            # OpenAI: Send system prompt to API and store the resulting ID
            response_id = self.llm_client.set_company_context(
                company=company,
                company_base_context=prepared_context,
                model=model
            )
            self.session_context.save_last_response_id(company_short_name, user_identifier, response_id, model=model)
            self.session_context.save_initial_response_id(company_short_name, user_identifier, response_id, model=model)
            return {'response_id': response_id}

        elif history_type == self.TYPE_CLIENT_SIDE:
            # Gemini: Store system prompt as the first message in the list
            context_history = [{"role": "user", "content": prepared_context}]
            self.session_context.save_context_history(company_short_name, user_identifier, context_history, model=model)
            return {}

        return {}

    def populate_request_params(self,
                                handle: Any,
                                user_turn_prompt: str,
                                ignore_history: bool = False) -> bool:
        """
        Populates the request_params within the HistoryHandle.
        Returns True if a rebuild is needed, False otherwise.
        """
        model = getattr(handle, "model", None)

        if handle.type == self.TYPE_SERVER_SIDE:
            previous_response_id = None
            if ignore_history:
                previous_response_id = self.session_context.get_initial_response_id(
                    handle.company_short_name,handle.user_identifier,model=model)

            else:
                previous_response_id = self.session_context.get_last_response_id(
                    handle.company_short_name,handle.user_identifier,model=model)


            if not previous_response_id:
                handle.request_params = {}
                return True  # Needs rebuild

            handle.request_params = {'previous_response_id': previous_response_id}
            return False

        elif handle.type == self.TYPE_CLIENT_SIDE:
            context_history = self.session_context.get_context_history(
                handle.company_short_name,handle.user_identifier,model=model) or []

            if not context_history:
                handle.request_params = {}
                return True  # Needs rebuild

            if ignore_history and len(context_history) > 1:
                # Keep only system prompt
                context_history = [context_history[0]]

            # For Gemini, we append the current user turn to the context sent to the API
            context_history.append({"role": "user", "content": user_turn_prompt})

            self._trim_context_history(context_history)

            handle.request_params = {'context_history': context_history}
            return False

        handle.request_params = {}
        return False

    def update_history(self,
                       history_handle: Any,
                       user_turn_prompt: str,
                       response: Dict[str, Any]):
        """Saves or updates the history after a successful LLM call."""

        # We access the type from the handle
        history_type = history_handle.type
        company_short_name = history_handle.company_short_name
        user_identifier = history_handle.user_identifier
        model = getattr(history_handle, "model", None)

        if history_type == self.TYPE_SERVER_SIDE:
            if "response_id" in response:
                self.session_context.save_last_response_id(
                    company_short_name,
                    user_identifier,
                    response["response_id"],
                    model=model)

        elif history_type == self.TYPE_CLIENT_SIDE:
            context_history = self.session_context.get_context_history(
                company_short_name,
                user_identifier,
                model=model) or []

            # Ensure the user prompt is recorded if not already.
            # We check content equality to handle the case where the previous message was
            # also 'user' (e.g., System Prompt) but different content.
            last_content = context_history[-1].get("content") if context_history else None

            if last_content != user_turn_prompt:
                context_history.append({"role": "user", "content": user_turn_prompt})

            if response.get('answer'):
                context_history.append({"role": "model", "content": response['answer']})

            self.session_context.save_context_history(
                company_short_name,
                user_identifier,
                context_history,
                model=model)

    def _trim_context_history(self, context_history: list):
        """Internal helper to keep token usage within limits for client-side history."""
        if not context_history or len(context_history) <= 1:
            return
        try:
            total_tokens = sum(self.llm_client.count_tokens(json.dumps(message)) for message in context_history)
        except Exception as e:
            logging.error(f"Error counting tokens for history: {e}.")
            return

        while total_tokens > self.GEMINI_MAX_TOKENS_CONTEXT_HISTORY and len(context_history) > 1:
            try:
                # Remove the oldest message after system prompt
                removed_message = context_history.pop(1)
                removed_tokens = self.llm_client.count_tokens(json.dumps(removed_message))
                total_tokens -= removed_tokens
                logging.warning(
                    f"History tokens exceed limit. Removed old message. New total: {total_tokens} tokens."
                )
            except IndexError:
                break

    # --- Database History Management (Legacy HistoryService) ---

    def get_full_history(self, company_short_name: str, user_identifier: str) -> dict:
        """Retrieves the full persisted history from the database."""
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {"error": self.i18n.t('errors.company_not_found', company_short_name=company_short_name)}

            history = self.llm_query_repo.get_history(company, user_identifier)
            if not history:
                return {'message': 'empty history', 'history': []}

            history_list = [query.to_dict() for query in history]
            return {'message': 'history loaded ok', 'history': history_list}

        except Exception as e:
            return {'error': str(e)}