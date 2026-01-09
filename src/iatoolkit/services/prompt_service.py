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
from collections import defaultdict
from iatoolkit.repositories.models import (Prompt, PromptCategory,
                                           Company, PromptType)
from iatoolkit.common.exceptions import IAToolkitException
import importlib.resources
import logging
import os

# iatoolkit system prompts definitions
_SYSTEM_PROMPTS = [
    {'name': 'query_main', 'description': 'iatoolkit main prompt', 'order': 1},
    {'name': 'format_styles', 'description': 'output format styles', 'order': 2},
    {'name': 'sql_rules', 'description': 'instructions  for SQL queries', 'order': 3},
]

class PromptService:
    @inject
    def __init__(self,
                 asset_repo: AssetRepository,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService):
        self.asset_repo = asset_repo
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.i18n_service = i18n_service

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
                            'order': p.order
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

        # 2. update the prompt in the database
        new_prompt = Prompt(
            company_id=company.id,
            name=prompt_name,
            description=data.get('description', ''),
            order=data.get('order', 1),
            category_id=category_id,
            active=data.get('active', True),
            prompt_type=data.get('prompt_type', 'company'),
            filename=f"{prompt_name.lower().replace(' ', '_')}.prompt",
            custom_fields=data.get('custom_fields', [])
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

    def get_system_prompt(self):
        try:
            system_prompt_content = []

            # read all the system prompts from the database
            system_prompts = self.llm_query_repo.get_system_prompts()

            for prompt in system_prompts:
                try:
                    content = importlib.resources.read_text('iatoolkit.system_prompts', prompt.filename)
                    system_prompt_content.append(content)
                except FileNotFoundError:
                    logging.warning(f"Prompt file does not exist in the package: {prompt.filename}")
                except Exception as e:
                    raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                             f"error reading system prompt '{prompt.filename}': {e}")

            # join the system prompts into a single string
            return "\n".join(system_prompt_content)

        except IAToolkitException:
            raise
        except Exception as e:
            logging.exception(
                f"Error al obtener el contenido del prompt de sistema: {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.PROMPT_ERROR,
                               f'error reading the system prompts": {str(e)}')

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

        # community edition has its own prompt management
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

                new_prompt = Prompt(
                    company_id=company.id,
                    name=prompt_name,
                    description=prompt_data.get('description'),
                    order=prompt_data.get('order'),
                    category_id=category_obj.id,
                    active=prompt_data.get('active', True),
                    prompt_type=prompt_data.get('prompt_type', PromptType.COMPANY.value).lower(),
                    filename=filename,
                    custom_fields=prompt_data.get('custom_fields', [])
                )

                self.llm_query_repo.create_or_update_prompt(new_prompt)

            # 3. Cleanup: Delete prompts present in DB but not in Config
            existing_prompts = self.llm_query_repo.get_prompts(company)
            for p in existing_prompts:
                if p.name not in defined_prompt_names:
                    # Using hard delete to keep consistent with previous "refresh" behavior
                    self.llm_query_repo.session.delete(p)

            self.llm_query_repo.commit()

        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def register_system_prompts(self, company_short_name: str):
        """
        Instantiates the system prompts into the database.
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f'Company {company_short_name} not found')

        sys_category = PromptCategory(company_id=company.id, name="System", order=0)
        sys_category = self.llm_query_repo.create_or_update_prompt_category(sys_category)

        try:
            defined_names = set()

            for i, prompt_data in enumerate(_SYSTEM_PROMPTS):
                prompt_name = prompt_data['name']
                defined_names.add(prompt_name)
                prompt_filename = f"{prompt_name}.prompt"

                new_prompt = Prompt(
                    company_id=company.id,
                    name=prompt_name,
                    description=prompt_data['description'],
                    order=prompt_data['order'],
                    category_id=sys_category.id,
                    active=True,
                    prompt_type=PromptType.SYSTEM.value,
                    filename=prompt_filename,
                    custom_fields=[]
                )
                self.llm_query_repo.create_or_update_prompt(new_prompt)

                # add prompt to company assets
                prompt_content = importlib.resources.read_text('iatoolkit.system_prompts', prompt_filename)
                self.asset_repo.write_text(company.short_name, AssetType.PROMPT, prompt_filename, prompt_content)

            self.llm_query_repo.commit()
            return True

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
