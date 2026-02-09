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
from iatoolkit.common.model_registry import ModelRegistry
from injector import inject
import logging
from typing import Optional
import time
from dataclasses import dataclass
from iatoolkit.common.util import measure_time


@dataclass
class HistoryHandle:
    """Encapsulates the state needed to manage history for a single turn."""
    company_short_name: str
    user_identifier: str
    type: str
    model: str | None = None
    request_params: dict = None


class QueryService:
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
                 context_builder: ContextBuilderService
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

    def _ensure_valid_history(self, company,
                              user_identifier: str,
                              effective_model: str,
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
            self.prepare_context(company_short_name=company.short_name, user_identifier=user_identifier)
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

    def prepare_context(self, company_short_name: str, user_identifier: str) -> dict:
        """
        Prepares the static context (Company + User Profile + Tools) and checks if it needs to be rebuilt.
        Delegates construction to ContextBuilderService.
        """
        if not user_identifier:
            return {'rebuild_needed': True, 'error': 'Invalid user identifier'}

        # Delegate context construction to the builder
        final_system_context, user_profile = self.context_builder.build_system_context(
            company_short_name, user_identifier
        )

        if not final_system_context:
            logging.error(f"Failed to build system context for {company_short_name}")
            return {'rebuild_needed': True}

        # save the user information in the session context
        # it's needed for the jinja predefined prompts (filtering)
        self.session_context.save_profile_data(company_short_name, user_identifier, user_profile)

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

    def _filter_tools_for_prompt(self, tools: list[dict], prompt_name: Optional[str]) -> list[dict]:
        """
        Filtra las herramientas según el prompt para optimizar el payload al LLM.
        Algunos prompts solo necesitan herramientas específicas.
        
        Args:
            tools: Lista completa de herramientas disponibles
            prompt_name: Nombre del prompt activo
            
        Returns:
            Lista filtrada de herramientas
        """
        if not prompt_name:
            return tools
        
        # Mapeo de prompts a herramientas requeridas
        prompt_tool_mapping = {
            "risk_faces": ["identity_risk"],  # Solo necesita identity_risk
            # Agregar más mapeos aquí en el futuro
        }
        
        required_tools = prompt_tool_mapping.get(prompt_name.lower())
        if not required_tools:
            # Si el prompt no está en el mapeo, retornar todas las tools
            return tools
        
        # Filtrar tools para incluir solo las requeridas
        filtered_tools = [
            tool for tool in tools 
            if tool.get("name") in required_tools
        ]
        
        if filtered_tools:
            logging.info(f"[TOOL_FILTER] Prompt '{prompt_name}' detected: filtered {len(tools)} tools to {len(filtered_tools)} tools: {required_tools}")
        else:
            logging.warning(f"[TOOL_FILTER] Prompt '{prompt_name}' required tools {required_tools} but none found. Using all tools.")
            return tools
        
        return filtered_tools

    @measure_time
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

            # --- Build User-Facing Prompt (Delegated to Builder) ---
            user_turn_prompt, effective_question, images = self.context_builder.build_user_turn_prompt(
                company=company,
                user_identifier=user_identifier,
                client_data=client_data,
                files=files,
                prompt_name=prompt_name,
                question=question
            )

            # --- History Management (Strategy Pattern) ---
            history_handle, error_response = self._ensure_valid_history(
                company=company,
                user_identifier=user_identifier,
                effective_model=effective_model,
                user_turn_prompt=user_turn_prompt,
                ignore_history=ignore_history
            )
            if error_response:
                return error_response

            # get the tools availables for this company
            tools = self.tool_service.get_tools_for_llm(company)

            # Filter tools based on prompt to optimize LLM payload
            tools = self._filter_tools_for_prompt(tools, prompt_name)

            # openai structured output instructions
            output_schema = {}

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