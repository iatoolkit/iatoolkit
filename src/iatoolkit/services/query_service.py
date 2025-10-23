# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.llm_client import llmClient
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.document_service import DocumentService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import Task
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
from injector import inject
import base64
import logging
from typing import Optional
import json
import time
import hashlib
import os


GEMINI_MAX_TOKENS_CONTEXT_HISTORY = 200000

class QueryService:
    @inject
    def __init__(self,
                 llm_client: llmClient,
                 profile_service: ProfileService,
                 document_service: DocumentService,
                 document_repo: DocumentRepo,
                 llmquery_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 prompt_service: PromptService,
                 util: Utility,
                 dispatcher: Dispatcher,
                 session_context: UserSessionContextService
                 ):
        self.profile_service = profile_service
        self.document_service = document_service
        self.document_repo = document_repo
        self.llmquery_repo = llmquery_repo
        self.profile_repo = profile_repo
        self.prompt_service = prompt_service
        self.util = util
        self.dispatcher = dispatcher
        self.session_context = session_context
        self.llm_client = llm_client

        # get the model from the environment variable
        self.model = os.getenv("LLM_MODEL", "")
        if not self.model:
            raise IAToolkitException(IAToolkitException.ErrorType.API_KEY,
                               "La variable de entorno 'LLM_MODEL' no está configurada.")

    def _build_context_and_profile(self, company_short_name: str, user_identifier: str) -> tuple:
        # this method read the user/company context from the database and renders the system prompt
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, None

        # Get the user profile from the single source of truth.
        user_profile = self.profile_service.get_profile_by_identifier(company_short_name, user_identifier)
        if not user_profile:
            # This might happen if a session exists for a user that was deleted.
            return None, None

        # render the iatoolkit main system prompt with the company/user information
        system_prompt_template = self.prompt_service.get_system_prompt()
        rendered_system_prompt = self.util.render_prompt_from_string(
            template_string=system_prompt_template,
            question=None,
            client_data=user_profile,
            company=company,
            service_list=self.dispatcher.get_company_services(company)
        )

        # get the company context: schemas, database models, .md files
        company_specific_context = self.dispatcher.get_company_context(company_name=company_short_name)

        # merge context: company + user
        final_system_context = f"{company_specific_context}\n{rendered_system_prompt}"

        return final_system_context, user_profile

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

        try:
            prev_version = self.session_context.get_context_version(company_short_name, user_identifier)
        except Exception:
            prev_version = None

        rebuild_is_needed = not (prev_version and prev_version == current_version and
                                 self._has_valid_cached_context(company_short_name, user_identifier))

        if rebuild_is_needed:
            logging.info(
                f"Se necesita reconstrucción de contexto para {company_short_name}/{user_identifier}. Preparando...")


            # Guardar el contexto preparado y su versión para que `finalize_context_rebuild` los use.
            self.session_context.save_prepared_context(company_short_name, user_identifier, final_system_context,
                                                       current_version)

        return {'rebuild_needed': rebuild_is_needed}

    def finalize_context_rebuild(self, company_short_name: str, user_identifier: str, model: str = ''):

        # end the initilization, if there is a prepare context send it to llm
        if not model:
            model = self.model

        # --- Lógica de Bloqueo ---
        lock_key = f"lock:context:{company_short_name}/{user_identifier}"
        if not self.session_context.acquire_lock(lock_key, expire_seconds=60):
            logging.warning(
                f"Intento de reconstruir contexto para {user_identifier} mientras ya estaba en progreso. Se omite.")
            return

        try:
            start_time = time.time()
            company = self.profile_repo.get_company_by_short_name(company_short_name)

            # get the prepared context and version from the session cache
            prepared_context, version_to_save = self.session_context.get_and_clear_prepared_context(company_short_name,
                                                                                                    user_identifier)
            if not prepared_context:
                logging.info(
                    f"No se requiere reconstrucción de contexto para {company_short_name}/{user_identifier}. Finalización rápida.")
                return

            logging.info(f"Enviando contexto al LLM para {company_short_name}/{user_identifier}...")

            # Limpiar solo el historial de chat y el ID de respuesta anterior
            self.session_context.clear_llm_history(company_short_name, user_identifier)

            if self.util.is_gemini_model(model):
                context_history = [{"role": "user", "content": prepared_context}]
                self.session_context.save_context_history(company_short_name, user_identifier, context_history)

            elif self.util.is_openai_model(model):
                response_id = self.llm_client.set_company_context(
                    company=company, company_base_context=prepared_context, model=model
                )
                self.session_context.save_last_response_id(company_short_name, user_identifier, response_id)

            if version_to_save:
                self.session_context.save_context_version(company_short_name, user_identifier, version_to_save)

            logging.info(
                f"Contexto de {company_short_name}/{user_identifier} establecido en {int(time.time() - start_time)} seg.")
        except Exception as e:
            logging.exception(f"Error en finalize_context_rebuild para {company_short_name}: {e}")
            raise e
        finally:
            # --- Liberar el Bloqueo ---
            self.session_context.release_lock(lock_key)

    def llm_query(self,
                  company_short_name: str,
                  user_identifier: str,
                  task: Optional[Task] = None,
                  prompt_name: str = None,
                  question: str = '',
                  client_data: dict = {},
                  files: list = []) -> dict:
        try:
            company = self.profile_repo.get_company_by_short_name(short_name=company_short_name)
            if not company:
                return {"error": True,
                        "error_message": f'No existe Company ID: {company_short_name}'}

            if not prompt_name and not question:
                return {"error": True,
                        "error_message": f'Hola, cual es tu pregunta?'}

            # get the previous response_id and context history
            previous_response_id = None
            context_history = self.session_context.get_context_history(company.short_name, user_identifier) or []

            if self.util.is_openai_model(self.model):
                # get user context
                previous_response_id = self.session_context.get_last_response_id(company.short_name, user_identifier)
                if not previous_response_id:
                    return {'error': True,
                            "error_message": f"FATAL: No se encontró 'previous_response_id' para '{company.short_name}/{user_identifier}'. La conversación no puede continuar."
                            }
            elif self.util.is_gemini_model(self.model):
                # check the length of the context_history and remove old messages
                self._trim_context_history(context_history)

            # get the user profile data from the session context
            user_profile = self.profile_service.get_profile_by_identifier(company.short_name, user_identifier)

            # combine client_data with user_profile
            final_client_data = (user_profile or {}).copy()
            final_client_data.update(client_data)

            # Load attached files into the context
            files_context = self.load_files_for_context(files)

            # Initialize prompt_content. It will be an empty string for direct questions.
            main_prompt = ""
            if prompt_name:
                # For task-based queries, wrap data into a JSON string and get the specific prompt template
                question_dict = {'prompt': prompt_name, 'data': final_client_data }
                question = json.dumps(question_dict)
                prompt_content = self.prompt_service.get_prompt_content(company, prompt_name)

                # Render the main user prompt using the appropriate template (or an empty one)
                main_prompt = self.util.render_prompt_from_string(
                    template_string=prompt_content,
                    question=question,
                    client_data=final_client_data,
                    user_identifier=user_identifier,
                    company=company,
                )

            # This is the final user-facing prompt for this specific turn
            user_turn_prompt = f"{main_prompt}\n{files_context}"
            if not prompt_name:
                user_turn_prompt += f"\n### La pregunta que debes responder es: {question}"
            else:
                user_turn_prompt += f'\n### Contexto Adicional: El usuario ha aportado este contexto puede ayudar: {question}'

            # add to the history context
            if self.util.is_gemini_model(self.model):
                context_history.append({"role": "user", "content": user_turn_prompt})

            # service list for the function calls
            tools = self.dispatcher.get_company_services(company)

            # openai structured output instructions
            output_schema = {}

            # Now send the instructions to the llm
            response = self.llm_client.invoke(
                company=company,
                user_identifier=user_identifier,
                previous_response_id=previous_response_id,
                context_history=context_history if self.util.is_gemini_model(self.model) else None,
                question=question,
                context=user_turn_prompt,
                tools=tools,
                text=output_schema
            )

            if not response.get('valid_response'):
                response['error'] = True

            # save last_response_id for the history chain
            if "response_id" in response:
                self.session_context.save_last_response_id(company.short_name, user_identifier, response["response_id"])
            if self.util.is_gemini_model(self.model):
                self.session_context.save_context_history(company.short_name, user_identifier, context_history)

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

    def _has_valid_cached_context(self, company_short_name: str, user_identifier: str) -> bool:
        """
        Verifica si existe un estado de contexto reutilizable en sesión.
        - OpenAI: last_response_id presente.
        - Gemini: context_history con al menos 1 mensaje.
        """
        try:
            if self.util.is_openai_model(self.model):
                prev_id = self.session_context.get_last_response_id(company_short_name, user_identifier)
                return bool(prev_id)
            if self.util.is_gemini_model(self.model):
                history = self.session_context.get_context_history(company_short_name, user_identifier) or []
                return len(history) >= 1
            return False
        except Exception as e:
            logging.warning(f"Error verificando caché de contexto: {e}")
            return False

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
            filename = document.get('file_id') or document.get('filename')
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

    def _trim_context_history(self, context_history: list):
        """
        Verifica el tamaño del historial de contexto y elimina los mensajes más antiguos
        si supera un umbral, conservando siempre el mensaje del sistema (índice 0).
        """
        if not context_history or len(context_history) <= 1:
            return  # nothing to remember

        # calculate total tokens
        try:
            total_tokens = sum(self.llm_client.count_tokens(json.dumps(message)) for message in context_history)
        except Exception as e:
            logging.error(f"Error al calcular tokens del historial: {e}. No se pudo recortar el contexto.")
            return

        # Si se excede el límite, eliminar mensajes antiguos (empezando por el segundo)
        while total_tokens > GEMINI_MAX_TOKENS_CONTEXT_HISTORY and len(context_history) > 1:
            try:
                # Eliminar el mensaje más antiguo después del prompt del sistema
                removed_message = context_history.pop(1)
                removed_tokens = self.llm_client.count_tokens(json.dumps(removed_message))
                total_tokens -= removed_tokens
                logging.warning(
                    f"Historial de contexto ({total_tokens + removed_tokens} tokens) excedía el límite de {GEMINI_MAX_TOKENS_CONTEXT_HISTORY}. "
                    f"Nuevo total: {total_tokens} tokens."
                )
            except IndexError:
                # Se produce si solo queda el mensaje del sistema, el bucle debería detenerse.
                break
