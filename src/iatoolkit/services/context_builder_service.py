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
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.parsers.parsing_service import ParsingService
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.structured_output_service import StructuredOutputService
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
                 parsing_service: ParsingService,
                 tool_service: ToolService,
                 knowledge_base_service: KnowledgeBaseService,
                 prompt_service: PromptService,
                 util: Utility):
        self.profile_service = profile_service
        self.profile_repo = profile_repo
        self.company_context_service = company_context_service
        self.parsing_service = parsing_service
        self.tool_service = tool_service
        self.knowledge_base_service = knowledge_base_service
        self.prompt_service = prompt_service
        self.util = util

    def get_selected_system_prompt_keys(self, company: Company, query_text: str | None = None) -> list[str]:
        if not company:
            return []

        payload = self.prompt_service.get_system_prompt_payload(
            company_id=company.id,
            company_short_name=company.short_name,
            query_text=query_text,
        )
        selected_keys = payload.get("selected_keys")
        if not isinstance(selected_keys, list):
            return []
        return [key for key in selected_keys if isinstance(key, str) and key.strip()]

    def get_prompt_output_contract(self, company: Company, prompt_name: str | None) -> dict:
        if not company or not prompt_name:
            return {}

        prompt_obj = self.prompt_service.get_prompt_definition(company, prompt_name)
        if not prompt_obj:
            return {}

        schema = prompt_obj.output_schema

        if isinstance(schema, str):
            schema_text = schema.strip()
            if schema_text:
                try:
                    schema = json.loads(schema_text)
                except Exception:
                    try:
                        schema = StructuredOutputService.parse_yaml_schema(schema_text)
                    except Exception:
                        schema = None

        if not isinstance(schema, dict):
            try:
                schema = StructuredOutputService.parse_yaml_schema(prompt_obj.output_schema_yaml)
            except Exception:
                schema = None

        if isinstance(schema, dict):
            try:
                schema = StructuredOutputService.normalize_schema(schema)
            except Exception:
                schema = None

        return {
            "prompt_name": prompt_obj.name,
            "schema": schema,
            "schema_yaml": prompt_obj.output_schema_yaml,
            "schema_mode": prompt_obj.output_schema_mode or "best_effort",
            "response_mode": prompt_obj.output_response_mode or "chat_compatible",
            "attachment_mode": getattr(prompt_obj, "attachment_mode", None),
            "attachment_parser_provider": getattr(prompt_obj, "attachment_parser_provider", None),
            "attachment_fallback": getattr(prompt_obj, "attachment_fallback", None),
            "llm_model": getattr(prompt_obj, "llm_model", None),
            "llm_request_options": dict(getattr(prompt_obj, "llm_request_options", None) or {}),
            "tool_policy": self.prompt_service.normalize_tool_policy(
                getattr(prompt_obj, "tool_policy", None)
            ),
        }

    def build_system_context(
        self,
        company_short_name: str,
        user_identifier: str,
        query_text: str | None = None,
    ) -> Tuple[Optional[str], Optional[dict], list[str]]:
        """
        Builds the complete System Prompt including company context, user profile, and available tools.
        Returns:
            Tuple(final_context_string, user_profile_dict, selected_system_prompt_keys)
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, None, []

        # 1. Get user profile
        user_profile = self.profile_service.get_profile_by_identifier(company_short_name, user_identifier)

        # 2. Render the base system prompt (iatoolkit standard)
        system_prompt_payload = self.prompt_service.get_system_prompt_payload(
            company_id=company.id,
            company_short_name=company.short_name,
            query_text=query_text,
        )
        system_prompt_template = system_prompt_payload.get("content", "")
        selected_system_prompt_keys = system_prompt_payload.get("selected_keys")
        if not isinstance(selected_system_prompt_keys, list):
            selected_system_prompt_keys = []
        rendered_system_prompt = self.util.render_prompt_from_string(
            template_string=system_prompt_template,
            question=None,
            client_data=user_profile,
            company=company,
            service_list=self.tool_service.get_tools_for_llm(company)
        )

        # 3. Get company specific context (DB Schemas, Docs, etc.)
        company_specific_context = self.company_context_service.get_company_context(company_short_name)
        collection_context = self._build_collection_context(company_short_name)
        memory_context = self._build_memory_context()

        # 4. Merge contexts
        final_system_context = "\n".join(
            section
            for section in (company_specific_context, collection_context, memory_context, rendered_system_prompt)
            if section
        )

        return final_system_context, user_profile, selected_system_prompt_keys

    def _build_collection_context(self, company_short_name: str) -> str:
        try:
            descriptors = self.knowledge_base_service.get_collection_descriptors(company_short_name)
        except Exception as exc:
            logging.warning("Could not load collection descriptors for %s: %s", company_short_name, exc)
            return ""

        if not isinstance(descriptors, list) or not descriptors:
            return ""

        lines = [
            "### Available Document Collections",
            "Use `iat_document_search` when internal company documents may help answer the user.",
            "Available collections:",
        ]

        for entry in descriptors[:20]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            description = str(entry.get("description") or "").strip()
            if description:
                lines.append(f"- {name}: {description}")
            else:
                lines.append(f"- {name}")

        if len(lines) <= 3:
            return ""

        lines.append("If one collection clearly matches the question, prefer that collection. If unclear, search without specifying a collection first.")
        return "\n".join(lines)

    def _build_memory_context(self) -> str:
        return "\n".join([
            "### Personal Memory",
            "The user may have personal memory pages built from saved notes, links, files, and chat messages.",
            "Use `iat_memory_search` when the user is explicitly asking about saved notes, remembered items, or personal continuity across sessions.",
            "If `iat_memory_search` returns a result with `has_native_files=true`, call `iat_memory_get_page` before answering whenever the attached file contents may matter.",
            "Use `iat_memory_get_page` to read a specific page before answering when needed.",
            "Prefer memory pages as compiled context; do not assume all saved content is globally relevant.",
        ])

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
                    document_text = self.parsing_service.extract_text_for_context(
                        filename=filename,
                        content=file_content
                    )

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
