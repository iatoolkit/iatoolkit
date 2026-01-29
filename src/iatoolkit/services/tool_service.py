# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.models import Company, Tool
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.visual_tool_service import VisualToolService
from iatoolkit.services.system_tools import SYSTEM_TOOLS_DEFINITIONS
from iatoolkit import current_iatoolkit


class ToolService:
    @inject
    def __init__(self,
                 llm_query_repo: LLMQueryRepo,
                 knowledge_base_service: KnowledgeBaseService,
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
        self.knowledge_base_service = knowledge_base_service
        self.visual_kb_service = visual_kb_service
        self.visual_tool_service = visual_tool_service

        # execution mapper for system tools
        self.system_handlers = {
            "iat_generate_excel": self.excel_service.excel_generator,
            "iat_send_email": self.mail_service.send_mail,
            "iat_sql_query": self.sql_service.exec_sql,
            "iat_image_search": self.visual_tool_service.image_search,
            "iat_visual_search": self.visual_tool_service.visual_search,
            "iat_document_search": self.knowledge_base_service.search_raw
        }

    def register_system_tools(self):
        """
        Creates or updates system functions in the database.
        Called by the init_company cli command, the IAToolkit bootstrap process.
        """
        try:
            # delete all system tools
            self.llm_query_repo.delete_system_tools()

            # create new system tools
            for function in SYSTEM_TOOLS_DEFINITIONS:
                new_tool = Tool(
                    company_id=None,
                    name=function['function_name'],
                    description=function['description'],
                    parameters=function['parameters'],
                    tool_type=Tool.TYPE_SYSTEM,
                    source=Tool.SOURCE_SYSTEM
                )
                self.llm_query_repo.create_or_update_tool(new_tool)

            self.llm_query_repo.commit()
        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def sync_company_tools(self, company_short_name: str, tools_config: list):
        """
        Synchronizes tools from YAML config to Database.
        Logic:
        - WE ONLY TOUCH TOOLS WHERE source='YAML'.
        - We Upsert tools present in the YAML list.
        - We Delete tools present in DB (source='YAML') but missing in YAML list.
        - We IGNORE tools where source='USER' (GUI) or source='SYSTEM'.
        """

        # enterprise edition has its own tool management
        if not current_iatoolkit().is_community:
            return

        # If config is None (key missing), we assume empty list for safety
        if tools_config is None:
            tools_config = []

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME,
                                     f'Company {company_short_name} not found')

        try:
            # 1. Get all current tools to identify what needs to be deleted
            all_tools = self.llm_query_repo.get_company_tools(company)

            # Set of tool names defined in the current YAML
            yaml_tool_names = set()

            # 2. Sync (Create or Update) from Config
            for tool_data in tools_config:
                name = tool_data['function_name']
                yaml_tool_names.add(name)

                # Tools from YAML are always NATIVE and source=YAML
                tool_obj = Tool(
                    company_id=company.id,
                    name=name,
                    description=tool_data['description'],
                    parameters=tool_data['params'],

                    tool_type=Tool.TYPE_NATIVE,
                    source=Tool.SOURCE_YAML,
                )

                self.llm_query_repo.create_or_update_tool(tool_obj)

            # 3. Cleanup: Delete tools that are managed by YAML but are no longer in the file
            for tool in all_tools:
                if tool.source == Tool.SOURCE_YAML and tool.name not in yaml_tool_names:
                    self.llm_query_repo.delete_tool(tool)

            self.llm_query_repo.commit()

        except Exception as e:
            self.llm_query_repo.rollback()
            raise IAToolkitException(IAToolkitException.ErrorType.DATABASE_ERROR, str(e))

    def list_tools(self, company_short_name: str) -> list[dict]:
        """Returns a list of tools including metadata for the GUI."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        tools = self.llm_query_repo.get_company_tools(company)
        return [t.to_dict() for t in tools]

    def get_tool(self, company_short_name: str, tool_id: int) -> dict:
        """Gets a specific tool by ID."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        tool = self.llm_query_repo.get_tool_by_id(company.id, tool_id)
        if not tool:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "Tool not found")

        return tool.to_dict()

    def create_tool(self, company_short_name: str, tool_data: dict) -> dict:
        """Creates a new tool via API (Source=USER)."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        # Basic Validation
        if not tool_data.get('name') or not tool_data.get('description'):
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER, "Name and Description are required")

        new_tool = Tool(
            company_id=company.id,
            name=tool_data['name'],
            description=tool_data['description'],
            parameters=tool_data.get('parameters', {"type": "object", "properties": {}}),
            tool_type=tool_data.get('tool_type', Tool.TYPE_NATIVE),
            source=Tool.SOURCE_USER,
            is_active=tool_data.get('is_active', True)
        )

        # Check for existing name collision within the company
        existing = self.llm_query_repo.get_tool_definition(company, new_tool.name)
        if existing:
            raise IAToolkitException(IAToolkitException.ErrorType.DUPLICATE_ENTRY, f"Tool '{new_tool.name}' already exists.")

        created_tool = self.llm_query_repo.add_tool(new_tool)
        return created_tool.to_dict()

    def update_tool(self, company_short_name: str, tool_id: int, tool_data: dict) -> dict:
        """Updates an existing tool (Only if source=USER usually, but we allow editing YAML ones locally if needed or override)."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        tool = self.llm_query_repo.get_tool_by_id(company.id, tool_id)
        if not tool:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "Tool not found")

        # Prevent modifying System tools
        if tool.tool_type == Tool.TYPE_SYSTEM:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_OPERATION, "Cannot modify System Tools")

        # Update fields
        if 'name' in tool_data:
            tool.name = tool_data['name']
        if 'description' in tool_data:
            tool.description = tool_data['description']
        if 'parameters' in tool_data:
            tool.parameters = tool_data['parameters']
        if 'is_active' in tool_data:
            tool.is_active = tool_data['is_active']

        self.llm_query_repo.commit()
        return tool.to_dict()

    def delete_tool(self, company_short_name: str, tool_id: int):
        """Deletes a tool."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        tool = self.llm_query_repo.get_tool_by_id(company.id, tool_id)
        if not tool:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "Tool not found")

        if tool.tool_type == Tool.TYPE_SYSTEM:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_OPERATION, "Cannot delete System Tools")

        self.llm_query_repo.delete_tool(tool)

    def get_tool_definition(self, company_short_name: str, tool_name: str) -> Tool:
        """Helper to retrieve tool metadata for the Dispatcher."""
        # Optimization: could be a direct query in Repo
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None

        # 1. Try to find in company tools
        tool = self.llm_query_repo.get_tool_definition(company, tool_name)
        if tool:
            return tool

        # 2. Fallback to system tools
        return self.llm_query_repo.get_system_tool(tool_name)

    def get_tools_for_llm(self, company: Company) -> list[dict]:
        """
        Returns the list of tools (System + Company) formatted for the LLM (OpenAI Schema).
        """
        tools = []

        # get all the tools for the company and system
        company_tools = self.llm_query_repo.get_company_tools(company)

        for function in company_tools:
            if not function.is_active:
                continue

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
