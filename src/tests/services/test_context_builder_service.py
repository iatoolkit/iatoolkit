import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from iatoolkit.services.context_builder_service import ContextBuilderService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.parsers.parsing_service import ParsingService
from iatoolkit.services.tool_service import ToolService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.common.util import Utility
from iatoolkit.repositories.models import Company
import base64

MOCK_COMPANY_SHORT_NAME = "acme"
MOCK_USER_ID = "user123"

class TestContextBuilderService:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        # Mock all dependencies
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_company_context = MagicMock(spec=CompanyContextService)
        self.mock_knowledge_base_service = MagicMock(spec=KnowledgeBaseService)
        self.mock_parsing_service = MagicMock(spec=ParsingService)
        self.mock_tool_service = MagicMock(spec=ToolService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_util = MagicMock(spec=Utility)

        self.service = ContextBuilderService(
            profile_service=self.mock_profile_service,
            profile_repo=self.mock_profile_repo,
            company_context_service=self.mock_company_context,
            parsing_service=self.mock_parsing_service,
            tool_service=self.mock_tool_service,
            knowledge_base_service=self.mock_knowledge_base_service,
            prompt_service=self.mock_prompt_service,
            util=self.mock_util
        )

        self.mock_company = Company(short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_company.id = 1
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company

    def test_build_system_context_success(self):
        """Should correctly assemble company context, rendered system prompt, and return profile."""
        # Arrange
        mock_profile = {"name": "John Doe"}
        self.mock_profile_service.get_profile_by_identifier.return_value = mock_profile
        self.mock_prompt_service.get_system_prompt_payload.return_value = {
            "content": "System Template",
            "selected_keys": ["core_identity", "memory_usage", "output_basics"],
        }
        self.mock_prompt_service.resolve_system_prompt_capabilities.return_value = {
            "can_use_memory",
        }
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"name": "iat_memory_search", "description": "Memory search"},
        ]
        self.mock_knowledge_base_service.get_collection_descriptors.return_value = [
            {"name": "legal", "description": "Contracts and annexes", "parser_provider": "docling"},
            {"name": "support", "description": "Policies and operational manuals", "parser_provider": None},
        ]
        self.mock_util.render_prompt_from_string.return_value = (
            "Rendered System Prompt\n"
            "### Memoria personal\n"
            "If `iat_memory_search` returns a result with `has_native_files=true`, "
            "call `iat_memory_get_page` before answering whenever the attached file contents may matter."
        )
        self.mock_company_context.get_company_context_blocks.return_value = {
            "markdown_context": "Company Business Context",
            "sql_context": "DB Schema Context",
            "yaml_context": "",
        }

        # Act
        context, profile, selected_keys = self.service.build_system_context(MOCK_COMPANY_SHORT_NAME, MOCK_USER_ID)

        # Assert
        assert "Company Business Context" in context
        assert "DB Schema Context" in context
        assert "## Colecciones documentales disponibles" in context
        assert "Usa `iat_document_search` cuando documentos internos de la empresa puedan ayudar a responder al usuario." in context
        assert "### Memoria personal" in context
        assert "has_native_files=true" in context
        assert "- legal: Contracts and annexes" in context
        assert "- support: Policies and operational manuals" in context
        assert "Rendered System Prompt" in context
        assert context.index("Rendered System Prompt") < context.index("Company Business Context")
        assert context.index("Company Business Context") < context.index("## Colecciones documentales disponibles")
        assert context.index("## Colecciones documentales disponibles") < context.index("DB Schema Context")
        assert profile == mock_profile
        assert selected_keys == ["core_identity", "memory_usage", "output_basics"]
        self.mock_util.render_prompt_from_string.assert_called_once()
        self.mock_prompt_service.get_system_prompt_payload.assert_called_once_with(
            company_id=1,
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            query_text=None,
            capabilities_override={"can_use_memory"},
            execution_mode="chat",
            response_mode="chat_compatible",
        )
        self.mock_prompt_service.resolve_system_prompt_capabilities.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            {"can_use_memory"},
        )

    def test_build_system_context_company_not_found(self):
        """Should return None if company does not exist."""
        self.mock_profile_repo.get_company_by_short_name.return_value = None

        context, profile, selected_keys = self.service.build_system_context("unknown", MOCK_USER_ID)

        assert context is None
        assert profile is None
        assert selected_keys == []

    def test_build_system_context_omits_collection_block_when_no_collections(self):
        self.mock_profile_service.get_profile_by_identifier.return_value = {}
        self.mock_prompt_service.get_system_prompt_payload.return_value = {
            "content": "System Template",
            "selected_keys": [],
        }
        self.mock_prompt_service.resolve_system_prompt_capabilities.return_value = set()
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_knowledge_base_service.get_collection_descriptors.return_value = []
        self.mock_util.render_prompt_from_string.return_value = "Rendered System Prompt"
        self.mock_company_context.get_company_context_blocks.return_value = {
            "markdown_context": "",
            "sql_context": "DB Schema Context",
            "yaml_context": "",
        }

        context, _, _ = self.service.build_system_context(MOCK_COMPANY_SHORT_NAME, MOCK_USER_ID)

        assert "Colecciones documentales disponibles" not in context

    def test_build_agent_system_context_uses_only_bound_resources(self):
        mock_profile = {"name": "Agent User"}
        enabled_tools = [
            {"name": "iat_sql_query", "description": "sql"},
            {"name": "iat_document_search", "description": "docs"},
            {"name": "iat_memory_search", "description": "memory"},
        ]
        prompt_contract = {
            "resource_bindings": [
                {"resource_type": "sql_source", "resource_key": "erp"},
                {"resource_type": "rag_collection", "resource_key": "legal"},
            ],
        }

        self.mock_profile_service.get_profile_by_identifier.return_value = mock_profile
        self.mock_prompt_service.get_system_prompt_payload.return_value = {
            "content": "Agent System Template",
            "selected_keys": ["core_identity", "memory_usage", "sql_core"],
        }
        self.mock_prompt_service.resolve_system_prompt_capabilities.return_value = {
            "can_query_sql",
            "can_use_memory",
        }
        self.mock_util.render_prompt_from_string.return_value = "Rendered Agent Prompt\n### Memoria personal"
        self.mock_company_context.get_sql_context.return_value = "Filtered SQL Context"
        self.mock_knowledge_base_service.get_collection_descriptors.return_value = [
            {"name": "legal", "description": "Contracts"},
            {"name": "support", "description": "Policies"},
        ]

        context, profile, selected_keys = self.service.build_agent_system_context(
            MOCK_COMPANY_SHORT_NAME,
            MOCK_USER_ID,
            "research_agent",
            enabled_tools=enabled_tools,
            prompt_output_contract=prompt_contract,
            query_text="explica ventas",
        )

        assert "Filtered SQL Context" in context
        assert "## Colecciones documentales disponibles" in context
        assert "- legal: Contracts" in context
        assert "- support: Policies" not in context
        assert "### Memoria personal" in context
        assert "Rendered Agent Prompt" in context
        assert context.index("Rendered Agent Prompt") < context.index("## Colecciones documentales disponibles")
        assert context.index("## Colecciones documentales disponibles") < context.index("Filtered SQL Context")
        assert profile == mock_profile
        assert selected_keys == ["core_identity", "memory_usage", "sql_core"]
        self.mock_company_context.get_company_context_blocks.assert_not_called()
        self.mock_company_context.get_sql_context.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            allowed_databases=["erp"],
        )
        self.mock_prompt_service.get_system_prompt_payload.assert_called_once_with(
            company_id=1,
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            query_text="explica ventas",
            capabilities_override={"can_query_sql", "can_use_memory"},
            execution_mode="agent",
            response_mode="chat_compatible",
        )
        self.mock_prompt_service.resolve_system_prompt_capabilities.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            {"can_query_sql", "can_use_memory"},
            allowed_sql_databases=["erp"],
        )

    def test_build_user_turn_prompt_basic(self):
        """Should build a simple prompt with a direct question and no files."""
        # Arrange
        question = "Hello world"
        # Mock returning a real dict to be JSON serializable
        self.mock_profile_service.get_profile_by_identifier.return_value = {}

        # Act
        prompt, effective_q, images = self.service.build_user_turn_prompt(
            self.mock_company, MOCK_USER_ID, {}, [], None, question
        )

        # Assert
        assert "Hello world" in prompt
        assert effective_q == question
        assert images == []
        assert "Contexto Adicional" not in prompt

    def test_build_user_turn_prompt_with_template(self):
        """Should render a specific prompt template when prompt_name is provided."""
        # Arrange
        prompt_name = "summarize"
        # FIX: Ensure profile service returns a dict (JSON serializable), not a Mock
        self.mock_profile_service.get_profile_by_identifier.return_value = {}

        self.mock_prompt_service.get_prompt_content.return_value = "Summarize this: {{ question }}"
        self.mock_util.render_prompt_from_string.return_value = "Summarize this: data"

        # Act
        prompt, effective_q, images = self.service.build_user_turn_prompt(
            self.mock_company, MOCK_USER_ID, {}, [], prompt_name, "raw data"
        )

        # Assert
        assert "Summarize this: data" in prompt
        assert "Contexto Adicional" in prompt # Should indicate context injection
        self.mock_prompt_service.get_prompt_content.assert_called_with(self.mock_company, prompt_name)

    def test_process_attachments_separates_images_and_text(self):
        """Should separate image files from text files and decode text."""
        # Arrange
        files = [
            {'filename': 'doc.txt', 'base64': 'dGV4dA=='}, # "text" in b64
            {'filename': 'photo.jpg', 'base64': 'imagebytes'}
        ]
        self.mock_util.normalize_base64_payload.return_value = b'text'
        self.mock_parsing_service.extract_text_for_context.return_value = "Decoded Content"

        # Act
        context, images = self.service._process_attachments(files)

        # Assert
        # Check text context
        assert "<document name='doc.txt'>" in context
        assert "Decoded Content" in context
        assert "photo.jpg" not in context  # Image shouldn't be in text block

        # Check images list
        assert len(images) == 1
        assert images[0]['name'] == 'photo.jpg'
        assert images[0]['base64'] == 'imagebytes'

    def test_process_attachments_handles_errors_gracefully(self):
        """Should append error tags to context if file processing fails, instead of crashing."""
        # Arrange
        files = [{'filename': 'corrupt.pdf', 'base64': '...'}]
        self.mock_parsing_service.extract_text_for_context.side_effect = Exception("Parsing error")

        # Act
        context, images = self.service._process_attachments(files)

        # Assert
        assert "<error>Error al procesar el archivo corrupt.pdf: Parsing error</error>" in context

    def test_process_attachments_decodes_json_and_xml_payloads(self):
        files = [
            {'filename': 'data.json', 'base64': 'eyJhIjoxfQ=='},
            {'filename': 'data.xml', 'base64': 'PHg+MTwveD4='},
        ]

        def normalize_payload(value):
            if value == 'eyJhIjoxfQ==':
                return b'{"a":1}'
            if value == 'PHg+MTwveD4=':
                return b'<x>1</x>'
            return b''

        self.mock_util.normalize_base64_payload.side_effect = normalize_payload

        context, images = self.service._process_attachments(files)

        assert images == []
        assert '"a": 1' in context
        assert '<x>1</x>' in context
        assert 'null' not in context
        assert '"PHg+MTwveD4="' not in context

    def test_process_attachments_can_force_text_extraction_for_images(self):
        files = [{'filename': 'photo.png', 'base64': 'aW1hZ2VieXRlcw==', 'force_text_extraction': True}]
        self.mock_util.normalize_base64_payload.return_value = b'imagebytes'
        self.mock_parsing_service.extract_text_for_context.return_value = "OCR Content"

        context, images = self.service._process_attachments(files)

        assert "OCR Content" in context
        assert images == []

    def test_compute_context_version(self):
        """Should return a SHA256 hash."""
        v1 = self.service.compute_context_version("context A")
        v2 = self.service.compute_context_version("context A")
        v3 = self.service.compute_context_version("context B")

        assert v1 == v2
        assert v1 != v3
        assert len(v1) == 64 # SHA256 length

    def test_get_prompt_output_contract_uses_yaml_when_output_schema_is_null(self):
        self.mock_prompt_service.get_prompt_definition.return_value = SimpleNamespace(
            name="employee_prompt",
            output_schema=None,
            output_schema_yaml="""
type: object
properties:
  employees:
    type: array
    items:
      type: object
required:
  - employees
""",
            output_schema_mode="best_effort",
            output_response_mode="chat_compatible",
            attachment_mode=None,
            attachment_parser_provider=None,
            attachment_fallback=None,
            llm_model=None,
            llm_request_options=None,
            tool_policy=None,
        )
        self.mock_prompt_service.normalize_tool_policy.return_value = {
            "mode": "inherit",
            "tool_names": [],
        }

        contract = self.service.get_prompt_output_contract(self.mock_company, "employee_prompt")

        assert isinstance(contract.get("schema"), dict)
        assert contract["schema"]["type"] == "object"
        assert "employees" in contract["schema"]["properties"]
        assert contract["attachment_mode"] is None
        assert contract["attachment_parser_provider"] is None
        assert contract["attachment_fallback"] is None
        assert contract["llm_model"] is None
        assert contract["llm_request_options"] == {}
        assert contract["tool_policy"] == {"mode": "inherit", "tool_names": []}

    def test_get_prompt_output_contract_accepts_json_string_schema(self):
        self.mock_prompt_service.get_prompt_definition.return_value = SimpleNamespace(
            name="employee_prompt",
            execution_mode="agentic",
            agent_role="channels",
            output_schema='{"type":"object","properties":{"employees":{"type":"array"}}}',
            output_schema_yaml=None,
            output_schema_mode="strict",
            output_response_mode="structured_only",
            attachment_mode="native_only",
            attachment_parser_provider="basic",
            attachment_fallback="fail",
            llm_model="gpt-4.1-mini",
            llm_request_options={
                "reasoning_effort": "high",
                "store": False,
                "prompt_version": "2",
                "prompt_variant": "baseline",
            },
            tool_policy={"mode": "explicit", "tool_names": ["iat_sql_query"]},
            resource_bindings=[
                SimpleNamespace(
                    resource_type="sql_source",
                    resource_key="erp",
                    binding_order=0,
                    metadata_json={"scope": "primary"},
                )
            ],
        )
        self.mock_prompt_service.normalize_tool_policy.return_value = {
            "mode": "explicit",
            "tool_names": ["iat_sql_query"],
        }

        contract = self.service.get_prompt_output_contract(self.mock_company, "employee_prompt")

        assert isinstance(contract.get("schema"), dict)
        assert contract["schema"]["type"] == "object"
        assert contract["schema_mode"] == "strict"
        assert contract["response_mode"] == "structured_only"
        assert contract["execution_mode"] == "agentic"
        assert contract["agent_role"] == "channels"
        assert contract["attachment_mode"] == "native_only"
        assert contract["attachment_parser_provider"] == "basic"
        assert contract["attachment_fallback"] == "fail"
        assert contract["llm_model"] == "gpt-4.1-mini"
        assert contract["llm_request_options"] == {
            "reasoning_effort": "high",
            "store": False,
            "prompt_version": "2",
            "prompt_variant": "baseline",
        }
        assert contract["tool_policy"] == {"mode": "explicit", "tool_names": ["iat_sql_query"]}
        assert contract["resource_bindings"] == [
            {
                "resource_type": "sql_source",
                "resource_key": "erp",
                "binding_order": 0,
                "metadata_json": {"scope": "primary"},
            }
        ]

    def test_get_prompt_output_contract_derives_workspace_agent_as_agentic(self):
        self.mock_prompt_service.get_prompt_definition.return_value = SimpleNamespace(
            name="workspace_ops_prompt",
            execution_mode="conversational",
            agent_role="workspace_agent",
            output_schema=None,
            output_schema_yaml=None,
            output_schema_mode=None,
            output_response_mode=None,
            attachment_mode=None,
            attachment_parser_provider=None,
            attachment_fallback=None,
            llm_model=None,
            llm_request_options=None,
            tool_policy=None,
            resource_bindings=[],
        )

        contract = self.service.get_prompt_output_contract(self.mock_company, "workspace_ops_prompt")

        assert contract["agent_role"] == "workspace_agent"
        assert contract["execution_mode"] == "agentic"

    def test_get_prompt_output_contract_returns_attachment_policy_even_without_schema(self):
        self.mock_prompt_service.get_prompt_definition.return_value = SimpleNamespace(
            name="employee_prompt",
            output_schema=None,
            output_schema_yaml=None,
            output_schema_mode="best_effort",
            output_response_mode="chat_compatible",
            attachment_mode="native_only",
            attachment_parser_provider="docling",
            attachment_fallback="fail",
            llm_model="gpt-4o-mini",
            llm_request_options={"text_verbosity": "low"},
            execution_mode=None,
            agent_role=None,
            resource_bindings=[],
        )

        contract = self.service.get_prompt_output_contract(self.mock_company, "employee_prompt")

        assert contract["prompt_name"] == "employee_prompt"
        assert contract["schema"] is None
        assert contract["execution_mode"] == "conversational"
        assert contract["agent_role"] == "workspace_chat"
        assert contract["attachment_mode"] == "native_only"
        assert contract["attachment_parser_provider"] == "docling"
        assert contract["attachment_fallback"] == "fail"
        assert contract["llm_model"] == "gpt-4o-mini"
        assert contract["llm_request_options"] == {"text_verbosity": "low"}
