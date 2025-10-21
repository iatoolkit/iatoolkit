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


class TestQueryService:
    """
    Test suite for the QueryService, updated for the two-phase context initialization.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up a consistent, mocked environment for each test."""
        # Mocks para dependencias
        self.document_service = MagicMock()
        self.llmquery_repo = MagicMock()
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.prompt_service = MagicMock(spec=PromptService)
        self.utility = MagicMock(spec=Utility)
        self.llm_client_mock = MagicMock(spec=llmClient)
        self.dispatcher = MagicMock()
        self.session_context = MagicMock(spec=UserSessionContextService)

        # --- CORRECCIÓN: Reemplazar la lambda por una función def para máxima robustez ---
        def mock_resolver(external_user_id=None, local_user_id=0):
            if external_user_id:
                return (external_user_id, False)
            if local_user_id:
                return (str(local_user_id), True)
            return (None, False)

        self.utility.resolve_user_identifier.side_effect = mock_resolver

        self.company = Company(id=100, name='Test Company', short_name='test_company')
        self.profile_repo.get_company_by_short_name.return_value = self.company

        # Mocks para los datos que se construirían
        self.mock_final_context = "final_system_context_string"
        self.mock_user_profile = {'user_id': '1', 'user_name': 'Test User'}

        # Mocks de LLM y sesión
        self.llm_client_mock.set_company_context.return_value = 'new_context_id'
        self.mock_llm_response = {"valid_response": True, "answer": "LLM test response",
                                  "response_id": "new_llm_response_id"}
        self.llm_client_mock.invoke.return_value = self.mock_llm_response
        self.session_context.get_profile_data.return_value = self.mock_user_profile

        with patch.dict(os.environ, {"LLM_MODEL": "gpt-test"}):
            self.service = QueryService(
                llm_client=self.llm_client_mock, document_service=self.document_service,
                document_repo=MagicMock(), llmquery_repo=self.llmquery_repo,
                profile_repo=self.profile_repo, prompt_service=self.prompt_service,
                util=self.utility, dispatcher=self.dispatcher, session_context=self.session_context
            )

        # Patch el nuevo método de E/S para aislar los tests
        self.service._build_context_and_profile = MagicMock(return_value=(
            self.mock_final_context, self.mock_user_profile
        ))

        # Contenido de archivos para tests de carga
        self.document_content = b'document content'
        self.base64_content = base64.b64encode(self.document_content)
        yield

    # --- Tests para prepare_context ---

    def test_prepare_context_rebuild_not_needed_when_cache_is_valid(self):
        """Prueba que prepare_context devuelve 'rebuild_needed: False' si la versión y la caché son válidas."""
        user_id = 1
        user_identifier, _ = self.utility.resolve_user_identifier(local_user_id=user_id)
        mock_version = "v_hash_123"

        # Arrange
        with patch.object(self.service, '_compute_context_version_from_string', return_value=mock_version):
            self.session_context.get_context_version.return_value = mock_version
            with patch.object(self.service, '_has_valid_cached_context', return_value=True):
                # Act
                result = self.service.prepare_context(company_short_name='test_company', local_user_id=user_id)

        # Assert
        assert result == {'rebuild_needed': False}
        self.service._build_context_and_profile.assert_called_once()
        self.session_context.save_profile_data.assert_called_once_with('test_company', user_identifier,
                                                                       self.mock_user_profile)
        self.session_context.save_prepared_context.assert_not_called()

    def test_prepare_context_rebuild_needed_due_to_version_mismatch(self):
        """Prueba que se necesita reconstruir si la versión del contexto difiere y guarda el contexto preparado."""
        user_id = 1
        user_identifier, _ = self.utility.resolve_user_identifier(local_user_id=user_id)
        mock_version = "v_hash_new"

        # Arrange
        self.session_context.get_context_version.return_value = "v_hash_old"
        with patch.object(self.service, '_compute_context_version_from_string', return_value=mock_version):
            # Act
            result = self.service.prepare_context(company_short_name='test_company', local_user_id=user_id)

        # Assert
        assert result == {'rebuild_needed': True}
        self.session_context.save_prepared_context.assert_called_once_with(
            'test_company', user_identifier, self.mock_final_context, mock_version
        )

    # --- Tests para finalize_context_rebuild ---

    def test_finalize_context_rebuild_sends_to_llm_when_context_is_prepared(self):
        """Prueba que finalize_context_rebuild envía el contexto al LLM si hay uno preparado."""
        user_id = 1
        user_identifier, _ = self.utility.resolve_user_identifier(local_user_id=user_id)
        mock_version = "v_prep_123"

        # Arrange
        self.session_context.get_and_clear_prepared_context.return_value = (self.mock_final_context, mock_version)
        self.utility.is_openai_model.return_value = True

        # Act
        self.service.finalize_context_rebuild(company_short_name='test_company', local_user_id=user_id)

        # Assert
        self.session_context.get_and_clear_prepared_context.assert_called_once_with('test_company', user_identifier)
        self.session_context.clear_llm_history.assert_called_once()
        self.llm_client_mock.set_company_context.assert_called_once_with(
            company=self.company, company_base_context=self.mock_final_context, model='gpt-test'
        )
        self.session_context.save_last_response_id.assert_called_once_with('test_company', user_identifier,
                                                                           'new_context_id')
        self.session_context.save_context_version.assert_called_once_with('test_company', user_identifier, mock_version)

    def test_finalize_context_rebuild_does_nothing_if_no_context_prepared(self):
        """Prueba que finalize_context_rebuild no hace nada si no hay contexto preparado."""
        # Arrange
        self.session_context.get_and_clear_prepared_context.return_value = (None, None)

        # Act
        self.service.finalize_context_rebuild(company_short_name='test_company', local_user_id=1)

        # Assert
        self.llm_client_mock.set_company_context.assert_not_called()
        self.session_context.save_context_version.assert_not_called()

    # --- Tests para llm_query (Robustez y Auto-reparación) ---

    def test_llm_query_autorepairs_context_if_missing(self):
        """Prueba que llm_query puede reconstruir un contexto faltante 'on-the-fly'."""
        user_id = 1
        # Arrange
        self.session_context.get_last_response_id.side_effect = [None, 'repaired_context_id']
        self.utility.is_openai_model.return_value = True

        with patch.object(self.service, '_init_context_on_the_fly', return_value='repaired_context_id') as mock_repair:
            # Act
            self.service.llm_query(company_short_name='test_company', question='hello', local_user_id=user_id)

            # Assert
            mock_repair.assert_called_once_with('test_company', None, user_id)
            self.llm_client_mock.invoke.assert_called_once()
            assert self.llm_client_mock.invoke.call_args.kwargs['previous_response_id'] == 'repaired_context_id'

    def test_llm_query_fails_gracefully_if_autorepair_fails(self):
        """Prueba que llm_query devuelve un error claro si la auto-reparación del contexto falla."""
        user_id = 1
        user_identifier, _ = self.utility.resolve_user_identifier(local_user_id=user_id)
        # Arrange
        self.session_context.get_last_response_id.return_value = None
        self.utility.is_openai_model.return_value = True
        with patch.object(self.service, '_init_context_on_the_fly', return_value=None):
            # Act
            result = self.service.llm_query(company_short_name='test_company', question='hello', local_user_id=user_id)

            # Assert
            expected_error = f"FATAL: No se encontró 'previous_response_id' para 'test_company/{user_identifier}'. La conversación no puede continuar."
            assert result['error_message'] == expected_error

    # --- Otros Tests de Validación y Flujo ---

    def test_llm_query_fails_if_no_company(self):
        """Prueba que la consulta falla si la compañía no existe."""
        self.profile_repo.get_company_by_short_name.return_value = None
        result = self.service.llm_query(company_short_name='a_company', question="test", external_user_id="test_user")
        assert "No existe Company ID" in result["error_message"]

    def test_load_files_for_context_builds_correctly(self):
        """Prueba que el contexto de archivos se construye correctamente a partir de base64."""
        self.document_service.file_to_txt.return_value = "Text from file"
        files = [{'file_id': 'test.pdf', 'base64': self.base64_content.decode('utf-8')}]
        result = self.service.load_files_for_context(files)

        self.document_service.file_to_txt.assert_called_once_with('test.pdf', self.document_content)
        assert "<document name='test.pdf'>\nText from file\n</document>" in result