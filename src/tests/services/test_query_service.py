# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.query_service import QueryService, HistoryHandle
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.context_builder_service import ContextBuilderService
from iatoolkit.repositories.models import Company
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.tool_service import ToolService
from iatoolkit.common.model_registry import ModelRegistry

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test_company"
MOCK_LOCAL_USER_ID = "user-123"


class TestQueryService:
    """
    Test suite for the refactored QueryService.
    Now verifies orchestration and delegation to ContextBuilderService.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a consistent, mocked environment for each test."""
        # --- Mocks para dependencias directas ---
        self.mock_llm_client = MagicMock(spec=llmClient)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_dispatcher = MagicMock(spec=Dispatcher)
        self.mock_tool_service = MagicMock(spec=ToolService)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_configuration_service = MagicMock(spec=ConfigurationService)
        self.mock_history_manager = MagicMock(spec=HistoryManagerService)
        self.model_registry = MagicMock(spec=ModelRegistry)

        # New dependency mock
        self.mock_context_builder = MagicMock(spec=ContextBuilderService)

        # --- Instancia del servicio bajo prueba ---
        self.service = QueryService(
            dispatcher=self.mock_dispatcher,
            tool_service=self.mock_tool_service,
            llm_client=self.mock_llm_client,
            profile_repo=self.mock_profile_repo,
            i18n_service=self.mock_i18n_service,
            session_context=self.mock_session_context,
            configuration_service=self.mock_configuration_service,
            history_manager=self.mock_history_manager,
            model_registry=self.model_registry,
            context_builder=self.mock_context_builder
        )

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.mock_company = Company(id=1, short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company

        # Configuración común para context builder mock
        self.mock_final_context = "built_system_context_string"
        self.mock_user_profile = {"id": MOCK_LOCAL_USER_ID, "name": "Test User"}

        self.mock_context_builder.build_system_context.return_value = (
            self.mock_final_context, self.mock_user_profile
        )
        self.mock_context_builder.compute_context_version.return_value = "v_hash_123"

    # --- Tests para prepare_context ---

    def test_prepare_context_delegates_to_builder_and_saves(self):
        """Prueba que prepare_context usa el builder y guarda el resultado."""
        mock_version = "v_hash_123"

        # Simular que la versión actual coincide con la cacheada (no rebuild needed)
        self.mock_session_context.get_context_version.return_value = mock_version

        result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_LOCAL_USER_ID)

        # 1. Verifica delegación al builder
        self.mock_context_builder.build_system_context.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID
        )
        self.mock_context_builder.compute_context_version.assert_called_once_with(
            self.mock_final_context
        )

        # 2. Verifica interacción con session context
        self.mock_session_context.save_profile_data.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID, self.mock_user_profile
        )
        self.mock_session_context.save_prepared_context.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID, self.mock_final_context, mock_version
        )

        assert result == {'rebuild_needed': False}

    def test_prepare_context_returns_rebuild_needed_on_version_mismatch(self):
        """Prueba que indica reconstrucción si las versiones difieren."""
        self.mock_session_context.get_context_version.return_value = "v_old_version"
        self.mock_context_builder.compute_context_version.return_value = "v_new_version"

        result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_LOCAL_USER_ID)

        assert result == {'rebuild_needed': True}

    def test_prepare_context_handles_builder_failure(self):
        """Prueba que maneja el caso donde el builder no devuelve contexto."""
        self.mock_context_builder.build_system_context.return_value = (None, None)

        result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_LOCAL_USER_ID)

        assert result == {'rebuild_needed': True} # O manejo de error según lógica
        self.mock_session_context.save_prepared_context.assert_not_called()

    # --- Tests para set_context_for_llm ---

    def test_set_context_for_llm_delegates_to_manager(self):
        """Prueba que set_context_for_llm usa el manager para inicializar el contexto."""
        mock_version = "v_prep_abc"
        self.mock_session_context.acquire_lock.return_value = True
        self.mock_session_context.get_and_clear_prepared_context.return_value = (self.mock_final_context, mock_version)

        self.mock_configuration_service.get_configuration.return_value = {'model': 'gpt-test'}
        self.mock_history_manager.initialize_context.return_value = {'response_id': 'init_123'}

        result = self.service.set_context_for_llm(MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_LOCAL_USER_ID)

        # Verifica persistencia de versión y release de lock
        self.mock_session_context.save_context_version.assert_called_once()
        self.mock_session_context.release_lock.assert_called_once()
        assert result == {'response_id': 'init_123'}

    # --- Tests para init_context ---

    def test_init_context_orchestrates_clearing_and_rebuilding(self):
        """Prueba que init_context llama a los métodos correctos en la secuencia correcta."""
        with patch.object(self.service, 'prepare_context') as mock_prepare, \
                patch.object(self.service, 'set_context_for_llm',
                             return_value={'response_id': 'new_id_123'}) as mock_set_context:
            result = self.service.init_context(
                company_short_name=MOCK_COMPANY_SHORT_NAME,
                user_identifier=MOCK_LOCAL_USER_ID,
                model="gpt-test-model"
            )

        self.mock_session_context.clear_all_context.assert_called_once()
        mock_prepare.assert_called_once()
        mock_set_context.assert_called_once()
        assert result == {'response_id': 'new_id_123'}

    # --- Tests para llm_query ---

    def test_llm_query_happy_path(self):
        """Prueba una llamada a llm_query exitosa delegando al builder."""

        # 1. Mock de Context Builder (User Turn)
        user_prompt = "User prompt with context"
        effective_q = "Hi"
        images = []
        self.mock_context_builder.build_user_turn_prompt.return_value = (
            user_prompt, effective_q, images
        )

        # 2. Mock de History Manager
        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': 'existing_id'}
            return False  # No rebuild needed
        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect

        # 3. Mock de LLM Client
        mock_response = {'valid_response': True, 'answer': 'Hello'}
        self.mock_llm_client.invoke.return_value = mock_response

        # Act
        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="Hi",
            model='gpt-test'
        )

        # Assert
        # Verificar llamada al builder
        self.mock_context_builder.build_user_turn_prompt.assert_called_once()

        # Verificar llamada al LLM con los datos del builder
        self.mock_llm_client.invoke.assert_called_once()
        kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert kwargs['context'] == user_prompt
        assert kwargs['question'] == effective_q
        assert kwargs['previous_response_id'] == 'existing_id'

        # Verificar actualización de historia
        self.mock_history_manager.update_history.assert_called_once()

    def test_llm_query_rebuilds_context_if_needed(self):
        """Prueba que llm_query reconstruye el contexto si el history manager lo indica."""

        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])
        self.mock_llm_client.invoke.return_value = {'valid_response': True}

        # Simular: Primer llamada devuelve True (rebuild needed), segunda False (ok)
        self.mock_history_manager.populate_request_params.side_effect = [True, False]

        with patch.object(self.service, 'prepare_context') as mock_prepare, \
                patch.object(self.service, 'set_context_for_llm') as mock_set_context:

            self.service.llm_query(MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID, question="Hi")

            mock_prepare.assert_called_once()
            mock_set_context.assert_called_once()
            assert self.mock_history_manager.populate_request_params.call_count == 2

    def test_llm_query_fails_if_company_not_found(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = None
        result = self.service.llm_query("invalid_company", "user")
        assert result['error'] is True
        assert "translated:errors.company_not_found" in result['error_message']