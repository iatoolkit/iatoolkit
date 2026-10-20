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
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from injector import inject


class HistoryManagerService:
    """
    Manages conversation history for LLMs.

    IAToolkit owns the history with every provider: the message list lives in the
    user's session and is sent whole on each turn. No provider keeps conversation
    state for us (no `previous_response_id`, OpenAI runs with `store=False`), which
    is what lets the history be trimmed or compacted and lets a conversation move
    between providers.

    Also reads the persisted chat history for the history popup.
    """
    TYPE_CLIENT_SIDE = 'client_side'

    #: The budget when the model's context window is unknown (no `models-sync`
    #: has seen it, or a company.yaml model that does not declare it). It is what
    #: every model used before windows were stored.
    DEFAULT_CONTEXT_BUDGET_TOKENS = 400000
    #: The most of the window kept free for the answer. A reasoning model may
    #: declare 128k of output; reserving all of it would waste a quarter of a
    #: 400k window on an answer that is almost never that long.
    MAX_OUTPUT_RESERVE_TOKENS = 32000

    @inject
    def __init__(self,
                 session_context: UserSessionContextService,
                 i18n: I18nService,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 llm_client: Optional[llmClient] = None,
                 configuration_service: Optional[ConfigurationService] = None):
        self.session_context = session_context
        self.i18n = i18n
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.llm_client = llm_client
        self.configuration_service = configuration_service

    def initialize_context(self,
                           company_short_name: str,
                           user_identifier: str,
                           prepared_context: str,
                           model: str) -> Dict[str, Any]:
        """Starts a new conversation history with the prepared context as its first message.

        Nothing reaches the model here: the context travels with the first turn.
        """
        self.session_context.clear_llm_history(company_short_name, user_identifier, model=model)
        context_history = [{"role": "user", "content": prepared_context}]
        self.session_context.save_context_history(company_short_name, user_identifier, context_history, model=model)
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
        context_history = self.session_context.get_context_history(
            handle.company_short_name, handle.user_identifier, model=model) or []

        if not context_history:
            handle.request_params = {}
            return True  # Needs rebuild

        if ignore_history and len(context_history) > 1:
            # Keep only the prepared context
            context_history = [context_history[0]]

        # Append the current user turn to the context sent to the API
        context_history.append({"role": "user", "content": user_turn_prompt})

        self._trim_context_history(
            context_history,
            self.context_budget_tokens(handle.company_short_name, model),
        )

        handle.request_params = {'context_history': context_history}
        return False

    def update_history(self,
                       history_handle: Any,
                       user_turn_prompt: str,
                       response: Dict[str, Any]):
        """Saves the history after a successful LLM call."""
        company_short_name = history_handle.company_short_name
        user_identifier = history_handle.user_identifier
        model = getattr(history_handle, "model", None)

        # get the history for this company/user/model
        context_history = self.session_context.get_context_history(
            company_short_name,
            user_identifier,
            model=model) or []

        # Ensure the user prompt is recorded if not already.
        # We check content equality to handle the case where the previous message was
        # also 'user' (e.g., the prepared context) but different content.
        last_content = context_history[-1].get("content") if context_history else None

        if last_content != user_turn_prompt:
            context_history.append({"role": "user", "content": user_turn_prompt})

        history_messages = response.get("history_messages")
        if isinstance(history_messages, list) and history_messages:
            context_history.extend(history_messages)
        elif response.get('answer'):
            context_history.append({"role": "assistant", "content": response.get('answer', '')})

        self.session_context.save_context_history(
            company_short_name,
            user_identifier,
            context_history,
            model=model)

    def context_budget_tokens(self, company_short_name: str, model: Optional[str]) -> int:
        """How many tokens the history may take for this model: its window minus room for the answer."""
        model_config = {}
        if self.configuration_service is not None and model:
            try:
                model_config = self.configuration_service.get_llm_model_config(company_short_name, model) or {}
            except Exception as e:
                logging.warning(f"Could not read the model configuration of '{model}': {e}")
                model_config = {}

        context_window = self._positive_int(model_config.get("context_window"))
        if not context_window:
            return self.DEFAULT_CONTEXT_BUDGET_TOKENS
        max_output = self._positive_int(model_config.get("max_output_tokens")) or 0
        reserve = min(max_output, self.MAX_OUTPUT_RESERVE_TOKENS)
        return max(context_window - reserve, 1)

    @staticmethod
    def _positive_int(value) -> int:
        if isinstance(value, bool):
            return 0
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0

    @staticmethod
    def _turn_starts(context_history: list) -> list[int]:
        """Indexes where a turn begins: each user message after the prepared context."""
        return [
            index for index, message in enumerate(context_history)
            if index > 0 and isinstance(message, dict) and message.get("role") == "user"
        ]

    def _trim_context_history(self, context_history: list, budget_tokens: Optional[int] = None):
        """Drops whole turns, oldest first, until the history fits the budget.

        A turn is a user message and everything up to the next one: the
        assistant's tool calls, their outputs and the answer. Dropping message by
        message could remove a tool call and leave its output behind, a history
        every provider rejects. The prepared context and the current turn are
        never dropped.
        """
        if not context_history or len(context_history) <= 1:
            return
        budget = budget_tokens or self.DEFAULT_CONTEXT_BUDGET_TOKENS
        try:
            token_counts = [self.llm_client.count_tokens(json.dumps(message, default=str)) for message in context_history]
        except Exception as e:
            logging.error(f"Error counting tokens for history: {e}.")
            return

        total_tokens = sum(token_counts)
        while total_tokens > budget:
            turn_starts = self._turn_starts(context_history)
            if len(turn_starts) < 2:
                break  # only the current turn is left after the context
            first, second = turn_starts[0], turn_starts[1]
            removed_tokens = sum(token_counts[first:second])
            del context_history[first:second]
            del token_counts[first:second]
            total_tokens -= removed_tokens
            logging.warning(
                f"History tokens exceed the budget of {budget}. Removed the oldest turn "
                f"({second - first} messages). New total: {total_tokens} tokens."
            )

    # --- this is for the history popup in the chat page
    def get_full_history(self, company_short_name: str, user_identifier: str, limit: int = 100) -> dict:
        """Retrieves the full persisted history from the database."""
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {"error": self.i18n.t('errors.company_not_found', company_short_name=company_short_name)}

            history = self.llm_query_repo.get_history(company, user_identifier, limit=limit)
            if not history:
                return {'message': 'empty history', 'history': []}

            history_list = [query.to_dict() for query in history]
            return {'message': 'history loaded ok', 'history': history_list}

        except Exception as e:
            return {'error': str(e)}
