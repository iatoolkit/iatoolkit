# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.util import Utility
from injector import inject
import logging
import os
import base64


class Dispatcher:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 prompt_service: PromptService,
                 llmquery_repo: LLMQueryRepo,
                 util: Utility,):
        self.config_service = config_service
        self.prompt_service = prompt_service
        self.llmquery_repo = llmquery_repo
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

    def load_company_configs(self):
        # initialize the system functions and prompts
        self.setup_iatoolkit_system()

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

    def setup_iatoolkit_system(self):
        try:
            # system tools registration
            self.tool_service.register_system_tools()

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
            # --- Special case: visual similarity search needs image bytes from request attachments ---
            if function_name == "iat_visual_search":
                request_images = kwargs.pop("request_images", None) or []
                image_index = kwargs.get("image_index", None)
                n_results = kwargs.get("n_results", 5)

                if image_index is None:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_NAME,
                        "iat_visual_search requiere 'image_index'."
                    )

                if not isinstance(image_index, int) or image_index < 0 or image_index >= len(request_images):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_NAME,
                        f"image_index inválido ({image_index}). Imágenes adjuntas disponibles: {len(request_images)}."
                    )

                img_payload = request_images[image_index] or {}
                img_b64 = img_payload.get("base64")
                if not img_b64:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_NAME,
                        f"La imagen adjunta en index {image_index} no contiene campo 'base64'."
                    )

                try:
                    image_content = base64.b64decode(img_b64, validate=False)
                except Exception as e:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_NAME,
                        f"No se pudo decodificar base64 de la imagen en index {image_index}: {str(e)}"
                    ) from e

                handler = self.tool_service.get_system_handler(function_name)
                logging.debug(
                    f"Calling system handler [{function_name}] "
                    f"with company_short_name={company_short_name} "
                    f"and image_index={image_index} n_results={n_results}"
                )
                return handler(company_short_name, image_content=image_content, n_results=n_results)


            # this is the system function to be executed.
            handler = self.tool_service.get_system_handler(function_name)
            logging.debug(
                f"Calling system handler [{function_name}] "
                f"with company_short_name={company_short_name} "
                f"and kwargs={kwargs}"
            )
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
