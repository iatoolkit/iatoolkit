# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit import current_iatoolkit
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.configuration_service import ConfigurationService
from collections import defaultdict
from iatoolkit.repositories.models import (Prompt, PromptCategory,
                                           Company, PromptType)
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.system_prompt_catalog import build_system_prompt_payload
from iatoolkit.services.structured_output_service import StructuredOutputService
import logging

class PromptService:
    OUTPUT_SCHEMA_MODE_BEST_EFFORT = "best_effort"
    OUTPUT_SCHEMA_MODE_STRICT = "strict"
    OUTPUT_RESPONSE_MODE_CHAT = "chat_compatible"
    OUTPUT_RESPONSE_MODE_STRUCTURED = "structured_only"
    ATTACHMENT_MODE_EXTRACTED_ONLY = "extracted_only"
    ATTACHMENT_MODE_NATIVE_ONLY = "native_only"
    ATTACHMENT_MODE_NATIVE_PLUS_EXTRACTED = "native_plus_extracted"
    ATTACHMENT_MODE_AUTO = "auto"
    ATTACHMENT_PARSER_PROVIDER_AUTO = "auto"
    ATTACHMENT_PARSER_PROVIDER_DOCLING = "docling"
    ATTACHMENT_PARSER_PROVIDER_BASIC = "basic"
    ATTACHMENT_FALLBACK_EXTRACT = "extract"
    ATTACHMENT_FALLBACK_FAIL = "fail"

    @inject
    def __init__(self,
                 asset_repo: AssetRepository,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService,
                 sql_service: SqlService,
                 configuration_service: ConfigurationService):
        self.asset_repo = asset_repo
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.i18n_service = i18n_service
        self.sql_service = sql_service
        self.configuration_service = configuration_service

    def _normalize_prompt_type(self, prompt_type: str | None) -> str:
        candidate = str(prompt_type or PromptType.COMPANY.value).strip().lower()
        allowed = {
            PromptType.COMPANY.value,
            PromptType.AGENT.value,
        }
        if candidate in allowed:
            return candidate

        logging.warning(
            "Unsupported prompt_type '%s'. Falling back to '%s'.",
            prompt_type,
            PromptType.COMPANY.value,
        )
        return PromptType.COMPANY.value

    def _normalize_output_schema_mode(self, output_schema_mode: str | None) -> str:
        candidate = str(output_schema_mode or self.OUTPUT_SCHEMA_MODE_BEST_EFFORT).strip().lower()
        allowed = {
            self.OUTPUT_SCHEMA_MODE_BEST_EFFORT,
            self.OUTPUT_SCHEMA_MODE_STRICT,
        }
        if candidate in allowed:
            return candidate
        return self.OUTPUT_SCHEMA_MODE_BEST_EFFORT

    def _normalize_output_response_mode(self, output_response_mode: str | None) -> str:
        candidate = str(output_response_mode or self.OUTPUT_RESPONSE_MODE_CHAT).strip().lower()
        allowed = {
            self.OUTPUT_RESPONSE_MODE_CHAT,
            self.OUTPUT_RESPONSE_MODE_STRUCTURED,
        }
        if candidate in allowed:
            return candidate
        return self.OUTPUT_RESPONSE_MODE_CHAT

    def _extract_output_schema_payload(self, data: dict) -> tuple[dict | None, str | None]:
        yaml_value = data.get("output_schema_yaml")
        object_value = data.get("output_schema")

        parsed_from_yaml = None
        if isinstance(yaml_value, str):
            parsed_from_yaml = StructuredOutputService.parse_yaml_schema(yaml_value)
        elif yaml_value is not None:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "output_schema_yaml must be a string.",
            )

        if parsed_from_yaml is not None:
            try:
                normalized = StructuredOutputService.normalize_schema(parsed_from_yaml)
            except ValueError as e:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"Invalid output_schema_yaml: {e}",
                ) from e
            normalized_yaml = StructuredOutputService.dump_yaml_schema(normalized)
            return normalized, normalized_yaml

        if object_value is None:
            return None, None

        if not isinstance(object_value, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "output_schema must be an object.",
            )

        try:
            normalized = StructuredOutputService.normalize_schema(object_value)
        except ValueError as e:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Invalid output_schema: {e}",
            ) from e
        normalized_yaml = StructuredOutputService.dump_yaml_schema(normalized)
        return normalized, normalized_yaml

    def _normalize_attachment_mode(self, attachment_mode: str | None) -> str:
        candidate = str(attachment_mode or self.ATTACHMENT_MODE_EXTRACTED_ONLY).strip().lower()
        allowed = {
            self.ATTACHMENT_MODE_EXTRACTED_ONLY,
            self.ATTACHMENT_MODE_NATIVE_ONLY,
            self.ATTACHMENT_MODE_NATIVE_PLUS_EXTRACTED,
            self.ATTACHMENT_MODE_AUTO,
        }
        if candidate in allowed:
            return candidate
        return self.ATTACHMENT_MODE_EXTRACTED_ONLY

    def _normalize_attachment_fallback(self, attachment_fallback: str | None) -> str:
        candidate = str(attachment_fallback or self.ATTACHMENT_FALLBACK_EXTRACT).strip().lower()
        allowed = {
            self.ATTACHMENT_FALLBACK_EXTRACT,
            self.ATTACHMENT_FALLBACK_FAIL,
        }
        if candidate in allowed:
            return candidate
        return self.ATTACHMENT_FALLBACK_EXTRACT

    def _normalize_attachment_parser_provider(self, attachment_parser_provider: str | None) -> str:
        candidate = str(attachment_parser_provider or self.ATTACHMENT_PARSER_PROVIDER_AUTO).strip().lower()
        allowed = {
            self.ATTACHMENT_PARSER_PROVIDER_AUTO,
            self.ATTACHMENT_PARSER_PROVIDER_DOCLING,
            self.ATTACHMENT_PARSER_PROVIDER_BASIC,
        }
        if candidate == "legacy":
            return self.ATTACHMENT_PARSER_PROVIDER_BASIC
        if candidate in allowed:
            return candidate
        return self.ATTACHMENT_PARSER_PROVIDER_AUTO

    def _get_company_default_attachment_policy(self, company_short_name: str) -> dict:
        llm_config = self.configuration_service.get_configuration(company_short_name, "llm") or {}
        return {
            "attachment_mode": self._normalize_attachment_mode(llm_config.get("default_attachment_mode")),
            "attachment_fallback": self._normalize_attachment_fallback(llm_config.get("default_attachment_fallback")),
        }

    def get_prompts(self, company_short_name: str, include_all: bool = False) -> dict:
        try:
            # validate company
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {"error": self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name)}

            # get all the company prompts
            # If include_all is True, repo should return everything for the company
            # Otherwise, it should return only active prompts
            all_prompts = self.llm_query_repo.get_prompts(company, include_all=include_all)

            # Deduplicate prompts by id
            all_prompts = list({p.id: p for p in all_prompts}.values())

            # group by category
            prompts_by_category = defaultdict(list)
            for prompt in all_prompts:
                # Filter logic moved here or in repo.
                # If include_all is False, we only want active prompts (and maybe only specific types)
                if not include_all:

                    # Standard user view: excludes system/agent hidden prompts if any?
                    if prompt.prompt_type != PromptType.COMPANY.value:
                        continue

                # Grouping logic
                cat_key = (0, "Uncategorized") # Default
                if prompt.category:
                    cat_key = (prompt.category.order, prompt.category.name)

                prompts_by_category[cat_key].append(prompt)

            # sort each category by order
            for cat_key in prompts_by_category:
                prompts_by_category[cat_key].sort(key=lambda p: p.order)

            categorized_prompts = []

            # sort categories by order
            sorted_categories = sorted(prompts_by_category.items(), key=lambda item: item[0][0])

            for (cat_order, cat_name), prompts in sorted_categories:
                categorized_prompts.append({
                    'category_name': cat_name,
                    'category_order': cat_order,
                    'prompts': [
                        {
                            'prompt': p.name,
                            'description': p.description,
                            'type': p.prompt_type,
                            'active': p.active,
                            'custom_fields': p.custom_fields,
                            'order': p.order,
                            'output_schema_mode': p.output_schema_mode,
                            'output_response_mode': p.output_response_mode,
                            'attachment_mode': p.attachment_mode,
                            'attachment_parser_provider': getattr(p, 'attachment_parser_provider', None),
                            'attachment_fallback': p.attachment_fallback,
                        }
                        for p in prompts
                    ]
                })

            return {'message': categorized_prompts}

        except Exception as e:
            logging.error(f"error in get_prompts: {e}")
            return {'error': str(e)}


    def get_prompt_content(self, company: Company, prompt_name: str):
        try:
            # get the prompt from database
            prompt = self.llm_query_repo.get_prompt_by_name(company, prompt_name)
            if not prompt:
                raise IAToolkitException(IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND,
                                   f"prompt not found '{prompt}' for company '{company.short_name}'")

            try:
                # read the prompt content from asset repository
                user_prompt_content = self.asset_repo.read_text(
                    company.short_name,
                    AssetType.PROMPT,
                    prompt.filename
                )
            except FileNotFoundError:
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                         f"prompt file '{prompt.filename}' does not exist for company '{company.short_name}'")
            except Exception as e:
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                         f"error while reading prompt: '{prompt_name}': {e}")

            return user_prompt_content

        except IAToolkitException:
            raise
        except Exception as e:
            logging.exception(
                f"error loading prompt '{prompt_name}' content for '{company.short_name}': {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.PROMPT_ERROR,
                               f'error loading prompt "{prompt_name}" content for company {company.short_name}: {str(e)}')

    def get_prompt_definition(self, company: Company, prompt_name: str) -> Prompt | None:
        try:
            return self.llm_query_repo.get_prompt_by_name(company, prompt_name)
        except Exception as e:
            logging.exception("Error loading prompt definition for '%s': %s", prompt_name, e)
            return None

    def save_prompt(self, company_short_name: str, prompt_name: str, data: dict):
        """
        Create or Update a prompt.
        1. Saves the Jinja content to the .prompt asset file.
        2. Updates the Database.
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f"Company {company_short_name} not found")

        # Validate category if present
        category_id = None
        if 'category' in data:
             # simple lookup, assuming category names are unique per company
             cat = self.llm_query_repo.get_category_by_name(company.id, data['category'])
             if cat:
                 category_id = cat.id

        # 1. save the phisical part of the prompt (content)
        if 'content' in data:
            filename = f"{prompt_name}.prompt"
            filename = filename.lower().replace(' ', '_')
            self.asset_repo.write_text(company_short_name, AssetType.PROMPT, filename, data['content'])

        output_schema, output_schema_yaml = self._extract_output_schema_payload(data)
        company_default_policy = self._get_company_default_attachment_policy(company_short_name)

        # 2. update the prompt in the database
        new_prompt = Prompt(
            company_id=company.id,
            name=prompt_name,
            description=data.get('description', ''),
            order=data.get('order', 1),
            category_id=category_id,
            active=data.get('active', True),
            prompt_type=self._normalize_prompt_type(data.get('prompt_type')),
            filename=f"{prompt_name.lower().replace(' ', '_')}.prompt",
            custom_fields=data.get('custom_fields', []),
            output_schema=output_schema,
            output_schema_yaml=output_schema_yaml,
            output_schema_mode=self._normalize_output_schema_mode(data.get("output_schema_mode")),
            output_response_mode=self._normalize_output_response_mode(data.get("output_response_mode")),
            attachment_mode=self._normalize_attachment_mode(
                data.get("attachment_mode", company_default_policy["attachment_mode"])
            ),
            attachment_parser_provider=self._normalize_attachment_parser_provider(
                data.get("attachment_parser_provider")
            ),
            attachment_fallback=self._normalize_attachment_fallback(
                data.get("attachment_fallback", company_default_policy["attachment_fallback"])
            ),
        )
        self.llm_query_repo.create_or_update_prompt(new_prompt)

    def delete_prompt(self, company_short_name: str, prompt_name: str):
        """
        Deletes a prompt:
        1. Removes from DB.
        2. (Optional) Deletes/Archives physical file.
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, f"Company not found")

        prompt_db = self.llm_query_repo.get_prompt_by_name(company, prompt_name)
        if not prompt_db:
            raise IAToolkitException(IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND, f"Prompt {prompt_name} not found")

        # 1. Remove from DB
        self.llm_query_repo.delete_prompt(prompt_db)

    def _resolve_system_prompt_capabilities(self, company_short_name: str) -> set[str]:
        capabilities: set[str] = set()
        if not company_short_name:
            return capabilities

        try:
            db_names = self.sql_service.get_db_names(company_short_name)
            if isinstance(db_names, list) and db_names:
                capabilities.add("has_sql_sources")
        except Exception as e:
            logging.debug(
                "Could not resolve SQL capabilities for company '%s': %s",
                company_short_name,
                e,
            )

        return capabilities

    def get_system_prompt_payload(
        self,
        company_id: int,
        company_short_name: str | None = None,
        query_text: str | None = None,
    ) -> dict:
        try:
            resolved_short_name = (company_short_name or "").strip()
            if not resolved_short_name:
                company = self.profile_repo.get_company_by_id(company_id)
                if not company:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND,
                        f"company not found for id '{company_id}'",
                    )
                resolved_short_name = company.short_name

            capabilities = self._resolve_system_prompt_capabilities(resolved_short_name)
            payload = build_system_prompt_payload(capabilities, query_text=query_text)
            selected_keys = payload.get("selected_keys")
            if not isinstance(selected_keys, list):
                selected_keys = []

            return {
                "content": payload.get("content", ""),
                "selected_keys": selected_keys,
            }

        except IAToolkitException:
            raise
        except Exception as e:
            logging.exception(
                f"Error al obtener el contenido del prompt de sistema: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.PROMPT_ERROR,
                               f'error reading the system prompts": {str(e)}')

    def get_system_prompt(
        self,
        company_id: int,
        company_short_name: str | None = None,
        query_text: str | None = None,
    ):
        payload = self.get_system_prompt_payload(
            company_id=company_id,
            company_short_name=company_short_name,
            query_text=query_text,
        )
        return payload.get("content", "")

    def sync_company_prompts(self, company_short_name: str, prompt_list: list, categories_config: list):
        """
        Synchronizes prompt categories and prompts from YAML config to Database.
        Strategies:
        - Categories: Create or Update existing based on name.
        - Prompts: Create or Update existing based on name. Soft-delete or Delete unused.
        """
        if not prompt_list:
            return

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f'Company {company_short_name} not found')

        # enterprise edition has its own prompt management
        if not current_iatoolkit().is_community:
            return

        try:
            # 1. Sync Categories
            category_map = {}

            for i, category_name in enumerate(categories_config):
                category_obj = PromptCategory(
                    company_id=company.id,
                    name=category_name,
                    order=i + 1
                )
                # Persist and get back the object with ID
                persisted_cat = self.llm_query_repo.create_or_update_prompt_category(category_obj)
                category_map[category_name] = persisted_cat

            # 2. Sync Prompts
            defined_prompt_names = set()
            company_default_policy = self._get_company_default_attachment_policy(company_short_name)

            for prompt_data in prompt_list:
                category_name = prompt_data.get('category')
                if not category_name or category_name not in category_map:
                    logging.warning(
                        f"⚠️  Warning: Prompt '{prompt_data['name']}' has an invalid or missing category. Skipping.")
                    continue

                prompt_name = prompt_data['name']
                defined_prompt_names.add(prompt_name)

                category_obj = category_map[category_name]
                filename = f"{prompt_name}.prompt"
                normalized_schema = StructuredOutputService.normalize_schema(prompt_data.get("output_schema"))

                new_prompt = Prompt(
                    company_id=company.id,
                    name=prompt_name,
                    description=prompt_data.get('description'),
                    order=prompt_data.get('order'),
                    category_id=category_obj.id,
                    active=prompt_data.get('active', True),
                    prompt_type=self._normalize_prompt_type(prompt_data.get('prompt_type')),
                    filename=filename,
                    custom_fields=prompt_data.get('custom_fields', []),
                    output_schema=normalized_schema,
                    output_schema_yaml=StructuredOutputService.dump_yaml_schema(normalized_schema),
                    output_schema_mode=self._normalize_output_schema_mode(prompt_data.get("output_schema_mode")),
                    output_response_mode=self._normalize_output_response_mode(prompt_data.get("output_response_mode")),
                    attachment_mode=self._normalize_attachment_mode(
                        prompt_data.get("attachment_mode", company_default_policy["attachment_mode"])
                    ),
                    attachment_parser_provider=self._normalize_attachment_parser_provider(
                        prompt_data.get("attachment_parser_provider")
                    ),
                    attachment_fallback=self._normalize_attachment_fallback(
                        prompt_data.get("attachment_fallback", company_default_policy["attachment_fallback"])
                    ),
                )

                self.llm_query_repo.create_or_update_prompt(new_prompt)

            # 3. Cleanup: Delete prompts present in DB but not in Config
            existing_prompts = self.llm_query_repo.get_prompts(company, include_all=True)
            for p in existing_prompts:
                if p.name not in defined_prompt_names:
                    # Using hard delete to keep consistent with previous "refresh" behavior
                    self.llm_query_repo.session.delete(p)

            self.llm_query_repo.commit()

        except IAToolkitException:
            self.llm_query_repo.rollback()
            raise
        except ValueError as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, str(e)) from e
        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def sync_prompt_categories(self, company_short_name: str, categories_config: list):
        """
        Syncs only the prompt categories based on a simple list of names.
        The order in the list determines the 'order' field in DB.
        Removes categories not present in the list.
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f'Company {company_short_name} not found')

        try:
            processed_categories_ids = []

            # 1. Update/Create Categories
            for idx, cat_name in enumerate(categories_config):
                # Order is 0-based index or 1-based, consistent with current usage (seems 0 or 1 is fine, usually 0 for arrays)
                new_cat = PromptCategory(
                    company_id=company.id,
                    name=cat_name,
                    order=idx
                )
                persisted_cat = self.llm_query_repo.create_or_update_prompt_category(new_cat)
                processed_categories_ids.append(persisted_cat.id)

            # 2. Delete missing categories
            # We fetch all categories for the company and delete those not in processed_ids
            all_categories = self.llm_query_repo.get_all_categories(company.id)
            for cat in all_categories:
                if cat.id not in processed_categories_ids:
                    # Depending on logic, we might want to check if they have prompts assigned.
                    # Usually, sync logic implies "force state", so we delete.
                    # SQLAlchemy cascading might handle prompts or set them to null depending on model config.
                    self.llm_query_repo.session.delete(cat)

            self.llm_query_repo.commit()

        except Exception as e:
            self.llm_query_repo.rollback()
            logging.exception(f"Error syncing prompt categories: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))
