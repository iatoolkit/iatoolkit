# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


import logging
import json
import time
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
    #: The most the history may take, whatever the model's window. Every turn
    #: (and every round of its tool loop) sends the whole history, so a
    #: million-token window filled on each call is a cost nobody chose: seen in
    #: production, three calls of 393k tokens for one question. A company may
    #: set its own with `llm.max_context_tokens`.
    DEFAULT_MAX_CONTEXT_TOKENS = 200000

    #: Share of the budget at which a finished turn asks for a background
    #: compaction, and at which the next turn compacts in line because the
    #: background one did not land in time (BL-009, Fase E).
    COMPACTION_TRIGGER_SHARE = 0.70
    INLINE_COMPACTION_SHARE = 0.95
    #: Parts an in-line compaction may summarize: one, the person is waiting.
    INLINE_COMPACTION_MAX_CHUNKS = 1
    #: How long a turn waits for a compaction that is writing the history.
    HISTORY_LOCK_WAIT_SECONDS = 2.0
    HISTORY_LOCK_TTL_SECONDS = 30
    #: The stored history never grows past this many budgets. Only the copy sent
    #: to the model used to be trimmed, so a conversation that was never
    #: compacted kept every turn in the session (829k tokens seen on a 400k
    #: budget). Two budgets leave the background compaction room to summarize
    #: what is over one; past them, the oldest turns go.
    STORED_HISTORY_MAX_BUDGETS = 2

    #: Marks the message that holds the summary of the compacted turns. It goes
    #: to the model as it is, so it also tells the model what the text is.
    SUMMARY_PREFIX = "[Summary of the earlier conversation]"

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
        # Resolved on first use: the compaction service needs this one.
        self._compaction_service = None
        self._compaction_trigger = None

    @property
    def compaction_service(self):
        if self._compaction_service is None:
            from iatoolkit import current_iatoolkit
            from iatoolkit.services.history_compaction_service import HistoryCompactionService

            self._compaction_service = current_iatoolkit().get_injector().get(HistoryCompactionService)
        return self._compaction_service

    @compaction_service.setter
    def compaction_service(self, service):
        self._compaction_service = service

    @property
    def compaction_trigger(self):
        if self._compaction_trigger is None:
            from iatoolkit import current_iatoolkit
            from iatoolkit.common.interfaces.history_compaction_trigger import HistoryCompactionTrigger

            self._compaction_trigger = current_iatoolkit().get_injector().get(HistoryCompactionTrigger)
        return self._compaction_trigger

    @compaction_trigger.setter
    def compaction_trigger(self, trigger):
        self._compaction_trigger = trigger

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
        budget = self.context_budget_tokens(handle.company_short_name, model)
        if not ignore_history:
            self._compact_in_line_if_needed(handle.company_short_name, handle.user_identifier, model,
                                            user_turn_prompt, budget)
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

        self._trim_context_history(context_history, budget)

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

        # A compaction writing the history meanwhile would be overwritten by the
        # read-modify-write below. Waited for briefly; if it never frees, the turn
        # is saved anyway: the compaction is what gets lost, never the turn.
        lock_key = self.history_lock_key(company_short_name, user_identifier, model)
        locked = self.acquire_history_lock(lock_key, wait_seconds=self.HISTORY_LOCK_WAIT_SECONDS)
        try:
            self._append_turn(company_short_name, user_identifier, model, user_turn_prompt, response)
        finally:
            if locked:
                self.release_history_lock(lock_key)

        self._record_context_size(company_short_name, user_identifier, model, response)

    def _append_turn(self, company_short_name: str, user_identifier: str, model: Optional[str],
                     user_turn_prompt: str, response: Dict[str, Any]):
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

        self._cap_stored_history(company_short_name, model, context_history)

        self.session_context.save_context_history(
            company_short_name,
            user_identifier,
            context_history,
            model=model)

    # ------------------------------------------------------------------
    # Compaction (BL-009, Fase E)
    # ------------------------------------------------------------------

    def _record_context_size(self, company_short_name: str, user_identifier: str, model: Optional[str],
                             response: Dict[str, Any]):
        """Keeps the context size the provider measured, and asks for a compaction past the threshold."""
        stats = response.get("stats") if isinstance(response, dict) else None
        context_tokens = self._positive_int((stats or {}).get("context_tokens"))
        if not context_tokens:
            return
        try:
            self.session_context.save_context_tokens(company_short_name, user_identifier, context_tokens, model=model)
            budget = self.context_budget_tokens(company_short_name, model)
            if context_tokens >= budget * self.COMPACTION_TRIGGER_SHARE:
                self.compaction_trigger.trigger(company_short_name, user_identifier, model)
        except Exception as e:
            # A compaction that is not asked for now is asked for on the next turn.
            logging.warning(f"Could not request the history compaction of {company_short_name}/{user_identifier}: {e}")

    def _compact_in_line_if_needed(self, company_short_name: str, user_identifier: str, model: Optional[str],
                                   user_turn_prompt: str, budget: int):
        """Handles a turn that would not fit because the background compaction did not land in time.

        With workers, the turn asks for the compaction again and goes out
        trimmed: a summary takes one to three minutes (seen in production), and
        the request would die long before (gunicorn's timeout is 60s). Only an
        installation without workers compacts in line, since nothing else ever
        would.
        """
        try:
            measured = self.session_context.get_context_tokens(company_short_name, user_identifier, model=model)
            if not measured:
                return
            estimated = measured + self.llm_client.count_tokens(user_turn_prompt or "")
            if estimated < budget * self.INLINE_COMPACTION_SHARE:
                return
            if self.compaction_trigger.trigger(company_short_name, user_identifier, model):
                return
            result = self.compaction_service.compact(
                company_short_name, user_identifier, model,
                max_chunks=self.INLINE_COMPACTION_MAX_CHUNKS,
            )
            logging.info(f"In-line compaction of {company_short_name}/{user_identifier}: {result}")
        except Exception as e:
            # The trim that follows still keeps the request inside the window.
            logging.warning(f"In-line history compaction failed for {company_short_name}/{user_identifier}: {e}")

    @staticmethod
    def history_lock_key(company_short_name: str, user_identifier: str, model: Optional[str]) -> str:
        return f"lock:history:{company_short_name}/{user_identifier}/{model or ''}"

    def acquire_history_lock(self, lock_key: str, wait_seconds: float = 0.0) -> bool:
        deadline = time.monotonic() + max(wait_seconds, 0.0)
        while True:
            if self.session_context.acquire_lock(lock_key, expire_seconds=self.HISTORY_LOCK_TTL_SECONDS):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def release_history_lock(self, lock_key: str):
        self.session_context.release_lock(lock_key)

    @classmethod
    def summary_message(cls, summary: str) -> dict:
        return {"role": "user", "content": f"{cls.SUMMARY_PREFIX}\n\n{str(summary or '').strip()}"}

    @classmethod
    def is_summary_message(cls, message: Any) -> bool:
        return (
            isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(message.get("content"), str)
            and message["content"].startswith(cls.SUMMARY_PREFIX)
        )

    @classmethod
    def summary_text(cls, message: Any) -> str:
        if not cls.is_summary_message(message):
            return ""
        return message["content"][len(cls.SUMMARY_PREFIX):].strip()

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
        if context_window:
            max_output = self._positive_int(model_config.get("max_output_tokens")) or 0
            reserve = min(max_output, self.MAX_OUTPUT_RESERVE_TOKENS)
            budget = max(context_window - reserve, 1)
        else:
            budget = self.DEFAULT_CONTEXT_BUDGET_TOKENS

        # The window is a ceiling, not a target: the cap is a cost decision.
        cap = self._company_context_cap(company_short_name) or self.DEFAULT_MAX_CONTEXT_TOKENS
        return min(budget, cap)

    def _company_context_cap(self, company_short_name: str) -> int:
        """`llm.max_context_tokens` in company.yaml; 0 when not set (the platform default applies)."""
        if self.configuration_service is None:
            return 0
        try:
            llm_config = self.configuration_service.get_configuration(company_short_name, "llm") or {}
        except Exception:
            return 0
        if not isinstance(llm_config, dict):
            return 0
        return self._positive_int(llm_config.get("max_context_tokens"))

    @staticmethod
    def _positive_int(value) -> int:
        if isinstance(value, bool):
            return 0
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0

    @classmethod
    def turn_starts(cls, context_history: list) -> list[int]:
        """Indexes where a turn begins: each user message after the prepared context.

        A compaction summary is not a turn: it stays with the prepared context,
        so trimming never drops it before the turns it is older than.
        """
        return [
            index for index, message in enumerate(context_history)
            if index > 0 and isinstance(message, dict) and message.get("role") == "user"
            and not cls.is_summary_message(message)
        ]

    def _cap_stored_history(self, company_short_name: str, model: Optional[str], context_history: list):
        """Keeps the stored history under STORED_HISTORY_MAX_BUDGETS budgets, whole turns at a time."""
        cap = self.context_budget_tokens(company_short_name, model) * self.STORED_HISTORY_MAX_BUDGETS
        # A cheap upper estimate first (a token is rarely under 3 characters):
        # counting every save with the tokenizer would cost what this saves.
        if len(json.dumps(context_history, default=str)) <= cap * 3:
            return
        self._trim_context_history(context_history, cap, purpose="stored")

    def _trim_context_history(self, context_history: list, budget_tokens: Optional[int] = None,
                              purpose: str = "request"):
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
        initial_tokens = total_tokens
        removed_turns = 0
        removed_messages = 0
        while total_tokens > budget:
            turn_starts = self.turn_starts(context_history)
            if len(turn_starts) < 2:
                break  # only the current turn is left after the context
            first, second = turn_starts[0], turn_starts[1]
            removed_tokens = sum(token_counts[first:second])
            del context_history[first:second]
            del token_counts[first:second]
            total_tokens -= removed_tokens
            removed_turns += 1
            removed_messages += second - first

        if removed_turns:
            logging.warning(
                f"History ({purpose}) over the budget of {budget} tokens: removed the {removed_turns} "
                f"oldest turns ({removed_messages} messages), {initial_tokens} -> {total_tokens} tokens."
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
