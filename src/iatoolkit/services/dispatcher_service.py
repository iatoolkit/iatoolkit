# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.models import Company, Function
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.mail_service import MailService
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
                 sql_service: SqlService,
                 excel_service: ExcelService,
                 mail_service: MailService):
        self.config_service = config_service
        self.prompt_service = prompt_service
        self.llmquery_repo = llmquery_repo
        self.util = util
        self.sql_service = sql_service
        self.excel_service = excel_service
        self.mail_service = mail_service
        self.system_functions = _FUNCTION_LIST
        self.system_prompts = _SYSTEM_PROMPT

        self._company_registry = None
        self._company_instances = None

        self.tool_handlers = {
            "iat_generate_excel": self.excel_service.excel_generator,
            "iat_send_email": self.mail_service.send_mail,
            "iat_sql_query": self.sql_service.exec_sql
        }

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

        """Loads the configuration of every company"""
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
        logging.info(f"  -> Registering databases for '{company_name}'...")
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
        # create system functions
        for function in self.system_functions:
            self.llmquery_repo.create_function(
                Function(
                    company_id=None,
                    system_function=True,
                    name=function['function_name'],
                    description= function['description'],
                    parameters=function['parameters']
                )
            )

        # create the system prompts
        i = 1
        for prompt in self.system_prompts:
            self.prompt_service.create_prompt(
                prompt_name=prompt['name'],
                description=prompt['description'],
                order=1,
                is_system_prompt=True,
            )
            i += 1


    def dispatch(self, company_short_name: str, function_name: str, **kwargs) -> dict:
        company_key = company_short_name.lower()

        if company_key not in self.company_instances:
            available_companies = list(self.company_instances.keys())
            raise IAToolkitException(
                IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                f"Empresa '{company_short_name}' no configurada. Empresas disponibles: {available_companies}"
            )

        # check if action is a system function
        if function_name in self.tool_handlers:
            return  self.tool_handlers[function_name](company_short_name, **kwargs)

        company_instance = self.company_instances[company_short_name]
        try:
            return company_instance.handle_request(function_name, **kwargs)
        except IAToolkitException as e:
            # Si ya es una IAToolkitException, la relanzamos para preservar el tipo de error original.
            raise e

        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                               f"Error en function call '{function_name}': {str(e)}") from e

    def get_company_services(self, company: Company) -> list[dict]:
        # create the syntax with openai response syntax, for the company function list
        tools = []
        functions = self.llmquery_repo.get_company_functions(company)

        for function in functions:
            # make sure is always on
            function.parameters["additionalProperties"] = False

            ai_tool = {
                "type": "function",
                "name": function.name,
                "description": function.description,
                "parameters": function.parameters,
                "strict": True
            }
            tools.append(ai_tool)
        return tools

    def get_user_info(self, company_name: str, user_identifier: str) -> dict:
        if company_name not in self.company_instances:
            raise IAToolkitException(IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                                     f"company not configured: {company_name}")

        # source 2: external company user
        company_instance = self.company_instances[company_name]
        try:
            external_user_profile = company_instance.get_user_info(user_identifier)
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.EXTERNAL_SOURCE_ERROR,
                                     f"Error in get_user_info: {company_name}: {str(e)}") from e

        return external_user_profile

    def get_company_instance(self, company_name: str):
        """Returns the instance for a given company name."""
        return self.company_instances.get(company_name)


# iatoolkit system prompts
_SYSTEM_PROMPT = [
    {'name': 'query_main', 'description':'iatoolkit main prompt'},
    {'name': 'format_styles', 'description':'output format styles'},
    {'name': 'sql_rules', 'description':'instructions  for SQL queries'}
]

# iatoolkit  built-in functions (Tools)
_FUNCTION_LIST = [
    {
        "function_name": "iat_sql_query",
        "description": "Servicio SQL de IAToolkit: debes utilizar este servicio para todas las consultas a base de datos.",
        "parameters": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "nombre de la base de datos a consultar: `database_name`"
                },
                "query": {
                    "type": "string",
                    "description": "string con la consulta en sql"
                },
            },
            "required": ["database", "query"]
            }
    },
    {
        "function_name": "iat_generate_excel",
        "description": "Generador de Excel."
                    "Genera un archivo Excel (.xlsx) a partir de una lista de diccionarios. "
                    "Cada diccionario representa una fila del archivo. "
                    "el archivo se guarda en directorio de descargas."
                    "retorna diccionario con filename, attachment_token (para enviar archivo por mail)"
                    "content_type y download_link",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nombre del archivo de salida (ejemplo: 'reporte.xlsx')",
                    "pattern": "^.+\\.xlsx?$"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "Nombre de la hoja dentro del Excel",
                    "minLength": 1
                },
                "data": {
                    "type": "array",
                    "description": "Lista de diccionarios. Cada diccionario representa una fila.",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "number"},
                                {"type": "boolean"},
                                {"type": "null"},
                                {
                                    "type": "string",
                                    "format": "date"
                                }
                            ]
                        }
                    }
                }
            },
            "required": ["filename", "sheet_name", "data"]
        }
    },
    {
        'function_name': "iat_send_email",
        'description':  "iatoolkit mail system. "        
            "envia mails cuando un usuario lo solicita.",
         'parameters': {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "email del destinatario"},
                "subject": {"type": "string", "description": "asunto del email"},
                "body": {"type": "string", "description": "HTML del email"},
                "attachments": {
                    "type": "array",
                    "description": "Lista de archivos adjuntos codificados en base64",
                    "items": {
                      "type": "object",
                      "properties": {
                        "filename": {
                          "type": "string",
                          "description": "Nombre del archivo con su extensión (ej. informe.pdf)"
                        },
                        "content": {
                          "type": "string",
                          "description": "Contenido del archivo en b64."
                        },
                        "attachment_token": {
                          "type": "string",
                          "description": "token para descargar el archivo."
                        }
                      },
                      "required": ["filename", "content", "attachment_token"],
                      "additionalProperties": False
                    }
                }
            },
            "required": ["recipient", "subject", "body", "attachments"]
        }
     }
]
