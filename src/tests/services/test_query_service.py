# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
import os
import base64
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company
from iatoolkit.common.util import Utility
from iatoolkit.infra.llm_client import llmClient
from iatoolkit.services.dispatcher_service import Dispatcher

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test_company"
MOCK_LOCAL_USER_ID = 1
MOCK_EXTERNAL_USER_ID = "ext-user-abc"


class TestQueryService:
    """
    Test suite for the refactored and simplified QueryService.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a consistent, mocked environment for each test."""
        # --- Mocks para todas las dependencias ---
        self.mock_llm_client = MagicMock(spec=llmClient)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_document_service = MagicMock()
        self.mock_llmquery_repo = MagicMock()
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_util = MagicMock(spec=Utility)
        self.mock_dispatcher = MagicMock(spec=Dispatcher)
        self.mock_session_context = MagicMock(spec=UserSessionContextService)

        # --- Instancia del servicio bajo prueba ---
        with patch.dict(os.environ, {"LLM_MODEL": "gpt-test"}):
            self.service = QueryService(
                llm_client=self.mock_llm_client,
                profile_service=self.mock_profile_service,
                document_service=self.mock_document_service,
                document_repo=MagicMock(),
                llmquery_repo=self.mock_llmquery_repo,
                profile_repo=self.mock_profile_repo,
                prompt_service=self.mock_prompt_service,
                util=self.mock_util,
                dispatcher=self.mock_dispatcher,
                session_context=self.mock_session_context
            )


        self.mock_company = Company(id=1, short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company

        # Mock para el método interno que hace la E/S de disco
        self.mock_final_context = "built_context_string"
        self.mock_user_profile = {"id": MOCK_LOCAL_USER_ID, "name": "Test User"}
        self.service._build_context_and_profile = MagicMock(
            return_value=(self.mock_final_context, self.mock_user_profile))

        # Base64 content for file loading tests
        self.base64_content = base64.b64encode(b'document content')

    # --- Tests para prepare_context ---

    def test_prepare_context_rebuild_not_needed(self):
        """Prueba que prepare_context devuelve 'rebuild_needed: False' si la caché es válida."""
        mock_version = "v_hash_123"
        user_identifier = str(MOCK_LOCAL_USER_ID)
        with patch.object(self.service, '_compute_context_version_from_string', return_value=mock_version):
            self.mock_session_context.get_context_version.return_value = mock_version
            with patch.object(self.service, '_has_valid_cached_context', return_value=True):
                result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=user_identifier)

        assert result == {'rebuild_needed': False}
        self.service._build_context_and_profile.assert_called_once_with(MOCK_COMPANY_SHORT_NAME, user_identifier)
        self.mock_session_context.save_prepared_context.assert_not_called()

    def test_prepare_context_rebuild_needed_due_to_version_mismatch(self):
        """Prueba que se necesita reconstruir si la versión del contexto difiere."""
        mock_version = "v_new"
        user_identifier = str(MOCK_LOCAL_USER_ID)
        self.mock_session_context.get_context_version.return_value = "v_old"
        with patch.object(self.service, '_compute_context_version_from_string', return_value=mock_version):
            result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=user_identifier)

        assert result == {'rebuild_needed': True}
        self.mock_session_context.save_prepared_context.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, user_identifier, self.mock_final_context, mock_version
        )

    # --- Tests para finalize_context_rebuild ---

    def test_finalize_rebuild_sends_to_llm_when_prepared(self):
        """Prueba que finalize_context_rebuild envía el contexto al LLM si hay uno preparado."""
        mock_version = "v_prep_abc"
        self.mock_session_context.acquire_lock.return_value = True
        self.mock_session_context.get_and_clear_prepared_context.return_value = (self.mock_final_context, mock_version)
        self.mock_util.is_openai_model.return_value = True

        self.service.finalize_context_rebuild(MOCK_COMPANY_SHORT_NAME, user_identifier=str(MOCK_LOCAL_USER_ID))

        self.mock_session_context.acquire_lock.assert_called_once()
        self.mock_session_context.save_context_version.assert_called_once_with(MOCK_COMPANY_SHORT_NAME,
                                                                               str(MOCK_LOCAL_USER_ID), mock_version)
        self.mock_session_context.release_lock.assert_called_once()

    def test_finalize_rebuild_does_nothing_if_lock_not_acquired(self):
        """Prueba que finalize no hace nada si no puede adquirir el lock."""
        self.mock_session_context.acquire_lock.return_value = False

        self.service.finalize_context_rebuild(MOCK_COMPANY_SHORT_NAME, user_identifier=str(MOCK_LOCAL_USER_ID))

        self.mock_session_context.get_and_clear_prepared_context.assert_not_called()
        self.mock_llm_client.set_company_context.assert_not_called()
        self.mock_session_context.release_lock.assert_not_called()

    # --- Tests para llm_query ---

    def test_llm_query_happy_path(self):
        """Prueba una llamada a llm_query cuando el contexto ya está inicializado."""
        self.mock_session_context.get_last_response_id.return_value = "existing_id"
        self.mock_util.is_openai_model.return_value = True

        self.service.llm_query(company_short_name=MOCK_COMPANY_SHORT_NAME,
                               user_identifier=str(MOCK_LOCAL_USER_ID),
                               question="Hi")

        self.mock_llm_client.invoke.assert_called_once()
        assert self.mock_llm_client.invoke.call_args.kwargs['previous_response_id'] == "existing_id"

    def test_llm_query_fails_if_context_is_missing(self):
        """Prueba que llm_query ahora falla si no hay un contexto inicializado."""
        self.mock_session_context.get_last_response_id.return_value = None
        self.mock_util.is_openai_model.return_value = True

        result = self.service.llm_query(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                        user_identifier=str(MOCK_LOCAL_USER_ID),
                                        question="Hi")

        assert result['error'] is True
        expected_error = f"FATAL: No se encontró 'previous_response_id' para '{MOCK_COMPANY_SHORT_NAME}/{str(MOCK_LOCAL_USER_ID)}'. La conversación no puede continuar."
        assert result['error_message'] == expected_error
        self.mock_llm_client.invoke.assert_not_called()

    # --- Tests para load_files_for_context ---

    def test_load_files_for_context_builds_correctly(self):
        """Prueba que el contexto de archivos se construye correctamente."""
        self.mock_document_service.file_to_txt.return_value = "Text from file"
        files = [{'file_id': 'test.pdf', 'base64': self.base64_content.decode('utf-8')}]

        result = self.service.load_files_for_context(files)

        self.mock_document_service.file_to_txt.assert_called_once()
        assert "<document name='test.pdf'>\nText from file\n</document>" in result
        assert "en total son: 1 documentos adjuntos" in result

    def test_load_files_for_context_handles_missing_content(self):
        """Prueba que se maneja un archivo sin contenido (solo nombre)."""
        files = [{'filename': 'empty.txt'}]  # No 'base64' or 'content' key

        result = self.service.load_files_for_context(files)

        assert "<error>El archivo 'empty.txt' no fue encontrado y no pudo ser cargado.</error>" in result
        self.mock_document_service.file_to_txt.assert_not_called()

    def test_load_files_for_context_handles_processing_error(self):
        """Prueba que se captura una excepción durante el procesamiento del archivo."""
        self.mock_document_service.file_to_txt.side_effect = Exception("PDF rendering failed")
        files = [{'file_id': 'corrupt.pdf', 'base64': self.base64_content.decode('utf-8')}]

        result = self.service.load_files_for_context(files)

        assert "<error>Error al procesar el archivo corrupt.pdf: PDF rendering failed</error>" in result