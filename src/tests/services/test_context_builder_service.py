import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from iatoolkit.services.context_builder_service import ContextBuilderService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.company_context_service import CompanyContextService
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
            "selected_keys": ["query_main", "format_styles"],
        }
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_util.render_prompt_from_string.return_value = "Rendered System Prompt"
        self.mock_company_context.get_company_context.return_value = "DB Schema Context"

        # Act
        context, profile, selected_keys = self.service.build_system_context(MOCK_COMPANY_SHORT_NAME, MOCK_USER_ID)

        # Assert
        assert "DB Schema Context" in context
        assert "Rendered System Prompt" in context
        assert profile == mock_profile
        assert selected_keys == ["query_main", "format_styles"]
        self.mock_util.render_prompt_from_string.assert_called_once()
        self.mock_prompt_service.get_system_prompt_payload.assert_called_once_with(
            company_id=1,
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            query_text=None,
        )

    def test_build_system_context_company_not_found(self):
        """Should return None if company does not exist."""
        self.mock_profile_repo.get_company_by_short_name.return_value = None

        context, profile, selected_keys = self.service.build_system_context("unknown", MOCK_USER_ID)

        assert context is None
        assert profile is None
        assert selected_keys == []

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
        )

        contract = self.service.get_prompt_output_contract(self.mock_company, "employee_prompt")

        assert isinstance(contract.get("schema"), dict)
        assert contract["schema"]["type"] == "object"
        assert "employees" in contract["schema"]["properties"]
        assert contract["attachment_mode"] is None
        assert contract["attachment_parser_provider"] is None
        assert contract["attachment_fallback"] is None

    def test_get_prompt_output_contract_accepts_json_string_schema(self):
        self.mock_prompt_service.get_prompt_definition.return_value = SimpleNamespace(
            name="employee_prompt",
            output_schema='{"type":"object","properties":{"employees":{"type":"array"}}}',
            output_schema_yaml=None,
            output_schema_mode="strict",
            output_response_mode="structured_only",
            attachment_mode="native_only",
            attachment_parser_provider="legacy",
            attachment_fallback="fail",
        )

        contract = self.service.get_prompt_output_contract(self.mock_company, "employee_prompt")

        assert isinstance(contract.get("schema"), dict)
        assert contract["schema"]["type"] == "object"
        assert contract["schema_mode"] == "strict"
        assert contract["response_mode"] == "structured_only"
        assert contract["attachment_mode"] == "native_only"
        assert contract["attachment_parser_provider"] == "legacy"
        assert contract["attachment_fallback"] == "fail"

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
        )

        contract = self.service.get_prompt_output_contract(self.mock_company, "employee_prompt")

        assert contract["prompt_name"] == "employee_prompt"
        assert contract["schema"] is None
        assert contract["attachment_mode"] == "native_only"
        assert contract["attachment_parser_provider"] == "docling"
        assert contract["attachment_fallback"] == "fail"
