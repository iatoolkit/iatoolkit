# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from collections import defaultdict
from iatoolkit.repositories.models import Prompt, PromptCategory, Company
import os
from iatoolkit.common.exceptions import IAToolkitException
import importlib.resources
import logging

# iatoolkit system prompts definitions
_SYSTEM_PROMPTS = [
    {'name': 'query_main', 'description': 'iatoolkit main prompt'},
    {'name': 'format_styles', 'description': 'output format styles'},
    {'name': 'sql_rules', 'description': 'instructions  for SQL queries'}
]

class PromptService:
    @inject
    def __init__(self,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService):
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.i18n_service = i18n_service

    def sync_company_prompts(self, company_instance, prompts_config: list, categories_config: list):
        """
        Synchronizes prompt categories and prompts from YAML config to Database.
        Strategies:
        - Categories: Create or Update existing based on name.
        - Prompts: Create or Update existing based on name. Soft-delete or Delete unused.
        """
        try:
            # 1. Sync Categories
            category_map = {}

            for i, category_name in enumerate(categories_config):
                category_obj = PromptCategory(
                    company_id=company_instance.company.id,
                    name=category_name,
                    order=i + 1
                )
                # Persist and get back the object with ID
                persisted_cat = self.llm_query_repo.create_or_update_prompt_category(category_obj)
                category_map[category_name] = persisted_cat

            # 2. Sync Prompts
            defined_prompt_names = set()

            for prompt_data in prompts_config:
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
                    company_id=company_instance.company.id,
                    name=prompt_name,
                    description=prompt_data['description'],
                    order=prompt_data['order'],
                    category_id=category_obj.id,
                    active=prompt_data.get('active', True),
                    is_system_prompt=False,
                    filename=filename,
                    custom_fields=prompt_data.get('custom_fields', [])
                )

                self.llm_query_repo.create_or_update_prompt(new_prompt)

            # 3. Cleanup: Delete prompts present in DB but not in Config
            existing_prompts = self.llm_query_repo.get_prompts(company_instance.company)
            for p in existing_prompts:
                if p.name not in defined_prompt_names:
                    # Using hard delete to keep consistent with previous "refresh" behavior
                    self.llm_query_repo.session.delete(p)

            self.llm_query_repo.commit()

        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def register_system_prompts(self):
        """
        Synchronizes system prompts defined in Dispatcher/Code to Database.
        """
        try:
            defined_names = set()

            for i, prompt_data in enumerate(_SYSTEM_PROMPTS):
                prompt_name = prompt_data['name']
                defined_names.add(prompt_name)

                new_prompt = Prompt(
                    company_id=None,  # System prompts have no company
                    name=prompt_name,
                    description=prompt_data['description'],
                    order=i + 1,
                    category_id=None,
                    active=True,
                    is_system_prompt=True,
                    filename=f"{prompt_name}.prompt",
                    custom_fields=[]
                )
                self.llm_query_repo.create_or_update_prompt(new_prompt)

            # Cleanup old system prompts
            existing_sys_prompts = self.llm_query_repo.get_system_prompts()
            for p in existing_sys_prompts:
                if p.name not in defined_names:
                    self.llm_query_repo.session.delete(p)

            self.llm_query_repo.commit()

        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def create_prompt(self,
                      prompt_name: str,
                      description: str,
                      order: int,
                      company: Company = None,
                      category: PromptCategory = None,
                      active: bool = True,
                      is_system_prompt: bool = False,
                      custom_fields: list = []
                      ):
        """
            Direct creation method (used by sync or direct calls).
            Validates file existence before creating DB entry.
        """
        prompt_filename = prompt_name.lower() + '.prompt'
        if is_system_prompt:
            if not importlib.resources.files('iatoolkit.system_prompts').joinpath(prompt_filename).is_file():
                raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                f'missing system prompt file: {prompt_filename}')
        else:
            template_dir = f'companies/{company.short_name}/prompts'

            relative_prompt_path = os.path.join(template_dir, prompt_filename)
            if not os.path.exists(relative_prompt_path):
                raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                               f'missing prompt file: {relative_prompt_path}')

        if custom_fields:
            for f in custom_fields:
                if ('data_key' not in f) or ('label' not in f):
                    raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                               f'The field "custom_fields" must contain the following keys: data_key y label')

                # add default value for data_type
                if 'type' not in f:
                    f['type'] = 'text'

        prompt = Prompt(
                company_id=company.id if company else None,
                name=prompt_name,
                description=description,
                order=order,
                category_id=category.id if category and not is_system_prompt else None,
                active=active,
                filename=prompt_filename,
                is_system_prompt=is_system_prompt,
                custom_fields=custom_fields
            )

        try:
            self.llm_query_repo.create_or_update_prompt(prompt)
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR,
                               f'error creating prompt "{prompt_name}": {str(e)}')

    def get_prompt_content(self, company: Company, prompt_name: str):
        try:
            user_prompt_content = []
            execution_dir = os.getcwd()

            # get the user prompt
            user_prompt = self.llm_query_repo.get_prompt_by_name(company, prompt_name)
            if not user_prompt:
                raise IAToolkitException(IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND,
                                   f"prompt not found '{prompt_name}' for company '{company.short_name}'")

            prompt_file = f'companies/{company.short_name}/prompts/{user_prompt.filename}'
            absolute_filepath = os.path.join(execution_dir, prompt_file)
            if not os.path.exists(absolute_filepath):
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                   f"prompt file '{prompt_name}' does not exist: {absolute_filepath}")

            try:
                with open(absolute_filepath, 'r', encoding='utf-8') as f:
                    user_prompt_content = f.read()
            except Exception as e:
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                   f"error while reading prompt: '{prompt_name}' in this pathname {absolute_filepath}: {e}")

            return user_prompt_content

        except IAToolkitException:
            # Vuelve a lanzar las IAToolkitException que ya hemos manejado
            # para que no sean capturadas por el siguiente bloque.
            raise
        except Exception as e:
            logging.exception(
                f"error loading prompt '{prompt_name}' content for '{company.short_name}': {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.PROMPT_ERROR,
                               f'error loading prompt "{prompt_name}" content for company {company.short_name}: {str(e)}')

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

    def get_user_prompts(self, company_short_name: str) -> dict:
        try:
            # validate company
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {"error": self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name)}

            # get all the prompts
            all_prompts = self.llm_query_repo.get_prompts(company)

            # Agrupar prompts por categoría
            prompts_by_category = defaultdict(list)
            for prompt in all_prompts:
                if prompt.active:
                    if prompt.category:
                        cat_key = (prompt.category.order, prompt.category.name)
                        prompts_by_category[cat_key].append(prompt)

            # Ordenar los prompts dentro de cada categoría
            for cat_key in prompts_by_category:
                prompts_by_category[cat_key].sort(key=lambda p: p.order)

            # Crear la estructura de respuesta final, ordenada por la categoría
            categorized_prompts = []

            # Ordenar las categorías por su 'order'
            sorted_categories = sorted(prompts_by_category.items(), key=lambda item: item[0][0])

            for (cat_order, cat_name), prompts in sorted_categories:
                categorized_prompts.append({
                    'category_name': cat_name,
                    'category_order': cat_order,
                    'prompts': [
                        {
                            'prompt': p.name,
                            'description': p.description,
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

