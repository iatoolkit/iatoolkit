# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
import os
import base64
import json

from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import User, Company
from iatoolkit.common.util import Utility
from iatoolkit.infra.llm_client import llmClient
from iatoolkit.common.exceptions import IAToolkitException


class TestQueryService:
    """
    Test suite for the QueryService.
    It uses a consistent setup to mock all dependencies and the global `current_iatoolkit` context.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """
        Set up a consistent, mocked environment for each test.
        This includes mocking all dependencies and the global `current_iatoolkit` context.
        """
        # Mocks for all injected dependencies
        self.document_service = MagicMock()
        self.llmquery_repo = MagicMock()
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.prompt_service = MagicMock(spec=PromptService)
        self.utility = MagicMock(spec=Utility)
        self.llm_client_mock = MagicMock(spec=llmClient)
        self.dispatcher = MagicMock()
        self.session_context = MagicMock(spec=UserSessionContextService)


        # --- Common mock configurations ---
        self.utility.resolve_user_identifier.side_effect = lambda external_user_id=None,local_user_id=0: (external_user_id, False) or (f"User_{local_user_id}", True)

        self.user = User(id=1, email='test@user.com')
        self.company = Company(id=100, name='Test Company', short_name='test_company')
        self.profile_repo.get_company_by_short_name.return_value = self.company

        # Default mock session data
        self.session_context.get_last_response_id.return_value = 'prev_response_id'
        self.session_context.get_profile_data.return_value = {'user_role': 'leader', 'user_name': 'session_user'}

        # Default mock LLM response
        self.mock_llm_response = {"valid_response": True, "answer": "LLM test response",
                                  "response_id": "new_llm_response_id"}
        self.llm_client_mock.invoke.return_value = self.mock_llm_response
        self.llm_client_mock.set_company_context.return_value = 'new_context_response_id'

        # Default mock Dispatcher responses
        self.dispatcher.get_user_info.return_value = {'user_role': 'leader', 'user_name': 'test_user'}
        self.dispatcher.get_company_services.return_value = [{'name': 'service1'}]
        self.dispatcher.get_company_context.return_value = "Specific company context."

        # Default prompt rendering
        self.prompt_service.get_system_prompt.return_value = "System prompt template: {{ user_role }}"
        self.utility.render_prompt_from_string.return_value = "Rendered system prompt: leader"

        # Default model type
        self.utility.is_openai_model.return_value = True
        self.utility.is_gemini_model.return_value = False

        # Create the service instance under test. This now works because the context is patched.
        with patch.dict(os.environ, {"LLM_MODEL": "gpt-test"}):
            self.service = QueryService(
                llm_client=self.llm_client_mock,
                document_service=self.document_service,
                document_repo=MagicMock(),
                llmquery_repo=self.llmquery_repo,
                profile_repo=self.profile_repo,
                prompt_service=self.prompt_service,
                util=self.utility,
                dispatcher=self.dispatcher,
                session_context=self.session_context
            )

        # File content for file loading tests
        self.document_content = b'document content'
        self.base64_content = base64.b64encode(self.document_content)

        yield  # The test runs at this point

    # --- Input Validation Tests ---

    def test_llm_query_fails_if_no_company(self):
        """Tests that the query fails if the company does not exist."""
        self.profile_repo.get_company_by_short_name.return_value = None
        result = self.service.llm_query(company_short_name='a_company', question="test", external_user_id="test_user")
        assert "No existe Company ID" in result["error_message"]

    def test_llm_query_fails_if_no_question_or_prompt(self):
        """Tests that the query fails if both question and prompt_name are missing."""
        result = self.service.llm_query(company_short_name='a_company', external_user_id="test_user")
        assert "Hola, cual es tu pregunta?" in result["error_message"]

    def test_llm_query_fails_if_no_previous_response_id_for_openai(self):
        """Tests query failure if no previous response ID is found for OpenAI models."""
        self.session_context.get_last_response_id.return_value = None
        self.llm_client_mock.set_company_context.return_value = None  # Simulate that context initialization also fails
        self.utility.is_openai_model.return_value = True

        result = self.service.llm_query(
            company_short_name='a_company',
            external_user_id="test_user",
            question="test"
        )
        assert "FATAL: No se encontró 'previous_response_id'" in result["error_message"]

    # --- Core Logic Tests ---

    def test_llm_query_with_direct_question_successfully(self):
        """Tests a direct query and the correct management of response IDs in the session."""
        self.utility.is_openai_model.return_value = True

        result = self.service.llm_query(company_short_name='test_company', question='hello',
                                        external_user_id='test_user')

        self.llm_client_mock.invoke.assert_called_once()
        call_args = self.llm_client_mock.invoke.call_args.kwargs
        assert call_args['company'] == self.company
        assert call_args['user_identifier'] == 'test_user'
        assert call_args['previous_response_id'] == 'prev_response_id'
        assert "La pregunta que debes responder es: hello" in call_args['context']

        self.session_context.save_last_response_id.assert_called_once_with(
            'test_company', 'test_user', 'new_llm_response_id'
        )
        assert result['answer'] == 'LLM test response'

    def test_llm_query_with_prompt_name_merges_data_correctly(self):
        """Tests that session data is merged with request data, with the latter taking priority."""
        request_client_data = {'user_name': 'request_user'}
        external_user_id = 'ext_user_2'

        self.service.llm_query(
            company_short_name='a_company',
            external_user_id=external_user_id,
            prompt_name="analisis_cartera",
            client_data=request_client_data
        )

        self.llm_client_mock.invoke.assert_called_once()
        call_kwargs = self.llm_client_mock.invoke.call_args.kwargs

        expected_data = {
            'prompt': 'analisis_cartera',
            'data': {
                'user_role': 'leader',  # From session
                'user_name': 'request_user',  # From request (overwrites session)
                'user_id': external_user_id  # Added by the service
            }
        }

        actual_question_dict = json.loads(call_kwargs['question'])
        assert actual_question_dict == expected_data

    # --- Context Initialization Tests ---

    def test_llm_init_context_happy_path_external_user(self):
        """Tests the successful, full context initialization flow for an external user."""
        self.utility.is_openai_model.return_value = True
        # Forzar build: no hay version previa
        self.session_context.get_context_version.return_value = None

        self.service.llm_init_context(
            company_short_name='test_co',
            external_user_id='ext_user_123'
        )

        # No reutiliza: debe limpiar y construir
        self.session_context.clear_all_context.assert_called_once_with(
            company_short_name='test_co', user_identifier='ext_user_123'
        )
        # Se guarda user session data (ya ocurre antes del guard en tu versión final)
        self.session_context.save_profile_data.assert_called_with(
            'test_co', 'ext_user_123', self.dispatcher.get_user_info.return_value
        )
        self.llm_client_mock.set_company_context.assert_called_once()
        self.session_context.save_last_response_id.assert_called_once_with(
            'test_co', 'ext_user_123', 'new_context_response_id'
        )
        # Se guarda la versión de contexto
        self.session_context.save_context_version.assert_called_once()
        args, kwargs = self.session_context.save_context_version.call_args
        assert args[0] == 'test_co'
        assert args[1] == 'ext_user_123'
        assert isinstance(args[2], str) and len(args[2]) > 0  # hash

    def test_llm_init_context_reuses_when_version_matches_openai(self):
        """When version matches and cached state is valid, it should reuse context (OpenAI)."""
        self.utility.is_openai_model.return_value = True
        # Simular misma versión: el hash que calcule será el mismo si no cambiamos mocks
        fake_version = "vhash123"
        self.session_context.get_context_version.return_value = fake_version
        # Estado válido
        self.session_context.get_last_response_id.return_value = 'prev_response_id'

        # Mockear el cómputo del hash para que coincida
        with patch.object(self.service, "_compute_context_version_from_string", return_value=fake_version):
            result = self.service.llm_init_context(
                company_short_name='test_co',
                external_user_id='ext_user_123'
            )

        # Debe reutilizar: no limpiar ni setear contexto
        self.session_context.clear_all_context.assert_not_called()
        self.llm_client_mock.set_company_context.assert_not_called()
        # Debe devolver el response_id existente o indicador de reuse
        assert result in ('prev_response_id', 'openai-context-reused')

    def test_llm_init_context_rebuilds_when_version_differs_openai(self):
        """If version differs, it should rebuild context (OpenAI)."""
        self.utility.is_openai_model.return_value = True
        # Prev versión distinta
        self.session_context.get_context_version.return_value = "prev_vhash"
        # Hash nuevo distinto
        with patch.object(self.service, "_compute_context_version_from_string", return_value="new_vhash"):
            self.service.llm_init_context(
                company_short_name='test_co',
                external_user_id='ext_user_123'
            )

        self.session_context.clear_all_context.assert_called_once()
        self.llm_client_mock.set_company_context.assert_called_once()
        self.session_context.save_context_version.assert_called_once()
        args, _ = self.session_context.save_context_version.call_args
        assert args[2] == "new_vhash"

    def test_llm_init_context_rebuilds_if_state_missing_even_if_version_matches_openai(self):
        """If version matches but cached state is missing, it should rebuild."""
        self.utility.is_openai_model.return_value = True
        fake_version = "vhash123"
        self.session_context.get_context_version.return_value = fake_version
        # Estado inválido: no hay last_response_id
        self.session_context.get_last_response_id.return_value = None

        with patch.object(self.service, "_compute_context_version_from_string", return_value=fake_version):
            self.service.llm_init_context(
                company_short_name='test_co',
                external_user_id='ext_user_123'
            )

        self.session_context.clear_all_context.assert_called_once()
        self.llm_client_mock.set_company_context.assert_called_once()

    def test_llm_init_context_for_gemini_model(self):
        """Tests that for Gemini models, context is kept in session history and version is saved."""
        self.utility.is_openai_model.return_value = False
        self.utility.is_gemini_model.return_value = True
        # Forzar build: no hay version previa
        self.session_context.get_context_version.return_value = None

        response = self.service.llm_init_context(
            company_short_name='test_co',
            external_user_id='ext_user_123',
            model="gemini"
        )

        self.llm_client_mock.set_company_context.assert_not_called()
        self.session_context.save_context_history.assert_called_once()
        self.session_context.save_context_version.assert_called_once()

    def test_llm_init_context_reuses_when_version_matches_gemini(self):
        """When version matches and history exists, it should reuse context (Gemini)."""
        self.utility.is_openai_model.return_value = False
        self.utility.is_gemini_model.return_value = True
        fake_version = "vhash123"
        self.session_context.get_context_version.return_value = fake_version
        # Estado válido: hay al menos 1 mensaje
        self.session_context.get_context_history.return_value = [{"role": "user", "content": "ctx"}]

        with patch.object(self.service, "_compute_context_version_from_string", return_value=fake_version):
            result = self.service.llm_init_context(
                company_short_name='test_co',
                external_user_id='ext_user_123',
                model="gemini"
            )

        self.session_context.clear_all_context.assert_not_called()
        self.session_context.save_context_history.assert_not_called()
    # --- File Loading Tests ---

    @patch('os.path.exists', return_value=False)
    def test_load_files_for_context_handles_nonexistent_file(self, mock_exists):
        """Tests that a non-existent file is handled gracefully."""
        result = self.service.load_files_for_context([{'file_id': 'nonexistent.txt'}])
        assert "no fue encontrado y no pudo ser cargado" in result

    @patch('os.path.exists', return_value=True)
    def test_load_files_for_context_handles_service_exception(self, mock_exists):
        """Tests that exceptions from the document service are caught."""
        self.document_service.file_to_txt.side_effect = Exception("Service failed")
        files = [{'file_id': 'file.pdf', 'base64': self.base64_content.decode('utf-8')}]
        result = self.service.load_files_for_context(files)
        assert "Error al procesar el archivo file.pdf" in result

    @patch('os.path.exists', return_value=True)
    def test_load_files_for_context_builds_correctly(self, mock_exists):
        """Tests that file context is built correctly from base64 content."""
        self.document_service.file_to_txt.return_value = "Text from file"
        files = [{'file_id': 'test.pdf', 'base64': self.base64_content.decode('utf-8')}]
        result = self.service.load_files_for_context(files)

        self.document_service.file_to_txt.assert_called_once_with('test.pdf', self.document_content)
        expected_context = """
            A continuación encontraras una lista de documentos adjuntos
            enviados por el usuario que hace la pregunta, 
            en total son: 1 documentos adjuntos
            
<document name='test.pdf'>
Text from file
</document>
"""
        assert result == expected_context