# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import Company, Tool
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.license_service import LicenseService


_SYSTEM_TOOLS = [
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
        'description': "iatoolkit mail system. "
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
    },
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
    }
]


class ToolService:
    @inject
    def __init__(self,
                 llm_query_repo: LLMQueryRepo,
                 license_service: LicenseService,
                 sql_service: SqlService,
                 excel_service: ExcelService,
                 mail_service: MailService):
        self.llm_query_repo = llm_query_repo
        self.license_service = license_service
        self.sql_service = sql_service
        self.excel_service = excel_service
        self.mail_service = mail_service

        # execution mapper for system tools
        self.system_handlers = {
            "iat_generate_excel": self.excel_service.excel_generator,
            "iat_send_email": self.mail_service.send_mail,
            "iat_sql_query": self.sql_service.exec_sql
        }

    def register_system_tools(self):
        """Creates or updates system functions in the database."""
        try:
            # delete all system tools
            self.llm_query_repo.delete_system_tools()

            # create new system tools
            for function in _SYSTEM_TOOLS:
                new_tool = Tool(
                    company_id=None,
                    system_function=True,
                    name=function['function_name'],
                    description=function['description'],
                    parameters=function['parameters']
                )
                self.llm_query_repo.create_or_update_tool(new_tool)

            self.llm_query_repo.commit()
        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def sync_company_tools(self, company_instance, tools_config: list):
        """
        Synchronizes tools from YAML config to Database (Create/Update/Delete strategy).
        """
        try:
            # 1. license validation
            # verify if the number of tools in the YAML exceeds the limit
            self.license_service.validate_tool_config_limit(tools_config)

            # 12 Get existing tools map for later cleanup
            existing_tools = {
                f.name: f for f in self.llm_query_repo.get_company_tools(company_instance.company)
            }
            defined_tool_names = set()

            # 3. Sync (Create or Update) from Config
            for tool_data in tools_config:
                name = tool_data['function_name']
                defined_tool_names.add(name)

                # Construct the tool object with current config values
                # We create a new transient object and let the repo merge it
                tool_obj = Tool(
                    company_id=company_instance.company.id,
                    name=name,
                    description=tool_data['description'],
                    parameters=tool_data['params'],
                    system_function=False
                )

                # Always call create_or_update. The repo handles checking for existence by name.
                self.llm_query_repo.create_or_update_tool(tool_obj)

            # 4. Cleanup: Delete tools present in DB but not in Config
            for name, tool in existing_tools.items():
                # Ensure we don't delete system functions or active tools accidentally if logic changes,
                # though get_company_tools filters by company_id so system functions shouldn't be here usually.
                if not tool.system_function and (name not in defined_tool_names):
                    self.llm_query_repo.delete_tool(tool)

            self.llm_query_repo.commit()

        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))


    def get_tools_for_llm(self, company: Company) -> list[dict]:
        """
        Returns the list of tools (System + Company) formatted for the LLM (OpenAI Schema).
        """
        tools = []
        # Obtiene tanto las de la empresa como las del sistema (la query del repo debería soportar esto con OR)
        functions = self.llm_query_repo.get_company_tools(company)

        for function in functions:
            # Clonamos para no modificar el objeto de la sesión SQLAlchemy
            params = function.parameters.copy() if function.parameters else {}
            params["additionalProperties"] = False

            ai_tool = {
                "type": "function",
                "name": function.name,
                "description": function.description,
                "parameters": params,
                "strict": True
            }
            tools.append(ai_tool)
        return tools

    def get_system_handler(self, function_name: str):
        return self.system_handlers.get(function_name)

    def is_system_tool(self, function_name: str) -> bool:
        return function_name in self.system_handlers