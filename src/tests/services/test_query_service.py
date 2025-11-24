# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch, ANY
import os
import base64
from iatoolkit.services.query_service import QueryService, HistoryHandle
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.history_manager_service import HistoryManagerService
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
    Test suite for the refactored QueryService using HistoryManagerService Strategy and HistoryHandle.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a consistent, mocked environment for each test."""
        # --- Mocks para todas las dependencias ---
        self.mock_llm_client = MagicMock(spec=llmClient)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_document_service = MagicMock()
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_company_context_service = MagicMock(spec=CompanyContextService)
        self.mock_configuration_service = MagicMock(spec=ConfigurationService)
        self.mock_util = MagicMock(spec=Utility)
        self.mock_dispatcher = MagicMock(spec=Dispatcher)
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        # Mock directo del HistoryManagerService (ya no hay factory)
        self.mock_history_manager = MagicMock(spec=HistoryManagerService)

        # --- Instancia del servicio bajo prueba ---
        self.service = QueryService(
            llm_client=self.mock_llm_client,
            profile_service=self.mock_profile_service,
            company_context_service=self.mock_company_context_service,
            document_service=self.mock_document_service,
            profile_repo=self.mock_profile_repo,
            prompt_service=self.mock_prompt_service,
            i18n_service=self.mock_i18n_service,
            util=self.mock_util,
            dispatcher=self.mock_dispatcher,
            session_context=self.mock_session_context,
            configuration_service=self.mock_configuration_service,
            history_manager=self.mock_history_manager
        )

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

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
        """Prueba que prepare_context devuelve 'rebuild_needed: False' si la versión coincide."""
        mock_version = "v_hash_123"
        user_identifier = str(MOCK_LOCAL_USER_ID)
        with patch.object(self.service, '_compute_context_version_from_string', return_value=mock_version):
            self.mock_session_context.get_context_version.return_value = mock_version

            result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=user_identifier)

        assert result == {'rebuild_needed': False}
        self.service._build_context_and_profile.assert_called_once_with(MOCK_COMPANY_SHORT_NAME, user_identifier)
        self.mock_session_context.save_prepared_context.assert_called_once()

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

    # --- Tests para set_context_for_llm ---

    def test_set_context_for_llm_delegates_to_manager(self):
        """Prueba que set_context_for_llm usa el manager para inicializar el contexto."""
        mock_version = "v_prep_abc"
        self.mock_session_context.acquire_lock.return_value = True
        self.mock_session_context.get_and_clear_prepared_context.return_value = (self.mock_final_context, mock_version)

        self.mock_configuration_service.get_configuration.return_value = {'model': 'gpt-test'}
        self.mock_history_manager.initialize_context.return_value = {'response_id': 'init_123'}

        result = self.service.set_context_for_llm(MOCK_COMPANY_SHORT_NAME, user_identifier=str(MOCK_LOCAL_USER_ID))

        # Verifica que se delegó la inicialización al manager inyectado
        self.mock_history_manager.initialize_context.assert_called_once()

        # Verifica persistencia de versión y release de lock
        self.mock_session_context.save_context_version.assert_called_once()
        self.mock_session_context.release_lock.assert_called_once()
        assert result == {'response_id': 'init_123'}

    def test_set_context_for_llm_does_nothing_if_lock_not_acquired(self):
        """Prueba que set_context_for_llm no hace nada si no puede adquirir el lock."""
        self.mock_session_context.acquire_lock.return_value = False

        self.service.set_context_for_llm(MOCK_COMPANY_SHORT_NAME, user_identifier=str(MOCK_LOCAL_USER_ID))

        self.mock_history_manager.initialize_context.assert_not_called()
        self.mock_session_context.release_lock.assert_not_called()

    # --- Tests para init_context ---
    def test_init_context_orchestrates_clearing_and_rebuilding(self):
        """Prueba que init_context llama a los métodos correctos en la secuencia correcta."""
        with patch.object(self.service, 'prepare_context') as mock_prepare, \
                patch.object(self.service, 'set_context_for_llm',
                             return_value={'response_id': 'new_id_123'}) as mock_set_context:
            result = self.service.init_context(
                company_short_name=MOCK_COMPANY_SHORT_NAME,
                user_identifier=str(MOCK_LOCAL_USER_ID),
                model="gpt-test-model"
            )

        self.mock_session_context.clear_all_context.assert_called_once()
        mock_prepare.assert_called_once()
        mock_set_context.assert_called_once()
        assert result == {'response_id': 'new_id_123'}

    # --- Tests para llm_query ---

    def test_llm_query_happy_path(self):
        """Prueba una llamada a llm_query cuando el historial es válido usando HistoryHandle."""

        # Mock side effect to populate the handle request params
        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': 'existing_id'}
            return False  # No rebuild needed

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect

        # Simular respuesta válida del LLM
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'Hello'}

        self.service.llm_query(company_short_name=MOCK_COMPANY_SHORT_NAME,
                               user_identifier=str(MOCK_LOCAL_USER_ID),
                               question="Hi",
                               model='gpt-test')

        # 1. Verifica que se llamó a populate_request_params con un Handle
        self.mock_history_manager.populate_request_params.assert_called_once()
        call_args = self.mock_history_manager.populate_request_params.call_args
        handle_arg = call_args[0][0]
        assert isinstance(handle_arg, HistoryHandle)
        assert handle_arg.company_short_name == MOCK_COMPANY_SHORT_NAME

        # 2. Se invoca al cliente con los parámetros extraídos del handle
        self.mock_llm_client.invoke.assert_called_once()
        kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert kwargs['previous_response_id'] == 'existing_id'
        assert kwargs['context_history'] is None

        # 3. Se actualiza el historial pasando el handle
        # self.mock_history_manager.update_history.assert_called_once()
        # update_args = self.mock_history_manager.update_history.call_args
        #assert update_args[0][0] == handle_arg  # El primer argumento debe ser el handle

    def test_llm_query_rebuilds_context_if_missing(self):
        """Prueba que llm_query reconstruye el contexto automáticamente si populate_request_params lo indica."""

        # Setup side effect to simulate rebuild logic
        # Call 1: Returns True (needs rebuild), handle params empty
        # Call 2: Returns False (ok), populates handle params
        def populate_side_effect(handle, prompt, ignore):
            if self.mock_history_manager.populate_request_params.call_count == 1:
                return True
            handle.request_params = {'previous_response_id': 'new_id'}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True}

        with patch.object(self.service, 'prepare_context') as mock_prepare, \
                patch.object(self.service, 'set_context_for_llm') as mock_set_context:
            self.service.llm_query(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                   user_identifier=str(MOCK_LOCAL_USER_ID),
                                   question="Hi")

            # Verificar que se intentó reconstruir
            mock_prepare.assert_called_once()
            mock_set_context.assert_called_once()

            # Verificar que se llamó a populate_request_params dos veces
            assert self.mock_history_manager.populate_request_params.call_count == 2

            # Verificar que finalmente se invocó con el nuevo ID
            kwargs = self.mock_llm_client.invoke.call_args.kwargs
            assert kwargs['previous_response_id'] == 'new_id'

    def test_llm_query_fails_if_rebuild_fails(self):
        """Prueba que devuelve error si la reconstrucción falla (populate sigue devolviendo True)."""
        # Siempre devuelve True
        self.mock_history_manager.populate_request_params.return_value = True

        with patch.object(self.service, 'prepare_context'), \
                patch.object(self.service, 'set_context_for_llm'):
            result = self.service.llm_query(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                            user_identifier=str(MOCK_LOCAL_USER_ID),
                                            question="Hi")

            assert result['error'] is True
            assert "translated:errors.services.context_rebuild_failed" in result['error_message']
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