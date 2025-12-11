# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.tool_service import ToolService
from iatoolkit.services.document_service import DocumentService
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.common.model_registry import ModelRegistry
from iatoolkit.common.util import Utility
from injector import inject
import base64
import logging
from typing import Optional
import json
import time
import hashlib
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
    @inject
    def __init__(self,
                 dispatcher: Dispatcher,
                 tool_service: ToolService,
                 llm_client: llmClient,
                 profile_service: ProfileService,
                 company_context_service: CompanyContextService,
                 document_service: DocumentService,
                 profile_repo: ProfileRepo,
                 prompt_service: PromptService,
                 i18n_service: I18nService,
                 session_context: UserSessionContextService,
                 configuration_service: ConfigurationService,
                 history_manager: HistoryManagerService,
                 util: Utility,
                 model_registry: ModelRegistry
                 ):
        self.profile_service = profile_service
        self.company_context_service = company_context_service
        self.document_service = document_service
        self.profile_repo = profile_repo
        self.tool_service = tool_service
        self.prompt_service = prompt_service
        self.i18n_service = i18n_service
        self.util = util
        self.dispatcher = dispatcher
        self.session_context = session_context
        self.configuration_service = configuration_service
        self.llm_client = llm_client
        self.history_manager = history_manager
        self.model_registry = model_registry


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


    def _build_user_facing_prompt(self, company, user_identifier: str,
                                  client_data: dict, files: list,
                                  prompt_name: Optional[str], question: str) -> str:
        # get the user profile data from the session context
        user_profile = self.profile_service.get_profile_by_identifier(company.short_name, user_identifier)

        # combine client_data with user_profile
        final_client_data = (user_profile or {}).copy()
        final_client_data.update(client_data)

        # Load attached files into the context
        files_context = self.load_files_for_context(files)

        # Initialize prompt_content. It will be an empty string for direct questions.
        main_prompt = ""
        # We use a local variable for the question to avoid modifying the argument reference if it were mutable,
        # although strings are immutable, this keeps the logic clean regarding what 'question' means in each context.
        effective_question = question

        if prompt_name:
            question_dict = {'prompt': prompt_name, 'data': final_client_data}
            effective_question = json.dumps(question_dict)
            prompt_content = self.prompt_service.get_prompt_content(company, prompt_name)

            # Render the user requested prompt
            main_prompt = self.util.render_prompt_from_string(
                template_string=prompt_content,
                question=effective_question,
                client_data=final_client_data,
                user_identifier=user_identifier,
                company=company,
            )

        # This is the final user-facing prompt for this specific turn
        user_turn_prompt = f"{main_prompt}\n{files_context}"
        if not prompt_name:
            user_turn_prompt += f"\n### La pregunta que debes responder es: {effective_question}"
        else:
            user_turn_prompt += f'\n### Contexto Adicional: El usuario ha aportado este contexto puede ayudar: {effective_question}'

        return user_turn_prompt, effective_question

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

    def _build_context_and_profile(self, company_short_name: str, user_identifier: str) -> tuple:
        # this method read the user/company context from the database and renders the system prompt
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, None

        # Get the user profile from the single source of truth.
        user_profile = self.profile_service.get_profile_by_identifier(company_short_name, user_identifier)

        # render the iatoolkit main system prompt with the company/user information
        system_prompt_template = self.prompt_service.get_system_prompt()
        rendered_system_prompt = self.util.render_prompt_from_string(
            template_string=system_prompt_template,
            question=None,
            client_data=user_profile,
            company=company,
            service_list=self.tool_service.get_tools_for_llm(company)
        )

        # get the company context: schemas, database models, .md files
        company_specific_context = self.company_context_service.get_company_context(company_short_name)

        # merge context: company + user
        final_system_context = f"{company_specific_context}\n{rendered_system_prompt}"

        return final_system_context, user_profile


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
        self.session_context.clear_all_context(company_short_name, user_identifier,model=effective_model)
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
        # prepare the context and decide if it needs to be rebuilt
        # save the generated context in the session context for later use
        if not user_identifier:
            return {'rebuild_needed': True, 'error': 'Invalid user identifier'}

        # create the company/user context and compute its version
        final_system_context, user_profile = self._build_context_and_profile(
            company_short_name, user_identifier)

        # save the user information in the session context
        # it's needed for the jinja predefined prompts (filtering)
        self.session_context.save_profile_data(company_short_name, user_identifier, user_profile)

        # calculate the context version
        current_version = self._compute_context_version_from_string(final_system_context)

        # get the current version from the session cache
        try:
            prev_version = self.session_context.get_context_version(company_short_name, user_identifier)
        except Exception:
            prev_version = None

        # Determine if we need to persist the prepared context again.
        # If versions match, we assume the artifact is likely safe, but forcing a save
        # on version mismatch ensures data consistency.
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
            prepared_context, version_to_save = self.session_context.get_and_clear_prepared_context(company_short_name,                                                                                                    user_identifier)
            if not prepared_context:
                return

            logging.info(f"sending context to LLM model {effective_model} for: {company_short_name}/{user_identifier}...")

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
                  ignore_history: bool = False,
                  files: list = []
                  ) -> dict:
        try:
            company = self.profile_repo.get_company_by_short_name(short_name=company_short_name)
            if not company:
                return {"error": True,
                        "error_message": self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name)}

            if not prompt_name and not question:
                return {"error": True,
                        "error_message": self.i18n_service.t('services.start_query')}

            # --- Model Resolution ---
            effective_model = self._resolve_model(company_short_name, model)

            # --- Build User-Facing Prompt ---
            user_turn_prompt, effective_question = self._build_user_facing_prompt(
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
                previous_response_id=previous_response_id,
                context_history=context_history,
                question=effective_question,
                context=user_turn_prompt,
                tools=tools,
                text=output_schema
            )

            if not response.get('valid_response'):
                response['error'] = True
            else:
                # save history using the manager passing the handle
                self.history_manager.update_history(
                    history_handle, user_turn_prompt, response
                )

            return response
        except Exception as e:
            logging.exception(e)
            return {'error': True, "error_message": f"{str(e)}"}

    def _compute_context_version_from_string(self, final_system_context: str) -> str:
        # returns a hash of the context string
        try:
            return hashlib.sha256(final_system_context.encode("utf-8")).hexdigest()
        except Exception:
            return "unknown"


    def load_files_for_context(self, files: list) -> str:
        """
        Processes a list of attached files, decodes their content,
        and formats them into a string context for the LLM.
        """
        if not files:
            return ''

        context = f"""
            A continuación encontraras una lista de documentos adjuntos
            enviados por el usuario que hace la pregunta, 
            en total son: {len(files)} documentos adjuntos
            """
        for document in files:
            # Support both 'file_id' and 'filename' for robustness
            filename = document.get('file_id') or document.get('filename') or document.get('name')
            if not filename:
                context += "\n<error>Documento adjunto sin nombre ignorado.</error>\n"
                continue

            # Support both 'base64' and 'content' for robustness
            base64_content = document.get('base64') or document.get('content')

            if not base64_content:
                # Handles the case where a file is referenced but no content is provided
                context += f"\n<error>El archivo '{filename}' no fue encontrado y no pudo ser cargado.</error>\n"
                continue

            try:
                # Ensure content is bytes before decoding
                if isinstance(base64_content, str):
                    base64_content = base64_content.encode('utf-8')

                file_content = base64.b64decode(base64_content)
                document_text = self.document_service.file_to_txt(filename, file_content)
                context += f"\n<document name='{filename}'>\n{document_text}\n</document>\n"
            except Exception as e:
                # Catches errors from b64decode or file_to_txt
                logging.error(f"Failed to process file {filename}: {e}")
                context += f"\n<error>Error al procesar el archivo {filename}: {str(e)}</error>\n"
                continue

        return context

