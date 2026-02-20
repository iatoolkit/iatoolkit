# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
import os
import json
from urllib.parse import urlparse
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
    HTTP_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    HTTP_ALLOWED_BODY_MODES = {"none", "json_map", "full_args"}
    HTTP_ALLOWED_AUTH_TYPES = {"none", "bearer", "api_key_header", "api_key_query", "basic"}
    HTTP_ALLOWED_RESPONSE_MODES = {"json", "text", "raw"}

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
            "iat_image_search": self._handle_image_search_tool,
            "iat_visual_search": self._handle_visual_search_tool,
            "iat_document_search": self._handle_document_search_tool
        }

    def _handle_document_search_tool(self,
                                     company_short_name: str,
                                     query: str,
                                     collection: str = None,
                                     metadata_filter=None,
                                     n_results: int = 5,
                                     **kwargs):
        chunks = self.knowledge_base_service.search(
            company_short_name=company_short_name,
            query=query,
            n_results=n_results,
            collection=collection,
            metadata_filter=metadata_filter,
        )
        typed_chunks = self._normalize_chunks_for_tool(chunks)

        return {
            "status": "success",
            "query": query,
            "collection": collection,
            "count": len(typed_chunks),
            "chunks": typed_chunks,
            "serialized_context": self._serialize_document_chunks(typed_chunks),
        }

    def _handle_image_search_tool(self,
                                  company_short_name: str,
                                  query: str,
                                  collection: str = None,
                                  metadata_filter=None,
                                  n_results: int = 5,
                                  request_images: list | None = None,
                                  **kwargs):
        return self.visual_tool_service.image_search(
            company_short_name=company_short_name,
            query=query,
            collection=collection,
            metadata_filter=metadata_filter,
            request_images=request_images or [],
            n_results=n_results,
            structured_output=True,
        )

    def _handle_visual_search_tool(self,
                                   company_short_name: str,
                                   request_images: list,
                                   n_results: int = 5,
                                   image_index: int = 0,
                                   collection: str = None,
                                   metadata_filter=None,
                                   **kwargs):
        return self.visual_tool_service.visual_search(
            company_short_name=company_short_name,
            request_images=request_images,
            n_results=n_results,
            image_index=image_index,
            collection=collection,
            metadata_filter=metadata_filter,
            structured_output=True,
        )

    @staticmethod
    def _serialize_document_chunks(chunks: list[dict]) -> str:
        if not chunks:
            return "No chunks found."

        max_chars = int(os.getenv("TOOL_SERIALIZED_CONTEXT_MAX_CHARS", "12000"))
        lines = []

        for index, item in enumerate(chunks, start=1):
            chunk_meta = item.get("chunk_meta") or {}
            doc_meta = item.get("meta") or {}
            source_type = chunk_meta.get("source_type", "unknown")
            filename = item.get("filename", "unknown")
            document_url = item.get("url")
            filename_link = ToolService._to_markdown_link(filename, document_url)
            page = chunk_meta.get("page") or chunk_meta.get("page_start")
            caption = chunk_meta.get("caption_text")

            header = {
                "index": index,
                "filename": filename_link,
                "filename_raw": filename,
                "document_url": document_url,
                "source_type": source_type,
                "page": page,
                "caption_text": caption,
                "document_id": item.get("document_id"),
            }
            lines.append(json.dumps(header, ensure_ascii=False))
            text_content = (item.get("text") or "").strip()
            if text_content:
                lines.append(text_content)

            if source_type == "table":
                table_json = chunk_meta.get("table_json")
                if table_json:
                    lines.append(f"table_json={table_json}")

            # include a small JSON summary of doc metadata for traceability
            if doc_meta:
                lines.append(f"doc_meta={json.dumps(doc_meta, ensure_ascii=False)}")

            lines.append("")

        serialized = "\n".join(lines).strip()
        if len(serialized) <= max_chars:
            return serialized

        truncated = serialized[:max_chars]
        return f"{truncated}\n...[truncated]"

    @staticmethod
    def _normalize_chunks_for_tool(chunks: list[dict]) -> list[dict]:
        normalized = []
        for item in chunks or []:
            chunk = dict(item)
            chunk_meta = dict(chunk.get("chunk_meta") or {})

            table_json = chunk_meta.get("table_json")
            if isinstance(table_json, str) and table_json.strip():
                try:
                    chunk_meta["table_json"] = json.loads(table_json)
                except Exception:
                    # keep original string if it cannot be decoded
                    pass

            filename = chunk.get("filename", "unknown")
            document_url = chunk.get("url")
            chunk["filename_link"] = ToolService._to_markdown_link(filename, document_url)
            chunk["chunk_meta"] = chunk_meta
            normalized.append(chunk)
        return normalized

    @staticmethod
    def _to_markdown_link(label: str, url: str | None) -> str:
        text = label or "unknown"
        if not url:
            return text
        return f"[{text}]({url})"

    def _validate_tool_contract(self, tool_type: str, execution_config):
        if tool_type != Tool.TYPE_HTTP:
            return

        if execution_config is None:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "execution_config is required for HTTP tools"
            )

        self._validate_http_execution_config(execution_config)

    def _validate_http_execution_config(self, execution_config):
        if not isinstance(execution_config, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "execution_config must be a JSON object"
            )

        version = execution_config.get("version")
        if version != 1:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "execution_config.version must be 1"
            )

        request_cfg = execution_config.get("request")
        if not isinstance(request_cfg, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "execution_config.request must be a JSON object"
            )

        method = str(request_cfg.get("method", "")).upper()
        if method not in self.HTTP_ALLOWED_METHODS:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"execution_config.request.method must be one of {sorted(self.HTTP_ALLOWED_METHODS)}"
            )

        url = request_cfg.get("url")
        if not isinstance(url, str) or not url.strip():
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "execution_config.request.url is required and must be a non-empty string"
            )

        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "execution_config.request.url must be an absolute HTTPS URL"
            )

        timeout_ms = request_cfg.get("timeout_ms")
        if timeout_ms is not None:
            if not isinstance(timeout_ms, int) or timeout_ms <= 0 or timeout_ms > 120000:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.request.timeout_ms must be an integer between 1 and 120000"
                )

        for dict_key in ("path_params", "query_params", "headers"):
            value = request_cfg.get(dict_key)
            if value is not None and not isinstance(value, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"execution_config.request.{dict_key} must be a JSON object"
                )

        body_cfg = request_cfg.get("body")
        if body_cfg is not None:
            if not isinstance(body_cfg, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.request.body must be a JSON object"
                )

            body_mode = str(body_cfg.get("mode", "none")).lower()
            if body_mode not in self.HTTP_ALLOWED_BODY_MODES:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"execution_config.request.body.mode must be one of {sorted(self.HTTP_ALLOWED_BODY_MODES)}"
                )
            if body_mode == "json_map" and not isinstance(body_cfg.get("json_map"), dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.request.body.json_map must be a JSON object when mode is 'json_map'"
                )

        auth_cfg = execution_config.get("auth")
        if auth_cfg is not None:
            if not isinstance(auth_cfg, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.auth must be a JSON object"
                )

            auth_type = str(auth_cfg.get("type", "none")).lower()
            if auth_type not in self.HTTP_ALLOWED_AUTH_TYPES:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"execution_config.auth.type must be one of {sorted(self.HTTP_ALLOWED_AUTH_TYPES)}"
                )

            if auth_type == "bearer" and not auth_cfg.get("secret_ref"):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.auth.secret_ref is required for bearer auth"
                )
            if auth_type == "api_key_header":
                if not auth_cfg.get("header_name") or not auth_cfg.get("secret_ref"):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        "execution_config.auth.header_name and secret_ref are required for api_key_header auth"
                    )
            if auth_type == "api_key_query":
                if not auth_cfg.get("query_param") or not auth_cfg.get("secret_ref"):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        "execution_config.auth.query_param and secret_ref are required for api_key_query auth"
                    )
            if auth_type == "basic":
                if not auth_cfg.get("username_secret_ref") or not auth_cfg.get("password_secret_ref"):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        "execution_config.auth.username_secret_ref and password_secret_ref are required for basic auth"
                    )

        response_cfg = execution_config.get("response")
        if response_cfg is not None:
            if not isinstance(response_cfg, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.response must be a JSON object"
                )

            response_mode = str(response_cfg.get("mode", "json")).lower()
            if response_mode not in self.HTTP_ALLOWED_RESPONSE_MODES:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"execution_config.response.mode must be one of {sorted(self.HTTP_ALLOWED_RESPONSE_MODES)}"
                )

            success_codes = response_cfg.get("success_status_codes")
            if success_codes is not None:
                if (not isinstance(success_codes, list) or
                        not success_codes or
                        any(not isinstance(code, int) or code < 100 or code > 599 for code in success_codes)):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        "execution_config.response.success_status_codes must be a non-empty list of HTTP status codes"
                    )

            max_bytes = response_cfg.get("max_response_bytes")
            if max_bytes is not None and (not isinstance(max_bytes, int) or max_bytes <= 0):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.response.max_response_bytes must be a positive integer"
                )

        security_cfg = execution_config.get("security")
        if security_cfg is not None:
            if not isinstance(security_cfg, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.security must be a JSON object"
                )

            allowed_hosts = security_cfg.get("allowed_hosts")
            if allowed_hosts is not None:
                if not isinstance(allowed_hosts, list):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        "execution_config.security.allowed_hosts must be a list"
                    )
                for host in allowed_hosts:
                    if not isinstance(host, str) or not host.strip():
                        raise IAToolkitException(
                            IAToolkitException.ErrorType.INVALID_PARAMETER,
                            "execution_config.security.allowed_hosts must contain non-empty strings"
                        )

            allow_private_network = security_cfg.get("allow_private_network")
            if allow_private_network is True:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "execution_config.security.allow_private_network=true is not supported"
                )

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

        tool = self.llm_query_repo.get_tool_by_id(company.id, tool_id, include_system=True)
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

        tool_type = tool_data.get('tool_type', Tool.TYPE_NATIVE)
        execution_config = tool_data.get('execution_config')
        self._validate_tool_contract(tool_type, execution_config)

        new_tool = Tool(
            company_id=company.id,
            name=tool_data['name'],
            description=tool_data['description'],
            parameters=tool_data.get('parameters', {"type": "object", "properties": {}}),
            execution_config=execution_config,
            tool_type=tool_type,
            source=Tool.SOURCE_USER,
            is_active=tool_data.get('is_active', True)
        )

        # Check for existing name collision within the company
        existing = self.llm_query_repo.get_tool_definition(company, new_tool.name)
        if existing:
            raise IAToolkitException(IAToolkitException.ErrorType.DUPLICATE_ENTRY, f"Tool '{new_tool.name}' already exists.")

        created_tool = self.llm_query_repo.add_tool(new_tool)
        return created_tool.to_dict()

    def update_tool(
        self,
        company_short_name: str,
        tool_id: int,
        tool_data: dict,
        allow_system_update: bool = False
    ) -> dict:
        """Updates an existing tool (Only if source=USER usually, but we allow editing YAML ones locally if needed or override)."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        tool = self.llm_query_repo.get_tool_by_id(company.id, tool_id, include_system=True)
        if not tool:
            raise IAToolkitException(IAToolkitException.ErrorType.NOT_FOUND, "Tool not found")

        # Prevent modifying System tools
        if tool.tool_type == Tool.TYPE_SYSTEM and not allow_system_update:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_OPERATION, "Cannot modify System Tools")

        effective_tool_type = tool_data.get('tool_type', tool.tool_type)
        effective_execution_config = tool_data.get('execution_config', tool.execution_config)
        self._validate_tool_contract(effective_tool_type, effective_execution_config)

        # Update fields
        if 'name' in tool_data:
            tool.name = tool_data['name']
        if 'description' in tool_data:
            tool.description = tool_data['description']
        if 'parameters' in tool_data:
            tool.parameters = tool_data['parameters']
        if 'execution_config' in tool_data:
            tool.execution_config = tool_data['execution_config']
        if 'tool_type' in tool_data:
            tool.tool_type = tool_data['tool_type']
        if 'is_active' in tool_data:
            tool.is_active = tool_data['is_active']

        self.llm_query_repo.commit()
        return tool.to_dict()

    def delete_tool(self, company_short_name: str, tool_id: int):
        """Deletes a tool."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_NAME, "Company not found")

        tool = self.llm_query_repo.get_tool_by_id(company.id, tool_id, include_system=True)
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
