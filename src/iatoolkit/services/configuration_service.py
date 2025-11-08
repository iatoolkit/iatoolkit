# iatoolkit/services/configuration_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from pathlib import Path
from iatoolkit import BaseCompany
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import Company
from iatoolkit.common.util import Utility
from injector import inject
import logging

class ConfigurationService:
    """
    Orchestrates the configuration of a Company by reading its YAML files
    and using the BaseCompany's protected methods to register settings.
    """

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 utility: Utility):
        self.profile_repo = profile_repo
        self.utility = utility
        self._loaded_configs = {}   # cache for store loaded configurations

    def get_company_content(self, company_short_name: str, content_key: str) -> dict | list | None:
        """
        Public method to provide a specific section of a company's configuration.
        It uses a cache to avoid reading files from disk on every call.
        """
        self._ensure_config_loaded(company_short_name)
        return self._loaded_configs[company_short_name].get(content_key)

    def register_company(self, company_short_name: str, company_instance: BaseCompany):
        """
        Main entry point for configuring a company instance.
        This method is invoked by the dispatcher for each registered company.
        """
        logging.info(f"⚙️  Starting configuration for company '{company_short_name}'...")

        # 1. identify the instance with his name and load info from database
        company_instance.company_short_name = company_short_name
        company_instance.company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company_instance.company:
            raise ValueError(f"Company '{company_short_name}' not found in database.")

        # 2. Load the main configuration file and supplementary content files
        config = self._load_and_merge_configs(company_short_name)

        # 3. Register core company details and get the database object
        company_db_object = self._register_core_details(company_instance, config)

        # 4. Register tools (functions)
        self._register_tools(company_instance, config.get('tools', []))

        # 5. Register prompt categories and prompts
        self._register_prompts(company_instance, config)

        # 6. Link the persisted Company object back to the running instance
        company_instance.company = company_db_object

        logging.info(f"✅ Company '{company_short_name}' configured successfully.")

    def _ensure_config_loaded(self, company_short_name: str):
        """
        Checks if the configuration for a company is in the cache.
        If not, it loads it from files and stores it.
        """
        if company_short_name not in self._loaded_configs:
            self._loaded_configs[company_short_name] = self._load_and_merge_configs(company_short_name)

    def _load_and_merge_configs(self, company_short_name: str) -> dict:
        """
        Loads the main company.yaml and merges data from supplementary files
        specified in the 'content_files' section.
        """
        config_dir = Path("companies") / company_short_name / "config"
        main_config_path = config_dir / "company.yaml"

        if not main_config_path.exists():
            raise FileNotFoundError(f"Main configuration file not found: {main_config_path}")

        config = self.utility.load_schema_from_yaml(main_config_path)

        # Load and merge supplementary content files (e.g., onboarding_cards)
        for key, file_path in config.get('help_files', {}).items():
            supplementary_path = config_dir / file_path
            if supplementary_path.exists():
                config[key] = self.utility.load_schema_from_yaml(supplementary_path)
            else:
                logging.warning(f"⚠️  Warning: Content file not found: {supplementary_path}")
                config[key] = None  # Ensure the key exists but is empty

        return config

    def _register_core_details(self, company_instance: BaseCompany, config: dict) -> Company:
        """Calls _create_company with data from the merged YAML config."""
        return company_instance._create_company(
            name=config['name'],
            short_name=config['id'],
            parameters=config.get('parameters', {})
        )

    def _register_tools(self, company_instance: BaseCompany, tools_config: list):
        """Calls _create_function for each tool defined in the YAML."""
        for tool in tools_config:
            company_instance._create_function(
                function_name=tool['function_name'],
                description=tool['description'],
                params=tool['params']
            )

    def _register_prompts(self, company_instance: BaseCompany, config: dict):
        """
        Creates prompt categories first, then creates each prompt and assigns
        it to its respective category.
        """
        prompts_config = config.get('prompts', [])
        categories_config = config.get('prompt_categories', [])

        created_categories = {}
        for i, category_name in enumerate(categories_config):
            category_obj = company_instance._create_prompt_category(name=category_name, order=i + 1)
            created_categories[category_name] = category_obj

        for prompt_data in prompts_config:
            category_name = prompt_data.get('category')
            if not category_name or category_name not in created_categories:
                logging.info(f"⚠️  Warning: Prompt '{prompt_data['name']}' has an invalid or missing category. Skipping.")
                continue

            category_obj = created_categories[category_name]
            company_instance._create_prompt(
                prompt_name=prompt_data['name'],
                description=prompt_data['description'],
                order=prompt_data['order'],
                category=category_obj,
                active=prompt_data.get('active', True),
                custom_fields=prompt_data.get('custom_fields', [])
            )
