# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from typing import Optional, Tuple
import json
import logging
import hashlib

from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.tool_service import ToolService
from iatoolkit.services.document_service import DocumentService
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.common.util import Utility
from iatoolkit.repositories.models import Company


class ContextBuilderService:
    """
    Service responsible for constructing the text contexts and prompts used by the LLM.
    It encapsulates logic for:
    1. Building the System Prompt (Company context + User Profile + Tools).
    2. Building the User Turn Prompt (Question + Attached Files + Specific Prompt Templates).
    3. Processing file attachments (decoding, image separation).
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 profile_repo: ProfileRepo,
                 company_context_service: CompanyContextService,
                 document_service: DocumentService,
                 tool_service: ToolService,
                 prompt_service: PromptService,
                 util: Utility):
        self.profile_service = profile_service
        self.profile_repo = profile_repo
        self.company_context_service = company_context_service
        self.document_service = document_service
        self.tool_service = tool_service
        self.prompt_service = prompt_service
        self.util = util

    def build_system_context(self, company_short_name: str, user_identifier: str) -> Tuple[Optional[str], Optional[dict]]:
        """
        Builds the complete System Prompt including company context, user profile, and available tools.
        Returns:
            Tuple(final_context_string, user_profile_dict)
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, None

        # 1. Get user profile
        user_profile = self.profile_service.get_profile_by_identifier(company_short_name, user_identifier)

        # 2. Render the base system prompt (iatoolkit standard)
        system_prompt_template = self.prompt_service.get_system_prompt()
        rendered_system_prompt = self.util.render_prompt_from_string(
            template_string=system_prompt_template,
            question=None,
            client_data=user_profile,
            company=company,
            service_list=self.tool_service.get_tools_for_llm(company)
        )

        # 3. Get company specific context (DB Schemas, Docs, etc.)
        company_specific_context = self.company_context_service.get_company_context(company_short_name)

        # 4. Merge contexts
        final_system_context = f"{company_specific_context}\n{rendered_system_prompt}"

        return final_system_context, user_profile

    def build_user_turn_prompt(self,
                               company: Company,
                               user_identifier: str,
                               client_data: dict,
                               files: list,
                               prompt_name: Optional[str],
                               question: str) -> Tuple[str, str, list]:
        """
        Builds the specific prompt for the current user turn.
        Handles attached files, multimodal inputs (images), and Jinja template rendering if a prompt_name is provided.

        Returns:
            Tuple(user_turn_prompt_string, effective_question_string, list_of_images)
        """
        # We fetch the profile again to ensure we have the latest data for Jinja rendering context
        user_profile = self.profile_service.get_profile_by_identifier(company.short_name, user_identifier)

        final_client_data = (user_profile or {}).copy()
        final_client_data.update(client_data)

        # Process attached files: extract text content and separate images
        files_context, images = self._process_attachments(files)

        main_prompt = ""
        effective_question = question

        # If a specific prompt template was requested (e.g., "summarize_minutes")
        if prompt_name:
            question_dict = {'prompt': prompt_name, 'data': final_client_data}
            effective_question = json.dumps(question_dict)
            prompt_content = self.prompt_service.get_prompt_content(company, prompt_name)

            # Render the user requested prompt template
            main_prompt = self.util.render_prompt_from_string(
                template_string=prompt_content,
                question=effective_question,
                client_data=final_client_data,
                user_identifier=user_identifier,
                company=company,
                images=images
            )

        # Final assembly of the user prompt
        user_turn_prompt = f"{main_prompt}\n{files_context}"
        if not prompt_name:
            user_turn_prompt += f"\n### La pregunta que debes responder es: {effective_question}"
        else:
            user_turn_prompt += f'\n### Contexto Adicional: El usuario ha aportado este contexto puede ayudar: {effective_question}'

        return user_turn_prompt, effective_question, images

    def compute_context_version(self, context_string: str) -> str:
        """Computes a SHA256 hash of the context string to track changes."""
        try:
            return hashlib.sha256(context_string.encode("utf-8")).hexdigest()
        except Exception:
            return "unknown"

    def _process_attachments(self, files: list) -> Tuple[str, list]:
        """
        Internal helper.
        Decodes text documents into a context string and separates images for multimodal processing.
        """
        if not files:
            return '', []

        context_parts = []
        images = []
        text_files_count = 0

        for document in files:
            # Support multiple naming conventions for robustness
            filename = document.get('file_id') or document.get('filename') or document.get('name')
            base64_content = document.get('base64') or document.get('content')

            if not filename:
                context_parts.append("\n<error>Documento adjunto sin nombre ignorado.</error>\n")
                continue

            if not base64_content:
                context_parts.append(f"\n<error>El archivo '{filename}' no fue encontrado y no pudo ser cargado.</error>\n")
                continue

            # Detect if the file is an image
            if self._is_image(filename):
                images.append({'name': filename, 'base64': base64_content})
                continue

            try:
                # Handle JSON/XML directly or decode base64 for other text files
                if self._is_json(filename):
                    document_text = json.dumps(document.get('content'))
                else:
                    file_content = self.util.normalize_base64_payload(base64_content)
                    document_text = self.document_service.file_to_txt(filename, file_content)

                context_parts.append(f"\n<document name='{filename}'>\n{document_text}\n</document>\n")
                text_files_count += 1
            except Exception as e:
                logging.error(f"Failed to process file {filename}: {e}")
                context_parts.append(f"\n<error>Error al procesar el archivo {filename}: {str(e)}</error>\n")
                continue

        context = ""
        if text_files_count > 0:
            context = f"""
            A continuación encontraras una lista de documentos adjuntos
            enviados por el usuario que hace la pregunta, 
            en total son: {text_files_count} documentos adjuntos
            """ + "".join(context_parts)
        elif context_parts:
            # If only errors were collected
            context = "".join(context_parts)

        return context, images

    def _is_image(self, filename: str) -> bool:
        return filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif'))

    def _is_json(self, filename: str) -> bool:
        return filename.lower().endswith(('.json', '.xml'))