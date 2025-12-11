# iatoolkit/services/configuration_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from pathlib import Path
from iatoolkit.repositories.models import Company
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from injector import inject
import logging
import os


class ConfigurationService:
    """
    Orchestrates the configuration of a Company by reading its YAML files
    and using the BaseCompany's protected methods to register settings.
    """

    @inject
    def __init__(self,
                 llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 utility: Utility):
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

    def get_llm_configuration(self, company_short_name: str) -> dict | None:
        """
        Convenience helper to obtain the 'llm' configuration block for a company.
        Kept separate from get_configuration() to avoid coupling tests that
        assert the number of calls to get_configuration().
        """
        self._ensure_config_loaded(company_short_name)
        llm_config = self._loaded_configs[company_short_name].get("llm")
        return llm_config if isinstance(llm_config, dict) else None

    def load_configuration(self, company_short_name: str, company_instance):
        """
        Main entry point for configuring a company instance.
        This method is invoked by the dispatcher for each registered company.
        """
        logging.info(f"⚙️  Starting configuration for company '{company_short_name}'...")

        # 1. Load the main configuration file and supplementary content files
        config = self._load_and_merge_configs(company_short_name)

        # 2. Register core company details and get the database object
        self._register_core_details(company_instance, config)

        # 3. Register databases
        self._register_data_sources(company_short_name, config)

        # 4. Register tools
        self._register_tools(company_instance, config)

        # 5. Register prompt categories and prompts
        self._register_prompts(company_instance, config)

        # 6. Link the persisted Company object back to the running instance
        company_instance.company_short_name = company_short_name
        company_instance.id = company_instance.company.id

        # Final step: validate the configuration against platform
        self._validate_configuration(company_short_name, config)

        logging.info(f"✅ Company '{company_short_name}' configured successfully.")


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

    def _register_core_details(self, company_instance, config: dict) -> Company:
        # register the company in the database: create_or_update logic

        company_obj = Company(short_name=config['id'],
                              name=config['name'],
                              parameters=config.get('parameters', {}))
        company = self.profile_repo.create_company(company_obj)

        # save company object with the instance
        company_instance.company = company
        return company

    def _register_data_sources(self, company_short_name: str, config: dict):
        """
        Reads the data_sources config and registers databases with SqlService.
        Uses Lazy Loading to avoid circular dependency.
        """
        # Lazy import to avoid circular dependency: ConfigService -> SqlService -> I18n -> ConfigService
        from iatoolkit import current_iatoolkit
        from iatoolkit.services.sql_service import SqlService
        sql_service = current_iatoolkit().get_injector().get(SqlService)

        data_sources = config.get('data_sources', {})
        sql_sources = data_sources.get('sql', [])

        if not sql_sources:
            return

        logging.info(f"🛢️ Registering databases for '{company_short_name}'...")

        for db_config in sql_sources:
            db_name = db_config.get('database')
            db_schema = db_config.get('schema', 'public')
            db_env_var = db_config.get('connection_string_env')

            # resolve the URI
            db_uri = os.getenv(db_env_var) if db_env_var else None

            if not db_uri:
                logging.error(
                    f"-> Skipping DB '{db_name}' for '{company_short_name}': missing URI in env '{db_env_var}'.")
                continue

            # Register with the SQL service
            sql_service.register_database(db_uri, db_name, db_schema)

    def _register_tools(self, company_instance, config: dict):
        """creates in the database each tool defined in the YAML."""
        # Lazy import and resolve ToolService locally
        from iatoolkit import current_iatoolkit
        from iatoolkit.services.tool_service import ToolService
        tool_service = current_iatoolkit().get_injector().get(ToolService)

        tools_config = config.get('tools', [])
        tool_service.sync_company_tools(company_instance, tools_config)

    def _register_prompts(self, company_instance, config: dict):
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
            company_instance=company_instance,
            prompts_config=prompts_config,
            categories_config=categories_config
        )

    def _validate_configuration(self, company_short_name: str, config: dict):
        """
        Validates the structure and consistency of the company.yaml configuration.
        It checks for required keys, valid values, and existence of related files.
        Raises IAToolkitException if any validation error is found.
        """
        errors = []
        config_dir = Path("companies") / company_short_name / "config"
        prompts_dir = Path("companies") / company_short_name / "prompts"

        # Helper to collect errors
        def add_error(section, message):
            errors.append(f"[{section}] {message}")

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
            if not config.get("llm", {}).get("api-key"):
                add_error("llm", "Missing required key: 'api-key'")

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
            if not source.get("connection_string_env"):
                add_error(f"data_sources.sql[{i}]", "Missing required key: 'connection_string_env'")

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
                prompt_file = prompts_dir / f"{prompt_name}.prompt"
                if not prompt_file.is_file():
                    add_error(f"prompts/{prompt_name}:", f"Prompt file not found: {prompt_file}")

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
            help_file_path = config_dir / filename
            if not help_file_path.is_file():
                add_error(f"help_files.{key}", f"Help file not found: {help_file_path}")

        # If any errors were found, log all messages and raise an exception
        if errors:
            error_summary = f"Configuration file '{company_short_name}/config/company.yaml' for '{company_short_name}' has validation errors:\n" + "\n".join(
                f" - {e}" for e in errors)
            logging.error(error_summary)

            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                'company.yaml validation errors'
            )

