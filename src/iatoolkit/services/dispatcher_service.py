# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.inference_service import InferenceService
from iatoolkit.common.util import Utility
from injector import inject
import logging


class Dispatcher:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 prompt_service: PromptService,
                 llmquery_repo: LLMQueryRepo,
                 inference_service: InferenceService,
                 util: Utility,):
        self.config_service = config_service
        self.prompt_service = prompt_service
        self.llmquery_repo = llmquery_repo
        self.inference_service = inference_service
        self.util = util

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


    def dispatch(self, company_short_name: str, function_name: str, **kwargs) -> dict:
        company_key = company_short_name.lower()

        if company_key not in self.company_instances:
            available_companies = list(self.company_instances.keys())
            raise IAToolkitException(
                IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                f"Company '{company_short_name}' not configured. available companies: {available_companies}"
            )

        # 1. Consult the Database (Source of Truth) for the tool definition
        tool_def = self.tool_service.get_tool_definition(company_short_name, function_name)
        if not tool_def:
            raise IAToolkitException(
                IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                f"Tool '{function_name}' not registered for company '{company_short_name}'"
            )

        logging.error(f"DISPATCHER_SERVICE: {tool_def.parameters}")

        # 2. Dispatch based on Tool Type
        if tool_def.tool_type == 'SYSTEM':
            # Map to internal handler
            handler = self.tool_service.get_system_handler(function_name)
            if not handler:
                raise IAToolkitException(IAToolkitException.ErrorType.INTERNAL_ERROR,
                                         f"Handler for system tool '{function_name}' not found.")

            logging.debug(f"Dispatching SYSTEM tool: {function_name}")
            return handler(company_short_name, **kwargs)

        elif tool_def.tool_type == 'INFERENCE':
            # Delegate to Inference Service with DB config
            logging.debug(f"Dispatching INFERENCE tool: {function_name}")
            return self.inference_service.predict(
                company_short_name=company_short_name,
                tool_name=function_name,
                input_data=kwargs,
            )

        elif tool_def.tool_type == 'NATIVE':
            # Delegate to Company Python Class
            logging.debug(f"Dispatching NATIVE tool: {function_name}")
            company_instance = self.company_instances[company_short_name]
            method_name = function_name

            try:
                # Check if the method exists and is callable
                if not hasattr(company_instance, method_name):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                        f"Method '{method_name}' not found in company '{company_short_name}' instance."
                    )

                method = getattr(company_instance, method_name)
                if not callable(method):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                        f"Attribute '{method_name}' in company '{company_short_name}' is not callable."
                    )

                # Execute the method directly in the company class
                return method(**kwargs)

            except IAToolkitException as e:
                raise e
            except Exception as e:
                logging.exception(e)
                raise IAToolkitException(IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                                         f"Error executing native tool '{method_name}': {str(e)}") from e

        else:
            raise IAToolkitException(
                IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                f"Unknown tool type '{tool_def.tool_type}'"
            )

    def load_company_configs(self):

        # Loads the configuration of every company: company.yaml file
        for company_short_name, company_instance in self.company_instances.items():
            try:
                # read company configuration from company.yaml
                config, errors = self.config_service.load_configuration(company_short_name)

                '''
                if errors:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.CONFIG_ERROR,
                        'company.yaml validation errors'
                    )
                '''

                # complement the instance self data
                company_instance.company_short_name = company_short_name
                company_instance.company = config.get('company')

            except Exception as e:
                logging.error(f"❌ Failed to register configuration for '{company_short_name}': {e}")
                raise e

        return True
