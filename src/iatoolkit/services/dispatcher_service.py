# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.util import Utility
from injector import inject
import logging
import os


class Dispatcher:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 prompt_service: PromptService,
                 llmquery_repo: LLMQueryRepo,
                 util: Utility,
                 sql_service: SqlService):
        self.config_service = config_service
        self.prompt_service = prompt_service
        self.llmquery_repo = llmquery_repo
        self.util = util
        self.sql_service = sql_service

        self._tool_service = None
        self._company_registry = None
        self._company_instances = None


    @property
    def tool_service(self):
        """Lazy-loads and returns the ToolService instance to avoid circular imports."""
        if self._tool_service is None:
            from iatoolkit import current_iatoolkit
            from iatoolkit.services.tool_service import ToolService
            self._tool_service = current_iatoolkit().get_injector().get(ToolService)
        return self._tool_service

    @property
    def company_registry(self):
        """Lazy-loads and returns the CompanyRegistry instance."""
        if self._company_registry is None:
            from iatoolkit.company_registry import get_company_registry
            self._company_registry = get_company_registry()
        return self._company_registry

    @property
    def company_instances(self):
        """Lazy-loads and returns the instantiated company classes."""
        if self._company_instances is None:
            self._company_instances = self.company_registry.get_all_company_instances()
        return self._company_instances

    def load_company_configs(self):
        # initialize the system functions and prompts
        self.setup_iatoolkit_system()

        # Loads the configuration of every company: company.yaml file
        for company_name, company_instance in self.company_instances.items():
            try:
                # read company configuration from company.yaml
                self.config_service.load_configuration(company_name, company_instance)

                # register the company databases
                self._register_company_databases(company_name)

            except Exception as e:
                logging.error(f"❌ Failed to register configuration for '{company_name}': {e}")
                raise e

        return True

    def _register_company_databases(self, company_name: str):
        """
        Reads the data_sources config for a company and registers each
        database with the central SqlService.
        """
        logging.info(f"🛢️ Registering databases for '{company_name}'...")
        data_sources_config = self.config_service.get_configuration(company_name, 'data_sources')

        if not data_sources_config or not data_sources_config.get('sql'):
            return

        for db_config in data_sources_config['sql']:
            db_name = db_config.get('database')
            db_env_var = db_config.get('connection_string_env')

            # resolve the URI connection string from the environment variable
            db_uri = os.getenv(db_env_var) if db_env_var else None
            if not db_uri:
                logging.error(
                    f"-> Skipping database registration for '{company_name}' due to missing 'database' name or invalid connection URI.")
                return

            self.sql_service.register_database(db_name, db_uri)

    def setup_iatoolkit_system(self):
        try:
            # system tools registration
            self.tool_service.register_system_tools()

            # system prompts registration
            self.prompt_service.register_system_prompts()

        except Exception as e:
            self.llmquery_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))


    def dispatch(self, company_short_name: str, function_name: str, **kwargs) -> dict:
        company_key = company_short_name.lower()

        if company_key not in self.company_instances:
            available_companies = list(self.company_instances.keys())
            raise IAToolkitException(
                IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                f"Company '{company_short_name}' not configured. available companies: {available_companies}"
            )

        # check if action is a system function using ToolService
        if self.tool_service.is_system_tool(function_name):
            handler = self.tool_service.get_system_handler(function_name)
            return handler(company_short_name, **kwargs)

        company_instance = self.company_instances[company_short_name]
        try:
            return company_instance.handle_request(function_name, **kwargs)
        except IAToolkitException as e:
            # Si ya es una IAToolkitException, la relanzamos para preservar el tipo de error original.
            raise e

        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                               f"Error in function call '{function_name}': {str(e)}") from e


    def get_company_instance(self, company_name: str):
        """Returns the instance for a given company name."""
        return self.company_instances.get(company_name)
