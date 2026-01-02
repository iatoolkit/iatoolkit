# iatoolkit/services/configuration_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from iatoolkit.repositories.models import Company
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.common.util import Utility
from injector import inject
from typing import Any
import logging
import os


class ConfigurationService:
    """
    Orchestrates the configuration of a Company by reading its YAML files
    and using the BaseCompany's protected methods to register settings.
    """

    @inject
    def __init__(self,
                 asset_repo: AssetRepository,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 utility: Utility):
        self.asset_repo = asset_repo
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.utility = utility
        self._loaded_configs = {}   # cache for store loaded configurations

    def _ensure_config_loaded(self, company_short_name: str):
        """
        Checks if the configuration for a company is in the cache.
        If not, it loads it from files and stores it.
        """
        if company_short_name not in self._loaded_configs:
            self._loaded_configs[company_short_name] = self._load_and_merge_configs(company_short_name)

    def get_configuration(self, company_short_name: str, content_key: str):
        """
        Public method to provide a specific section of a company's configuration.
        It uses a cache to avoid reading files from disk on every call.
        """
        self._ensure_config_loaded(company_short_name)
        return self._loaded_configs[company_short_name].get(content_key)

    def get_llm_configuration(self, company_short_name: str):
        """
        Convenience helper to obtain the 'llm' configuration block for a company.
        Kept separate from get_configuration() to avoid coupling tests that
        assert the number of calls to get_configuration().
        """
        default_llm_model = None
        available_llm_models = []
        self._ensure_config_loaded(company_short_name)
        llm_config = self._loaded_configs[company_short_name].get("llm")
        if llm_config:
            default_llm_model = llm_config.get("model")
            available_llm_models = llm_config.get('available_models') or []

        # fallback: if no explicit list of models is provided, use the default model
        if not available_llm_models and default_llm_model:
            available_llm_models = [{
                "id": default_llm_model,
                "label": default_llm_model,
                "description": "Modelo por defecto configurado para esta compañía."
            }]
        return default_llm_model, available_llm_models

    def load_configuration(self, company_short_name: str):
        """
        Main entry point for configuring a company instance.
        This method is invoked by the dispatcher for each registered company.
        """
        logging.info(f"⚙️  Starting configuration for company '{company_short_name}'...")

        # 1. Load the main configuration file and supplementary content files
        config = self._load_and_merge_configs(company_short_name)
        if config:
            # 2. create/update company in database
            self._register_company_database(config)

            # 3. Register tools
            self._register_tools(company_short_name, config)

            # 4. Register prompt categories and prompts
            self._register_prompts(company_short_name, config)

            # 5. Register Knowledge base information
            self._register_knowledge_base(company_short_name, config)

        # Final step: validate the configuration against platform
        errors = self._validate_configuration(company_short_name, config)

        logging.info(f"✅ Company '{company_short_name}' configured successfully.")
        return config, errors

    def update_configuration_key(self, company_short_name: str, key: str, value) -> tuple[dict, list[str]]:
        """
        Updates a specific key in the company's configuration file, validates the result,
        and saves it to the asset repository if valid.

        Args:
            company_short_name: The company identifier.
            key: The configuration key to update (supports dot notation, e.g., 'llm.model').
            value: The new value for the key.

        Returns:
            A tuple containing the updated configuration dict and a list of error strings (if any).
        """
        # 1. Load raw config from file (to avoid working with merged supplementary files if possible,
        # but for simplicity we load the main yaml structure)
        main_config_filename = "company.yaml"

        if not self.asset_repo.exists(company_short_name, AssetType.CONFIG, main_config_filename):
            raise FileNotFoundError(f"Configuration file not found for {company_short_name}")

        yaml_content = self.asset_repo.read_text(company_short_name, AssetType.CONFIG, main_config_filename)
        config = self.utility.load_yaml_from_string(yaml_content) or {}

        # 2. Update the key in the dictionary
        self._set_nested_value(config, key, value)

        # 3. Validate the new configuration structure
        errors = self._validate_configuration(company_short_name, config)

        if errors:
            logging.warning(f"Configuration update failed validation: {errors}")
            return config, errors

        # 4. Save back to repository
        # Assuming Utility has a method to dump YAML. If not, standard yaml library would be needed.
        # For this example, we assume self.utility.dump_yaml_to_string exists.
        new_yaml_content = self.utility.dump_yaml_to_string(config)
        self.asset_repo.write_text(company_short_name, AssetType.CONFIG, main_config_filename, new_yaml_content)

        # 5. Invalidate cache so next reads get the new version
        if company_short_name in self._loaded_configs:
            del self._loaded_configs[company_short_name]

        return config, []

    def add_configuration_key(self, company_short_name: str, parent_key: str, key: str, value) -> tuple[dict, list[str]]:
        """
        Adds a new key-value pair under a specific parent key in the configuration.

        Args:
            company_short_name: The company identifier.
            parent_key: The parent configuration key under which to add the new key (e.g., 'llm').
            key: The new key name to add.
            value: The value for the new key.

        Returns:
            A tuple containing the updated configuration dict and a list of error strings (if any).
        """
        # 1. Load raw config from file
        main_config_filename = "company.yaml"

        if not self.asset_repo.exists(company_short_name, AssetType.CONFIG, main_config_filename):
            raise FileNotFoundError(f"Configuration file not found for {company_short_name}")

        yaml_content = self.asset_repo.read_text(company_short_name, AssetType.CONFIG, main_config_filename)
        config = self.utility.load_yaml_from_string(yaml_content) or {}

        # 2. Construct full path and set the value
        # If parent_key is provided, we append the new key to it (e.g., 'llm.new_setting')
        full_path = f"{parent_key}.{key}" if parent_key else key
        self._set_nested_value(config, full_path, value)

        # 3. Validate the new configuration structure
        errors = self._validate_configuration(company_short_name, config)

        if errors:
            logging.warning(f"Configuration add failed validation: {errors}")
            return config, errors

        # 4. Save back to repository
        new_yaml_content = self.utility.dump_yaml_to_string(config)
        self.asset_repo.write_text(company_short_name, AssetType.CONFIG, main_config_filename, new_yaml_content)

        # 5. Invalidate cache
        if company_short_name in self._loaded_configs:
            del self._loaded_configs[company_short_name]

        return config, []


    def validate_configuration(self, company_short_name: str) -> list[str]:
        """
        Public method to trigger validation of the current configuration.
        """
        config = self._load_and_merge_configs(company_short_name)
        return self._validate_configuration(company_short_name, config)

    def _set_nested_value(self, data: dict, key: str, value):
        """
        Helper to set a value in a nested dictionary or list using dot notation (e.g. 'llm.model', 'tools.0.name').
        Handles traversal through both dictionaries and lists.
        """
        keys = key.split('.')
        current = data

        # Traverse up to the parent of the target key
        for i, k in enumerate(keys[:-1]):
            if isinstance(current, dict):
                # If it's a dict, we can traverse or create the path
                current = current.setdefault(k, {})
            elif isinstance(current, list):
                # If it's a list, we MUST use an integer index
                try:
                    idx = int(k)
                    current = current[idx]
                except (ValueError, IndexError) as e:
                    raise ValueError(
                        f"Invalid path: cannot access index '{k}' in list at '{'.'.join(keys[:i + 1])}'") from e
            else:
                raise ValueError(
                    f"Invalid path: '{k}' is not a container (got {type(current)}) at '{'.'.join(keys[:i + 1])}'")

        # Set the final value
        last_key = keys[-1]
        if isinstance(current, dict):
            current[last_key] = value
        elif isinstance(current, list):
            try:
                idx = int(last_key)
                current[idx] = value
            except (ValueError, IndexError) as e:
                raise ValueError(f"Invalid path: cannot assign to index '{last_key}' in list") from e
        else:
            raise ValueError(f"Cannot assign value to non-container type {type(current)} at '{key}'")

    def _load_and_merge_configs(self, company_short_name: str) -> dict:
        """
        Loads the main company.yaml and merges data from supplementary files
        specified in the 'content_files' section using AssetRepository.
        """
        main_config_filename = "company.yaml"

        # verify existence of the main configuration file
        if not self.asset_repo.exists(company_short_name, AssetType.CONFIG, main_config_filename):
            # raise FileNotFoundError(f"Main configuration file not found: {main_config_filename}")
            logging.exception(f"Main configuration file not found: {main_config_filename}")

            # return the minimal configuration needed for starting the IAToolkit
            # this is a for solving a chicken/egg problem when trying to migrate the configuration
            # from filesystem to database in enterprise installation
            # see create_assets cli command in enterprise-iatoolkit)
            return {
                'id': company_short_name,
                'name': company_short_name,
                'llm': {'model': 'gpt-5', 'provider_api_keys': {'openai':''} },
                }

        # read text and parse
        yaml_content = self.asset_repo.read_text(company_short_name, AssetType.CONFIG, main_config_filename)
        config = self.utility.load_yaml_from_string(yaml_content)
        if not config:
            return {}

        # Load and merge supplementary content files (e.g., onboarding_cards)
        for key, filename in config.get('help_files', {}).items():
            if self.asset_repo.exists(company_short_name, AssetType.CONFIG, filename):
                supp_content = self.asset_repo.read_text(company_short_name, AssetType.CONFIG, filename)
                config[key] = self.utility.load_yaml_from_string(supp_content)
            else:
                logging.warning(f"⚠️  Warning: Content file not found: {filename}")
                config[key] = None

        return config

    def _register_company_database(self, config: dict) -> Company:
        # register the company in the database: create_or_update logic
        if not config:
            return None

        # create or update the company in database
        company_obj = Company(short_name=config.get('id'),
                              name=config.get('name'),
                              parameters=config.get('parameters', {}))
        company = self.profile_repo.create_company(company_obj)

        # save company object with the configuration
        config['company'] = company

        return company

    def register_data_sources(self,
                              company_short_name: str,
                              config: dict = None):
        """
        Reads the data_sources config and registers databases with SqlService.
        Uses Lazy Loading to avoid circular dependency.

        Public method: Can be called externally after initialization (e.g. by Enterprise)
        to re-register sources once new factories (like 'bridge') are available.
        """

        # If config is not provided, try to load it from cache
        if config is None:
            self._ensure_config_loaded(company_short_name)
            config = self._loaded_configs.get(company_short_name)

        if not config:
            return

        from iatoolkit import current_iatoolkit
        from iatoolkit.services.sql_service import SqlService
        sql_service = current_iatoolkit().get_injector().get(SqlService)

        data_sources = config.get('data_sources', {})
        sql_sources = data_sources.get('sql', [])

        if not sql_sources:
            return

        logging.info(f"🛢️ Registering databases  for '{company_short_name}'...")

        for source in sql_sources:
            db_name = source.get('database')
            if not db_name:
                continue

            # Prepare the config dictionary for the factory
            db_config = {
                'database': db_name,
                'schema': source.get('schema', 'public'),
                'connection_type': source.get('connection_type', 'direct'),

                # Pass through keys needed for Bridge or other plugins
                'bridge_id': source.get('bridge_id'),
                'timeout': source.get('timeout')
            }

            # Resolve URI if env var is present (Required for 'direct', optional for others)
            db_env_var = source.get('connection_string_env')
            if db_env_var:
                db_uri = os.getenv(db_env_var)
                if db_uri:
                    db_config['db_uri'] = db_uri

            # Validation: 'direct' connections MUST have a URI
            if db_config['connection_type'] == 'direct' and not db_config.get('db_uri'):
                logging.error(
                    f"-> Skipping DB '{db_name}' for '{company_short_name}': missing URI in env '{db_env_var}'.")
                continue

            elif db_config['connection_type'] == 'bridge' and not db_config.get('bridge_id'):
                logging.error(
                    f"-> Skipping DB '{db_name}' for '{company_short_name}': missing bridge_id in configuration.")
                continue

            # Register with the SQL service
            sql_service.register_database(company_short_name, db_name, db_config)

    def _register_tools(self, company_short_name: str, config: dict):
        """creates in the database each tool defined in the YAML."""
        # Lazy import and resolve ToolService locally
        from iatoolkit import current_iatoolkit
        from iatoolkit.services.tool_service import ToolService
        tool_service = current_iatoolkit().get_injector().get(ToolService)

        tools_config = config.get('tools', [])
        tool_service.sync_company_tools(company_short_name, tools_config)

    def _register_prompts(self, company_short_name: str, config: dict):
        """
         Delegates prompt synchronization to PromptService.
         """
        # Lazy import to avoid circular dependency
        from iatoolkit import current_iatoolkit
        from iatoolkit.services.prompt_service import PromptService
        prompt_service = current_iatoolkit().get_injector().get(PromptService)

        prompts_config = config.get('prompts', [])
        categories_config = config.get('prompt_categories', [])

        prompt_service.sync_company_prompts(
            company_short_name=company_short_name,
            prompts_config=prompts_config,
            categories_config=categories_config
        )

    def _register_knowledge_base(self, company_short_name: str, config: dict):
        # Lazy import to avoid circular dependency
        from iatoolkit import current_iatoolkit
        from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
        knowledge_base = current_iatoolkit().get_injector().get(KnowledgeBaseService)

        kb_config = config.get('knowledge_base', {})
        categories_config = kb_config.get('collections', [])

        # sync collection types in database
        knowledge_base.sync_collection_types(company_short_name, categories_config)


    def _validate_configuration(self, company_short_name: str, config: dict):
        """
        Validates the structure and consistency of the company.yaml configuration.
        It checks for required keys, valid values, and existence of related files.
        Raises IAToolkitException if any validation error is found.
        """
        errors = []

        # Helper to collect errors
        def add_error(section, message):
            errors.append(f"[{section}] {message}")

        if not config:
            add_error("General", "Configuration file missing or with errors, check the application logs.")
            return errors

        # 1. Top-level keys
        if not config.get("id"):
            add_error("General", "Missing required key: 'id'")
        elif config["id"] != company_short_name:
            add_error("General",
                      f"'id' ({config['id']}) does not match the company short name ('{company_short_name}').")
        if not config.get("name"):
            add_error("General", "Missing required key: 'name'")

        # 2. LLM section
        if not isinstance(config.get("llm"), dict):
            add_error("llm", "Missing or invalid 'llm' section.")
        else:
            if not config.get("llm", {}).get("model"):
                add_error("llm", "Missing required key: 'model'")
            if not config.get("llm", {}).get("provider_api_keys"):
                add_error("llm", "Missing required key: 'provider_api_keys'")

        # 3. Embedding Provider
        if isinstance(config.get("embedding_provider"), dict):
            if not config.get("embedding_provider", {}).get("provider"):
                add_error("embedding_provider", "Missing required key: 'provider'")
            if not config.get("embedding_provider", {}).get("model"):
                add_error("embedding_provider", "Missing required key: 'model'")
            if not config.get("embedding_provider", {}).get("api_key_name"):
                add_error("embedding_provider", "Missing required key: 'api_key_name'")

        # 4. Data Sources
        for i, source in enumerate(config.get("data_sources", {}).get("sql", [])):
            if not source.get("database"):
                add_error(f"data_sources.sql[{i}]", "Missing required key: 'database'")

            connection_type = source.get("connection_type")
            if connection_type == 'direct' and not source.get("connection_string_env"):
                add_error(f"data_sources.sql[{i}]", "Missing required key: 'connection_string_env'")
            elif connection_type == 'bridge' and not source.get("bridge_id"):
                add_error(f"data_sources.sql[{i}]", "Missing bridge_id'")

        # 5. Tools
        for i, tool in enumerate(config.get("tools", [])):
            function_name = tool.get("function_name")
            if not function_name:
                add_error(f"tools[{i}]", "Missing required key: 'function_name'")

            # check that function exist in dispatcher
            if not tool.get("description"):
                add_error(f"tools[{i}]", "Missing required key: 'description'")
            if not isinstance(tool.get("params"), dict):
                add_error(f"tools[{i}]", "'params' key must be a dictionary.")

        # 6. Prompts
        category_set = set(config.get("prompt_categories", []))
        for i, prompt in enumerate(config.get("prompts", [])):
            prompt_name = prompt.get("name")
            if not prompt_name:
                add_error(f"prompts[{i}]", "Missing required key: 'name'")
            else:
                prompt_filename = f"{prompt_name}.prompt"
                if not self.asset_repo.exists(company_short_name, AssetType.PROMPT, prompt_filename):
                    add_error(f"prompts/{prompt_name}:", f"Prompt file not found: {prompt_filename}")

                prompt_description = prompt.get("description")
                if not prompt_description:
                    add_error(f"prompts[{i}]", "Missing required key: 'description'")

            prompt_cat = prompt.get("category")
            if not prompt_cat:
                add_error(f"prompts[{i}]", "Missing required key: 'category'")
            elif prompt_cat not in category_set:
                add_error(f"prompts[{i}]", f"Category '{prompt_cat}' is not defined in 'prompt_categories'.")

        # 7. User Feedback
        feedback_config = config.get("parameters", {}).get("user_feedback", {})
        if feedback_config.get("channel") == "email" and not feedback_config.get("destination"):
            add_error("parameters.user_feedback", "When channel is 'email', a 'destination' is required.")

        # 8. Knowledge Base
        kb_config = config.get("knowledge_base", {})
        if kb_config and not isinstance(kb_config, dict):
            add_error("knowledge_base", "Section must be a dictionary.")
        elif kb_config:
            prod_connector = kb_config.get("connectors", {}).get("production", {})
            if prod_connector.get("type") == "s3":
                for key in ["bucket", "prefix", "aws_access_key_id_env", "aws_secret_access_key_env", "aws_region_env"]:
                    if not prod_connector.get(key):
                        add_error("knowledge_base.connectors.production", f"S3 connector is missing '{key}'.")

        # 9. Mail Provider
        mail_config = config.get("mail_provider", {})
        if mail_config:
            provider = mail_config.get("provider")
            if not provider:
                add_error("mail_provider", "Missing required key: 'provider'")
            elif provider not in ["brevo_mail", "smtplib"]:
                add_error("mail_provider", f"Unsupported provider: '{provider}'. Must be 'brevo_mail' or 'smtplib'.")

            if not mail_config.get("sender_email"):
                add_error("mail_provider", "Missing required key: 'sender_email'")

        # 10. Help Files
        for key, filename in config.get("help_files", {}).items():
            if not filename:
                add_error(f"help_files.{key}", "Filename cannot be empty.")
                continue
            if not self.asset_repo.exists(company_short_name, AssetType.CONFIG, filename):
                add_error(f"help_files.{key}", f"Help file not found: {filename}")


        # If any errors were found, log all messages and raise an exception
        if errors:
            error_summary = f"Configuration file '{company_short_name}/config/company.yaml' for '{company_short_name}' has validation errors:\n" + "\n".join(
                f" - {e}" for e in errors)
            logging.error(error_summary)

        return errors

