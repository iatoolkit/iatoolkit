# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.tool_service import ToolService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.context_builder_service import ContextBuilderService
from iatoolkit.services.attachment_policy_service import AttachmentPolicyService
from iatoolkit.common.model_registry import ModelRegistry
from injector import inject
import logging
from typing import Optional, Callable
import time
import json
import re
from dataclasses import dataclass


@dataclass
class HistoryHandle:
    """Encapsulates the state needed to manage history for a single turn."""
    company_short_name: str
    user_identifier: str
    type: str
    model: str | None = None
    request_params: dict = None


class QueryService:
    _tool_selector_hook: Callable | None = None

    @inject
    def __init__(self,
                 dispatcher: Dispatcher,
                 tool_service: ToolService,
                 llm_client: llmClient,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService,
                 session_context: UserSessionContextService,
                 configuration_service: ConfigurationService,
                 history_manager: HistoryManagerService,
                 model_registry: ModelRegistry,
                 context_builder: ContextBuilderService,
                 attachment_policy_service: AttachmentPolicyService | None = None,
                 ):
        self.profile_repo = profile_repo
        self.tool_service = tool_service
        self.i18n_service = i18n_service
        self.dispatcher = dispatcher
        self.session_context = session_context
        self.configuration_service = configuration_service
        self.llm_client = llm_client
        self.history_manager = history_manager
        self.model_registry = model_registry
        self.context_builder = context_builder
        self.attachment_policy_service = attachment_policy_service

    @classmethod
    def register_tool_selector_hook(cls, hook: Callable | None):
        """Registers an optional hook that can reduce the tools list before LLM invocation."""
        cls._tool_selector_hook = hook

    @classmethod
    def clear_tool_selector_hook(cls):
        cls._tool_selector_hook = None

    def _select_tools_for_llm(self,
                              company_short_name: str,
                              company,
                              user_identifier: str,
                              question: str,
                              tools: list[dict]) -> list[dict]:
        """
        Optional enterprise hook to reduce candidate tools (top-k routing).
        Fallback behavior is always the full tool list for compatibility.
        """
        hook = type(self)._tool_selector_hook
        if not callable(hook):
            return tools

        try:
            selected_tools = hook(
                company_short_name=company_short_name,
                company=company,
                user_identifier=user_identifier,
                question=question,
                tools=tools,
            )
        except Exception:
            logging.exception(
                "Tool selector hook failed for company '%s'. Falling back to full tool list.",
                company_short_name,
            )
            return tools

        if not isinstance(selected_tools, list) or not selected_tools:
            return tools
        if any(not isinstance(item, dict) or not item.get("name") for item in selected_tools):
            return tools

        return selected_tools

    def _select_tools_for_llm_with_metrics(self,
                                           company_short_name: str,
                                           company,
                                           user_identifier: str,
                                           question: str,
                                           tools: list[dict]) -> tuple[list[dict], dict]:
        started_at = time.time()
        candidate_count = len(tools) if isinstance(tools, list) else 0
        metrics = {
            "candidate_count": candidate_count,
            "selected_count": candidate_count,
            "selection_mode": "all_tools",
            "fallback_reason": "hook_not_registered",
            "selector_latency_ms": 0,
        }

        def _finalize(selected_tools: list[dict], *, reason: str | None, mode: str = "all_tools", hook_metadata: dict | None = None):
            metrics["selected_count"] = len(selected_tools) if isinstance(selected_tools, list) else candidate_count
            metrics["selection_mode"] = mode
            metrics["fallback_reason"] = reason
            metrics["selector_latency_ms"] = max(0, int((time.time() - started_at) * 1000))
            if hook_metadata:
                metrics["hook_metadata"] = hook_metadata
            return selected_tools, metrics

        if not isinstance(tools, list) or not tools:
            return _finalize(tools or [], reason="no_tools")

        hook = type(self)._tool_selector_hook
        if not callable(hook):
            return _finalize(tools, reason="hook_not_registered")

        try:
            hook_response = hook(
                company_short_name=company_short_name,
                company=company,
                user_identifier=user_identifier,
                question=question,
                tools=tools,
            )
        except Exception:
            logging.exception(
                "Tool selector hook failed for company '%s'. Falling back to full tool list.",
                company_short_name,
            )
            return _finalize(tools, reason="hook_error")

        hook_metadata = None
        selected_tools = hook_response
        if isinstance(hook_response, dict):
            selected_tools = hook_response.get("tools")
            hook_metadata_candidate = hook_response.get("metadata")
            if isinstance(hook_metadata_candidate, dict):
                hook_metadata = hook_metadata_candidate

        if not isinstance(selected_tools, list):
            return _finalize(tools, reason="invalid_hook_response", hook_metadata=hook_metadata)
        if not selected_tools:
            return _finalize(tools, reason="empty_selection", hook_metadata=hook_metadata)
        if any(not isinstance(item, dict) or not item.get("name") for item in selected_tools):
            return _finalize(tools, reason="invalid_tool_schema", hook_metadata=hook_metadata)

        return _finalize(selected_tools, reason=None, mode="router_selected", hook_metadata=hook_metadata)

    def _resolve_model(self, company_short_name: str, model: Optional[str]) -> str:
        # Priority: 1. Explicit model -> 2. Company config
        effective_model = model
        if not effective_model:
            llm_config = self.configuration_service.get_configuration(company_short_name, 'llm')
            if llm_config and llm_config.get('model'):
                effective_model = llm_config['model']
        return effective_model

    def _get_history_type(self, model: str) -> str:
        history_type_str = self.model_registry.get_history_type(model)
        if history_type_str == "server_side":
            return HistoryManagerService.TYPE_SERVER_SIDE
        else:
            return HistoryManagerService.TYPE_CLIENT_SIDE

    def _normalize_selected_system_prompt_keys(self, keys) -> list[str]:
        if not isinstance(keys, list):
            return []
        normalized: list[str] = []
        for item in keys:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    normalized.append(candidate)
        return normalized

    def _get_provider(self, model: str) -> str:
        get_provider_fn = getattr(self.model_registry, "get_provider", None)
        if not callable(get_provider_fn):
            return "unknown"
        try:
            provider = get_provider_fn(model)
            return provider or "unknown"
        except Exception:
            return "unknown"

    def _resolve_prompt_output_contract(self, company, prompt_name: str | None) -> dict:
        if not prompt_name:
            return {}
        try:
            contract = self.context_builder.get_prompt_output_contract(company, prompt_name)
            if not isinstance(contract, dict):
                return {}
            schema = contract.get("schema")
            if not isinstance(schema, dict):
                contract["schema"] = None
            contract["schema_mode"] = str(contract.get("schema_mode") or "best_effort").strip().lower()
            contract["response_mode"] = str(contract.get("response_mode") or "chat_compatible").strip().lower()
            raw_attachment_mode = contract.get("attachment_mode")
            raw_attachment_fallback = contract.get("attachment_fallback")
            contract["attachment_mode"] = (
                str(raw_attachment_mode).strip().lower() if raw_attachment_mode is not None else None
            )
            contract["attachment_fallback"] = (
                str(raw_attachment_fallback).strip().lower() if raw_attachment_fallback is not None else None
            )
            contract["provider"] = self._get_provider(contract.get("model") or "")
            return contract
        except Exception as e:
            logging.debug(
                "Could not resolve prompt output contract for '%s' in company '%s': %s",
                prompt_name,
                company.short_name if company else "-",
                e,
            )
            return {}

    def _resolve_company_attachment_defaults(self, company_short_name: str) -> dict:
        if self.attachment_policy_service:
            return self.attachment_policy_service.get_company_default_policy(company_short_name)

        llm_config = self.configuration_service.get_configuration(company_short_name, "llm") or {}
        return {
            "attachment_mode": str(llm_config.get("default_attachment_mode") or "extracted_only").strip().lower(),
            "attachment_fallback": str(llm_config.get("default_attachment_fallback") or "extract").strip().lower(),
        }

    def _resolve_effective_attachment_policy(self, company_short_name: str, prompt_output_contract: dict | None) -> dict:
        prompt_policy = prompt_output_contract or {}
        company_defaults = self._resolve_company_attachment_defaults(company_short_name)
        candidate_mode = prompt_policy.get("attachment_mode") or company_defaults.get("attachment_mode")
        candidate_fallback = prompt_policy.get("attachment_fallback") or company_defaults.get("attachment_fallback")

        if self.attachment_policy_service:
            return {
                "attachment_mode": self.attachment_policy_service.normalize_mode(candidate_mode),
                "attachment_fallback": self.attachment_policy_service.normalize_fallback(candidate_fallback),
            }

        return {
            "attachment_mode": str(candidate_mode or "extracted_only").strip().lower() or "extracted_only",
            "attachment_fallback": str(candidate_fallback or "extract").strip().lower() or "extract",
        }

    def _sanitize_schema_name(self, raw_name: str) -> str:
        candidate = re.sub(r"[^a-zA-Z0-9_]", "_", (raw_name or "").strip())
        candidate = candidate.strip("_")
        if not candidate:
            candidate = "prompt_output_schema"
        return candidate[:64]

    def _build_output_text_schema_payload(self, model: str, contract: dict) -> dict:
        schema = contract.get("schema") if isinstance(contract, dict) else None
        if not isinstance(schema, dict):
            return {}

        provider = self._get_provider(model)
        schema_mode = str(contract.get("schema_mode") or "best_effort").strip().lower()
        if provider in ("openai", "xai"):
            return {
                "format": {
                    "type": "json_schema",
                    "name": self._sanitize_schema_name(contract.get("prompt_name") or "prompt_output"),
                    "schema": schema,
                    "strict": schema_mode == "strict",
                }
            }

        if provider == "gemini":
            # Gemini structured output (native): keep app-side strict validation as source of truth.
            return {
                "response_mime_type": "application/json",
                "response_schema": schema,
            }

        return {}

    def _append_structured_schema_instruction(self, user_turn_prompt: str, contract: dict) -> str:
        schema = contract.get("schema")
        if not isinstance(schema, dict):
            return user_turn_prompt

        schema_json = json.dumps(schema, ensure_ascii=False)
        return (
            f"{user_turn_prompt}\n\n"
            "### OUTPUT CONTRACT (MANDATORY)\n"
            "Return ONLY one valid JSON object matching this schema.\n"
            "Do not include markdown fences, explanations, or extra text.\n"
            "Do NOT use wrapper keys like `answer` or `aditional_data`.\n"
            "Ignore any previous output-format instruction that conflicts with this contract.\n"
            f"Schema: {schema_json}\n"
        )

    def _ensure_valid_history(self, company,
                              user_identifier: str,
                              effective_model: str,
                              question: str,
                              user_turn_prompt: str,
                              ignore_history: bool
                              ) -> tuple[Optional[HistoryHandle], Optional[dict]]:
        """
            Manages the history strategy and rebuilds context if necessary.
            Returns: (HistoryHandle, error_response)
        """
        history_type = self._get_history_type(effective_model)

        # Initialize the handle with base context info
        handle = HistoryHandle(
            company_short_name=company.short_name,
            user_identifier=user_identifier,
            type=history_type,
            model=effective_model
        )

        # pass the handle to populate request_params
        needs_rebuild = self.history_manager.populate_request_params(
            handle, user_turn_prompt, ignore_history
        )

        if needs_rebuild:
            logging.warning(f"No valid history for {company.short_name}/{user_identifier}. Rebuilding context...")

            # try to rebuild the context
            self.prepare_context(
                company_short_name=company.short_name,
                user_identifier=user_identifier,
                query_text=question,
            )
            self.set_context_for_llm(company_short_name=company.short_name, user_identifier=user_identifier,
                                     model=effective_model)

            # Retry populating params with the same handle
            needs_rebuild = self.history_manager.populate_request_params(
                handle, user_turn_prompt, ignore_history
            )

            if needs_rebuild:
                error_key = 'errors.services.context_rebuild_failed'
                error_message = self.i18n_service.t(error_key, company_short_name=company.short_name,
                                                    user_identifier=user_identifier)
                return None, {'error': True, "error_message": error_message}

        return handle, None

    def init_context(self, company_short_name: str,
                     user_identifier: str,
                     model: str = None) -> dict:
        """
        Forces a context rebuild for a given user and (optionally) model.

        - Clears LLM-related context for the resolved model.
        - Regenerates the static company/user context.
        - Sends the context to the LLM for that model.
        """

        # 1. Resolve the effective model for this user/company
        effective_model = self._resolve_model(company_short_name, model)

        # 2. Clear only the LLM-related context for this model
        self.session_context.clear_all_context(company_short_name, user_identifier, model=effective_model)
        logging.info(
            f"Context for {company_short_name}/{user_identifier} "
            f"(model={effective_model}) has been cleared."
        )

        # 3. Static LLM context is now clean, we can prepare it again (model-agnostic)
        self.prepare_context(
            company_short_name=company_short_name,
            user_identifier=user_identifier
        )

        # 4. Communicate the new context to the specific LLM model
        response = self.set_context_for_llm(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            model=effective_model
        )

        return response

    def prepare_context(
        self,
        company_short_name: str,
        user_identifier: str,
        query_text: str | None = None,
    ) -> dict:
        """
        Prepares the static context (Company + User Profile + Tools) and checks if it needs to be rebuilt.
        Delegates construction to ContextBuilderService.
        """
        if not user_identifier:
            return {'rebuild_needed': True, 'error': 'Invalid user identifier'}

        # Delegate context construction to the builder
        context_build_result = self.context_builder.build_system_context(
            company_short_name, user_identifier, query_text=query_text
        )
        if isinstance(context_build_result, tuple) and len(context_build_result) == 3:
            final_system_context, user_profile, selected_system_prompt_keys = context_build_result
        else:
            final_system_context, user_profile = context_build_result
            selected_system_prompt_keys = []

        if not final_system_context:
            logging.error(f"Failed to build system context for {company_short_name}")
            return {'rebuild_needed': True}

        # save the user information in the session context
        # it's needed for the jinja predefined prompts (filtering)
        self.session_context.save_profile_data(company_short_name, user_identifier, user_profile)
        self.session_context.save_selected_system_prompt_keys(
            company_short_name,
            user_identifier,
            selected_system_prompt_keys if isinstance(selected_system_prompt_keys, list) else [],
        )

        # calculate the context version using the builder
        current_version = self.context_builder.compute_context_version(final_system_context)

        # get the current version from the session cache
        try:
            prev_version = self.session_context.get_context_version(company_short_name, user_identifier)
        except Exception:
            prev_version = None

        # Determine if we need to persist the prepared context again.
        rebuild_is_needed = (prev_version != current_version)

        # Save the prepared context and its version for `set_context_for_llm` to use.
        self.session_context.save_prepared_context(company_short_name,
                                                   user_identifier,
                                                   final_system_context,
                                                   current_version)
        return {'rebuild_needed': rebuild_is_needed}

    def set_context_for_llm(self,
                            company_short_name: str,
                            user_identifier: str,
                            model: str = ''):
        """
        Takes a pre-built static context and sends it to the LLM for the given model.
        Also initializes the model-specific history through HistoryManagerService.
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            logging.error(f"Company not found: {company_short_name} in set_context_for_llm")
            return

        # --- Model Resolution ---
        effective_model = self._resolve_model(company_short_name, model)

        # Lock per (company, user, model) to avoid concurrent rebuilds for the same model
        lock_key = f"lock:context:{company_short_name}/{user_identifier}/{effective_model}"
        if not self.session_context.acquire_lock(lock_key, expire_seconds=60):
            logging.warning(
                f"try to rebuild context for user {user_identifier} while is still in process, ignored.")
            return

        try:
            start_time = time.time()

            # get the prepared context and version from the session cache
            prepared_context, version_to_save = self.session_context.get_and_clear_prepared_context(company_short_name,
                                                                                                    user_identifier)
            if not prepared_context:
                return

            logging.info(
                f"sending context to LLM model {effective_model} for: {company_short_name}/{user_identifier}...")

            # --- Use Strategy Pattern for History/Context Initialization ---
            history_type = self._get_history_type(effective_model)
            response_data = self.history_manager.initialize_context(
                company_short_name, user_identifier, history_type, prepared_context, company, effective_model
            )

            if version_to_save:
                self.session_context.save_context_version(company_short_name, user_identifier, version_to_save)

            logging.info(
                f"Context for: {company_short_name}/{user_identifier} settled in {int(time.time() - start_time)} sec.")

            # Return data (e.g., response_id) if the manager generated any
            return response_data

        except Exception as e:
            logging.exception(f"Error in finalize_context_rebuild for {company_short_name}: {e}")
            raise e
        finally:
            # release the lock
            self.session_context.release_lock(lock_key)

    def llm_query(self,
                  company_short_name: str,
                  user_identifier: str,
                  model: Optional[str] = None,
                  prompt_name: str = None,
                  question: str = '',
                  client_data: dict = {},
                  task_id: Optional[int] = None,
                  ignore_history: bool = False,
                  files: list = []
                  ) -> dict:
        try:
            company = self.profile_repo.get_company_by_short_name(short_name=company_short_name)
            if not company:
                return {"error": True,
                        "error_message": self.i18n_service.t('errors.company_not_found',
                                                             company_short_name=company_short_name)}

            if not prompt_name and not question:
                return {"error": True,
                        "error_message": self.i18n_service.t('services.start_query')}

            # --- Model Resolution ---
            effective_model = self._resolve_model(company_short_name, model)

            # output contract
            prompt_output_contract = self._resolve_prompt_output_contract(company, prompt_name)
            output_schema = self._build_output_text_schema_payload(effective_model, prompt_output_contract)

            # attachment policy
            provider = self._get_provider(effective_model)
            effective_attachment_policy = self._resolve_effective_attachment_policy(
                company_short_name=company_short_name,
                prompt_output_contract=prompt_output_contract,
            )

            attachment_plan = {
                "files_for_context": files or [],
                "native_attachments": [],
                "errors": [],
                "policy": effective_attachment_policy,
                "capabilities": {},
                "stats": {
                    "total_files": len(files or []),
                    "native_sent_count": 0,
                    "extract_candidates": len(files or []),
                    "fallback_to_extract": 0,
                    "errors": 0,
                },
            }
            if self.attachment_policy_service:
                attachment_plan = self.attachment_policy_service.build_attachment_plan(
                    company_short_name=company_short_name,
                    provider=provider,
                    files=files or [],
                    policy=effective_attachment_policy,
                )

            if attachment_plan.get("errors"):
                attachment_errors = "; ".join(attachment_plan["errors"])
                logging.warning(
                    "Attachment policy rejected files for company '%s' prompt '%s': %s",
                    company_short_name,
                    prompt_name,
                    attachment_errors,
                )
                return {
                    "error": True,
                    "error_message": f"No se pudieron procesar los archivos adjuntos: {attachment_errors}",
                }

            # --- Build User-Facing Prompt (Delegated to Builder) ---
            user_turn_prompt, effective_question, images = self.context_builder.build_user_turn_prompt(
                company=company,
                user_identifier=user_identifier,
                client_data=client_data,
                files=attachment_plan.get("files_for_context", []),
                prompt_name=prompt_name,
                question=question
            )

            if prompt_output_contract.get("schema") and (
                not output_schema or provider == "gemini"
            ):
                user_turn_prompt = self._append_structured_schema_instruction(
                    user_turn_prompt=user_turn_prompt,
                    contract=prompt_output_contract,
                )

            # --- History Management (Strategy Pattern) ---
            history_handle, error_response = self._ensure_valid_history(
                company=company,
                user_identifier=user_identifier,
                effective_model=effective_model,
                question=effective_question,
                user_turn_prompt=user_turn_prompt,
                ignore_history=ignore_history
            )
            if error_response:
                return error_response

            # get the tools availables for this company
            tools = self.tool_service.get_tools_for_llm(company)

            tools, tool_router_metrics = self._select_tools_for_llm_with_metrics(
                company_short_name=company_short_name,
                company=company,
                user_identifier=user_identifier,
                question=effective_question,
                tools=tools,
            )
            selected_system_prompt_keys = []
            try:
                selected_system_prompt_keys = self._normalize_selected_system_prompt_keys(
                    self.session_context.get_selected_system_prompt_keys(
                        company_short_name,
                        user_identifier,
                    )
                )
            except Exception as e:
                logging.debug(
                    "Could not read selected system prompt keys from session telemetry cache (company='%s'): %s",
                    company_short_name,
                    e,
                )

            if not selected_system_prompt_keys:
                try:
                    selected_system_prompt_keys = self._normalize_selected_system_prompt_keys(
                        self.context_builder.get_selected_system_prompt_keys(
                            company,
                            query_text=effective_question,
                        )
                    )
                    self.session_context.save_selected_system_prompt_keys(
                        company_short_name,
                        user_identifier,
                        selected_system_prompt_keys,
                    )
                except Exception as e:
                    logging.debug(
                        "Could not resolve selected system prompt keys for telemetry (company='%s'): %s",
                        company_short_name,
                        e,
                    )
                    selected_system_prompt_keys = []

            if selected_system_prompt_keys:
                tool_router_metrics = dict(tool_router_metrics or {})
                tool_router_metrics["selected_system_prompt_keys"] = selected_system_prompt_keys

            execution_metadata = {"tool_router": tool_router_metrics}
            if prompt_output_contract.get("schema"):
                execution_metadata["structured_output"] = {
                    "enabled": True,
                    "schema_mode": prompt_output_contract.get("schema_mode", "best_effort"),
                    "response_mode": prompt_output_contract.get("response_mode", "chat_compatible"),
                    "provider": provider,
                }
            execution_metadata["attachments"] = {
                "policy": attachment_plan.get("policy", {}),
                "stats": attachment_plan.get("stats", {}),
                "provider": provider,
                "company_defaults": self._resolve_company_attachment_defaults(company_short_name),
            }

            # Safely extract parameters for invoke using the handle
            # The handle is guaranteed to have request_params populated if no error returned
            previous_response_id = history_handle.request_params.get('previous_response_id')
            context_history = history_handle.request_params.get('context_history')

            # Now send the instructions to the llm
            response = self.llm_client.invoke(
                company=company,
                user_identifier=user_identifier,
                model=effective_model,
                task_id=task_id,
                previous_response_id=previous_response_id,
                context_history=context_history,
                question=effective_question,
                context=user_turn_prompt,
                tools=tools,
                text=output_schema,
                images=images,
                attachments=attachment_plan.get("native_attachments", []),
                execution_metadata=execution_metadata,
                response_contract=prompt_output_contract if prompt_output_contract.get("schema") else None,
            )

            if not response.get('valid_response'):
                response['error'] = True

            # save history using the manager passing the handle
            self.history_manager.update_history(
                history_handle, user_turn_prompt, response
            )

            return response
        except Exception as e:
            logging.exception(e)
            return {'error': True, "error_message": f"{str(e)}"}
