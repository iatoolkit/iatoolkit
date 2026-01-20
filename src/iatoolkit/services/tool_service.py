# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.repositories.models import Company, Tool
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.visual_tool_service import VisualToolService


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
        "description": "Servicio SQL de IAToolkit: debes utilizar este servicio para todas las consultas SQL a bases de datos.",
        "parameters": {
            "type": "object",
            "properties": {
                "database_key": {
                    "type": "string",
                    "description": "IMPORTANT: nombre de la base de datos a consultar."
                },
                "query": {
                    "type": "string",
                    "description": "string con la consulta en sql"
                },
            },
            "required": ["database_key", "query"]
        }
    },
    {
        "function_name": "iat_image_search",
        "description": "Busca imágenes en la base de conocimiento visual de la empresa usando una descripción de texto. "
                       "Útil cuando el usuario pide 'ver' algo, 'muéstrame una foto de...', o busca gráficos y diagramas."
                    "",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Descripción detallada de la imagen que se busca (ej: 'foto de la fachada del edificio')."
                },
                "collection": {
                    "type": "string",
                    "description": "Opcional. Nombre de la colección donde buscar (ej: 'Planos', 'Marketing')."
                }
            },
            "required": ["query", "collection"]
        }
    },
    {
        "function_name": "iat_visual_search",
        "description": "Busca imágenes visualmente similares a una imagen adjunta por el usuario (búsqueda por similitud visual). "
                       "Si el usuario adjunta una imagen y solicita buscar algo similar debes utilizar este servicio.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_index": {
                    "type": "integer",
                    "description": "Opcional. Índice (0-based) de la imagen adjunta a usar. Por defecto es 0 (la primera imagen)."
                },
                "n_results": {
                    "type": "integer",
                    "description": "Cantidad de resultados a devolver (por defecto 3).",
                    "minimum": 1,
                    "maximum": 5
                }
            },
            "required": ["n_results", "image_index"]
        }
    },
]

class ToolService:
    @inject
    def __init__(self,
                 llm_query_repo: LLMQueryRepo,
                 visual_kb_service: VisualKnowledgeBaseService,
                 visual_tool_service: VisualToolService,
                 profile_repo: ProfileRepo,
                 sql_service: SqlService,
                 excel_service: ExcelService,
                 mail_service: MailService):
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.sql_service = sql_service
        self.excel_service = excel_service
        self.mail_service = mail_service
        self.visual_kb_service = visual_kb_service
        self.visual_tool_service = visual_tool_service

        # execution mapper for system tools
        self.system_handlers = {
            "iat_generate_excel": self.excel_service.excel_generator,
            "iat_send_email": self.mail_service.send_mail,
            "iat_sql_query": self.sql_service.exec_sql,
            "iat_image_search": self.visual_tool_service.image_search,
            "iat_visual_search": self.visual_tool_service.visual_search,
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

    def sync_company_tools(self, company_short_name: str, tools_config: list):
        """
        Synchronizes tools from YAML config to Database (Create/Update/Delete strategy).
        """
        if not tools_config:
            return

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f'Company {company_short_name} not found')

        try:
            # 1. Get existing tools map for later cleanup
            existing_tools = {
                f.name: f for f in self.llm_query_repo.get_company_tools(company)
            }
            defined_tool_names = set()

            # 2. Sync (Create or Update) from Config
            for tool_data in tools_config:
                name = tool_data['function_name']
                defined_tool_names.add(name)

                # Construct the tool object with current config values
                # We create a new transient object and let the repo merge it
                tool_obj = Tool(
                    company_id=company.id,
                    name=name,
                    description=tool_data['description'],
                    parameters=tool_data['params'],
                    system_function=False
                )

                # Always call create_or_update. The repo handles checking for existence by name.
                self.llm_query_repo.create_or_update_tool(tool_obj)

            # 3. Cleanup: Delete tools present in DB but not in Config
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

        # get all the tools for the company and system
        company_tools = self.llm_query_repo.get_company_tools(company)

        for function in company_tools:
            # clone for no modify the SQLAlchemy session object
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
