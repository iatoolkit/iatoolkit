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
from iatoolkit.services.attachment_policy_service import AttachmentPolicyService

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
        self.model_registry.get_provider.return_value = "openai"
        self.model_registry.get_history_type.return_value = "server_side"
        self.mock_configuration_service.get_llm_model_config.return_value = None

        # New dependency mock
        self.mock_context_builder = MagicMock(spec=ContextBuilderService)
        self.mock_attachment_policy_service = MagicMock(spec=AttachmentPolicyService)
        self.mock_attachment_policy_service.normalize_mode.side_effect = (
            lambda mode: str(mode or "extracted_only").strip().lower()
            if str(mode or "extracted_only").strip().lower() in {"extracted_only", "native_only", "native_plus_extracted", "auto"}
            else "extracted_only"
        )
        self.mock_attachment_policy_service.normalize_fallback.side_effect = (
            lambda fallback: str(fallback or "extract").strip().lower()
            if str(fallback or "extract").strip().lower() in {"extract", "fail"}
            else "extract"
        )
        self.mock_attachment_policy_service.get_company_default_policy.side_effect = (
            lambda company_short_name: {
                "attachment_mode": "extracted_only",
                "attachment_fallback": "extract",
            }
        )
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = (
            lambda company_short_name, provider, files, policy: {
                "files_for_context": files or [],
                "native_attachments": [],
                "errors": [],
                "policy": {
                    "attachment_mode": (policy or {}).get("attachment_mode") or "extracted_only",
                    "attachment_fallback": (policy or {}).get("attachment_fallback") or "extract",
                },
                "capabilities": {},
                "stats": {
                    "total_files": len(files or []),
                    "native_sent_count": 0,
                    "extract_candidates": len(files or []),
                    "fallback_to_extract": 0,
                    "errors": 0,
                },
            }
        )

        QueryService.clear_tool_selector_hook()

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
            context_builder=self.mock_context_builder,
            attachment_policy_service=self.mock_attachment_policy_service,
        )

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.mock_company = Company(id=1, short_name=MOCK_COMPANY_SHORT_NAME)
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company

        # Configuración común para context builder mock
        self.mock_final_context = "built_system_context_string"
        self.mock_user_profile = {"id": MOCK_LOCAL_USER_ID, "name": "Test User"}

        self.mock_context_builder.build_system_context.return_value = (
            self.mock_final_context, self.mock_user_profile, ["query_main", "format_styles"]
        )
        self.mock_context_builder.get_selected_system_prompt_keys.return_value = ["query_main", "format_styles"]
        self.mock_session_context.get_selected_system_prompt_keys.return_value = ["query_main", "format_styles"]
        self.mock_context_builder.compute_context_version.return_value = "v_hash_123"
        self.mock_configuration_service.get_configuration.return_value = {"model": "company-default-model"}

    # --- Tests para prepare_context ---

    def test_prepare_context_delegates_to_builder_and_saves(self):
        """Prueba que prepare_context usa el builder y guarda el resultado."""
        mock_version = "v_hash_123"

        # Simular que la versión actual coincide con la cacheada (no rebuild needed)
        self.mock_session_context.get_context_version.return_value = mock_version

        result = self.service.prepare_context(MOCK_COMPANY_SHORT_NAME, user_identifier=MOCK_LOCAL_USER_ID)

        # 1. Verifica delegación al builder
        self.mock_context_builder.build_system_context.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID, query_text=None
        )
        self.mock_context_builder.compute_context_version.assert_called_once_with(
            self.mock_final_context
        )

        # 2. Verifica interacción con session context
        self.mock_session_context.save_profile_data.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID, self.mock_user_profile
        )
        self.mock_session_context.save_selected_system_prompt_keys.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME, MOCK_LOCAL_USER_ID, ["query_main", "format_styles"]
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
        assert kwargs["execution_metadata"]["tool_router"]["selected_system_prompt_keys"] == [
            "query_main", "format_styles"
        ]
        self.mock_session_context.get_selected_system_prompt_keys.assert_called_once_with(
            MOCK_COMPANY_SHORT_NAME,
            MOCK_LOCAL_USER_ID,
        )
        self.mock_context_builder.get_selected_system_prompt_keys.assert_not_called()

        # Verificar actualización de historia
        self.mock_history_manager.update_history.assert_called_once()

    def test_llm_query_retries_when_server_side_ignore_history_uses_stale_initial_response_id(self):
        self.model_registry.get_history_type.return_value = "server_side"
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])

        state = {"populate_calls": 0}

        def populate_side_effect(handle, prompt, ignore):
            state["populate_calls"] += 1
            handle.request_params = {
                "previous_response_id": "stale-init-id" if state["populate_calls"] == 1 else "fresh-init-id",
                "context_history": None,
            }
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.side_effect = [
            RuntimeError(
                "Error calling LLM API: Error calling OpenAI API: Error code: 400 - "
                "{'error': {'message': \"Previous response with id 'resp_123' not found.\", "
                "'type': 'invalid_request_error', 'param': 'previous_response_id', "
                "'code': 'previous_response_not_found'}}"
            ),
            {"valid_response": True, "answer": "ok"},
        ]

        with patch.object(self.service, "init_context", return_value={"response_id": "fresh-init-id"}) as init_mock:
            result = self.service.llm_query(
                company_short_name=MOCK_COMPANY_SHORT_NAME,
                user_identifier=MOCK_LOCAL_USER_ID,
                question="Hi",
                model="gpt-test",
                ignore_history=True,
            )

        assert result["valid_response"] is True
        assert self.mock_llm_client.invoke.call_count == 2
        first_invoke = self.mock_llm_client.invoke.call_args_list[0].kwargs
        second_invoke = self.mock_llm_client.invoke.call_args_list[1].kwargs
        assert first_invoke["previous_response_id"] == "stale-init-id"
        assert second_invoke["previous_response_id"] == "fresh-init-id"
        init_mock.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            model="gpt-test",
        )
        assert self.mock_history_manager.update_history.call_count == 1

    def test_llm_query_sends_native_attachments_when_policy_requires_it(self):
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = None
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "schema": None,
            "attachment_mode": "native_only",
            "attachment_fallback": "extract",
        }
        self.mock_attachment_policy_service.build_attachment_plan.return_value = {
            "files_for_context": [],
            "native_attachments": [
                {
                    "name": "sales.csv",
                    "mime_type": "text/csv",
                    "base64": "U0FNUExF",
                }
            ],
            "errors": [],
            "policy": {"attachment_mode": "native_only", "attachment_fallback": "extract"},
            "capabilities": {"supports_native_files": True},
            "stats": {
                "total_files": 1,
                "native_sent_count": 1,
                "extract_candidates": 0,
                "fallback_to_extract": 0,
                "errors": 0,
            },
        }
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])
        self.mock_history_manager.populate_request_params.side_effect = (
            lambda handle, prompt, ignore: setattr(handle, "request_params", {"previous_response_id": None, "context_history": None}) or False
        )
        self.mock_llm_client.invoke.return_value = {"valid_response": True, "answer": "ok"}

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            question="ventas 2025",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            model="gpt-test",
        )

        assert result["valid_response"] is True
        self.mock_context_builder.build_user_turn_prompt.assert_called_once()
        build_kwargs = self.mock_context_builder.build_user_turn_prompt.call_args.kwargs
        assert build_kwargs["files"] == []

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert len(invoke_kwargs["attachments"]) == 1
        assert invoke_kwargs["attachments"][0]["name"] == "sales.csv"
        assert invoke_kwargs["execution_metadata"]["attachments"]["stats"]["native_sent_count"] == 1

    def test_llm_query_returns_error_when_attachment_policy_fails(self):
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = None
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "schema": None,
            "attachment_mode": "native_only",
            "attachment_fallback": "fail",
        }
        self.mock_attachment_policy_service.build_attachment_plan.return_value = {
            "files_for_context": [],
            "native_attachments": [],
            "errors": ["Attachment 'sales.csv' cannot be sent as native file for provider 'openai'."],
            "policy": {"attachment_mode": "native_only", "attachment_fallback": "fail"},
            "capabilities": {"supports_native_files": False},
            "stats": {
                "total_files": 1,
                "native_sent_count": 0,
                "extract_candidates": 0,
                "fallback_to_extract": 0,
                "errors": 1,
            },
        }

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            question="ventas 2025",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            model="gpt-test",
        )

        assert result["error"] is True
        assert "No se pudieron procesar los archivos adjuntos" in result["error_message"]
        self.mock_context_builder.build_user_turn_prompt.assert_not_called()
        self.mock_llm_client.invoke.assert_not_called()

    def test_llm_query_without_prompt_name_uses_company_default_attachment_policy(self):
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = None
        self.mock_attachment_policy_service.get_company_default_policy.side_effect = None
        self.mock_attachment_policy_service.get_company_default_policy.return_value = {
            "attachment_mode": "native_only",
            "attachment_fallback": "fail",
        }
        self.mock_attachment_policy_service.build_attachment_plan.return_value = {
            "files_for_context": [],
            "native_attachments": [{"name": "sales.csv", "mime_type": "text/csv", "base64": "U0FNUExF"}],
            "errors": [],
            "policy": {"attachment_mode": "native_only", "attachment_fallback": "fail"},
            "capabilities": {"supports_native_files": True},
            "stats": {
                "total_files": 1,
                "native_sent_count": 1,
                "extract_candidates": 0,
                "fallback_to_extract": 0,
                "errors": 0,
            },
        }
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])
        self.mock_history_manager.populate_request_params.side_effect = (
            lambda handle, prompt, ignore: setattr(handle, "request_params", {"previous_response_id": None, "context_history": None}) or False
        )
        self.mock_llm_client.invoke.return_value = {"valid_response": True, "answer": "ok"}

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="ventas 2025",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            model="gpt-test",
        )

        assert result["valid_response"] is True
        policy_kwargs = self.mock_attachment_policy_service.build_attachment_plan.call_args.kwargs["policy"]
        assert policy_kwargs["attachment_mode"] == "native_only"
        assert policy_kwargs["attachment_fallback"] == "fail"

    def test_llm_query_without_prompt_name_uses_native_fail_fallback_when_company_defaults_missing(self):
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = None
        self.mock_configuration_service.get_configuration.return_value = {"model": "gpt-test"}
        self.mock_attachment_policy_service.build_attachment_plan.return_value = {
            "files_for_context": [],
            "native_attachments": [{"name": "sales.csv", "mime_type": "text/csv", "base64": "U0FNUExF"}],
            "errors": [],
            "policy": {"attachment_mode": "native_only", "attachment_fallback": "fail"},
            "capabilities": {"supports_native_files": True},
            "stats": {
                "total_files": 1,
                "native_sent_count": 1,
                "extract_candidates": 0,
                "fallback_to_extract": 0,
                "errors": 0,
            },
        }
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])
        self.mock_history_manager.populate_request_params.side_effect = (
            lambda handle, prompt, ignore: setattr(handle, "request_params", {"previous_response_id": None, "context_history": None}) or False
        )
        self.mock_llm_client.invoke.return_value = {"valid_response": True, "answer": "ok"}

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="ventas 2025",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            model="gpt-test",
        )

        assert result["valid_response"] is True
        policy_kwargs = self.mock_attachment_policy_service.build_attachment_plan.call_args.kwargs["policy"]
        assert policy_kwargs["attachment_mode"] == "native_only"
        assert policy_kwargs["attachment_fallback"] == "fail"
        execution_attachments = self.mock_llm_client.invoke.call_args.kwargs["execution_metadata"]["attachments"]
        assert execution_attachments["company_defaults"]["attachment_mode"] == "native_only"
        assert execution_attachments["company_defaults"]["attachment_fallback"] == "fail"

    def test_llm_query_prompt_policy_overrides_company_defaults(self):
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = None
        self.mock_attachment_policy_service.get_company_default_policy.side_effect = None
        self.mock_attachment_policy_service.get_company_default_policy.return_value = {
            "attachment_mode": "native_only",
            "attachment_fallback": "fail",
        }
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "schema": None,
            "attachment_mode": "extracted_only",
            "attachment_fallback": "extract",
        }
        self.mock_attachment_policy_service.build_attachment_plan.return_value = {
            "files_for_context": [{"filename": "sales.csv", "base64": "U0FNUExF"}],
            "native_attachments": [],
            "errors": [],
            "policy": {"attachment_mode": "extracted_only", "attachment_fallback": "extract"},
            "capabilities": {"supports_native_files": True},
            "stats": {
                "total_files": 1,
                "native_sent_count": 0,
                "extract_candidates": 1,
                "fallback_to_extract": 0,
                "errors": 0,
            },
        }
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])
        self.mock_history_manager.populate_request_params.side_effect = (
            lambda handle, prompt, ignore: setattr(handle, "request_params", {"previous_response_id": None, "context_history": None}) or False
        )
        self.mock_llm_client.invoke.return_value = {"valid_response": True, "answer": "ok"}

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            question="ventas 2025",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            model="gpt-test",
        )

        assert result["valid_response"] is True
        policy_kwargs = self.mock_attachment_policy_service.build_attachment_plan.call_args.kwargs["policy"]
        assert policy_kwargs["attachment_mode"] == "extracted_only"
        assert policy_kwargs["attachment_fallback"] == "extract"

    def test_llm_query_with_prompt_name_keeps_legacy_company_fallback_when_defaults_missing(self):
        self.mock_attachment_policy_service.build_attachment_plan.side_effect = None
        self.mock_configuration_service.get_configuration.return_value = {"model": "gpt-test"}
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "schema": None,
            "attachment_mode": None,
            "attachment_fallback": None,
        }
        self.mock_attachment_policy_service.build_attachment_plan.return_value = {
            "files_for_context": [{"filename": "sales.csv", "base64": "U0FNUExF"}],
            "native_attachments": [],
            "errors": [],
            "policy": {"attachment_mode": "extracted_only", "attachment_fallback": "extract"},
            "capabilities": {"supports_native_files": True},
            "stats": {
                "total_files": 1,
                "native_sent_count": 0,
                "extract_candidates": 1,
                "fallback_to_extract": 0,
                "errors": 0,
            },
        }
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "q", [])
        self.mock_history_manager.populate_request_params.side_effect = (
            lambda handle, prompt, ignore: setattr(handle, "request_params", {"previous_response_id": None, "context_history": None}) or False
        )
        self.mock_llm_client.invoke.return_value = {"valid_response": True, "answer": "ok"}

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            question="ventas 2025",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            model="gpt-test",
        )

        assert result["valid_response"] is True
        policy_kwargs = self.mock_attachment_policy_service.build_attachment_plan.call_args.kwargs["policy"]
        assert policy_kwargs["attachment_mode"] == "extracted_only"
        assert policy_kwargs["attachment_fallback"] == "extract"
        execution_attachments = self.mock_llm_client.invoke.call_args.kwargs["execution_metadata"]["attachments"]
        assert execution_attachments["company_defaults"]["attachment_mode"] == "extracted_only"
        assert execution_attachments["company_defaults"]["attachment_fallback"] == "extract"

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

    def test_llm_query_applies_tool_selector_hook_when_registered(self):
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "tool_one", "description": "one", "parameters": {}, "strict": True},
            {"type": "function", "name": "tool_two", "description": "two", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "authors metrics", [])

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        hook_kwargs = {}

        def selector_hook(**kwargs):
            hook_kwargs.update(kwargs)
            return [kwargs["tools"][1]]

        QueryService.register_tool_selector_hook(selector_hook)

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="authors metrics",
            model='gpt-test'
        )

        assert result["valid_response"] is True
        self.mock_llm_client.invoke.assert_called_once()
        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert [tool["name"] for tool in invoke_kwargs["tools"]] == ["tool_two"]
        assert hook_kwargs["company_short_name"] == MOCK_COMPANY_SHORT_NAME
        assert "execution_metadata" in invoke_kwargs
        assert "tool_router" in invoke_kwargs["execution_metadata"]
        assert invoke_kwargs["execution_metadata"]["tool_router"]["selection_mode"] == "router_selected"
        assert hook_kwargs["question"] == "authors metrics"

    def test_llm_query_falls_back_to_all_tools_when_selector_hook_fails(self):
        full_tools = [
            {"type": "function", "name": "tool_one", "description": "one", "parameters": {}, "strict": True},
            {"type": "function", "name": "tool_two", "description": "two", "parameters": {}, "strict": True},
        ]
        self.mock_tool_service.get_tools_for_llm.return_value = full_tools
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "authors metrics", [])

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        def selector_hook(**kwargs):
            _ = kwargs
            raise RuntimeError("selector failure")

        QueryService.register_tool_selector_hook(selector_hook)

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="authors metrics",
            model='gpt-test'
        )

        assert result["valid_response"] is True
        self.mock_llm_client.invoke.assert_called_once()
        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert [tool["name"] for tool in invoke_kwargs["tools"]] == ["tool_one", "tool_two"]
        assert invoke_kwargs["execution_metadata"]["tool_router"]["fallback_reason"] == "hook_error"

    def test_llm_query_uses_prompt_explicit_tool_policy_and_skips_router(self):
        full_tools = [
            {"type": "function", "name": "iat_sql_query", "description": "sql", "parameters": {}, "strict": True},
            {"type": "function", "name": "crm_lookup", "description": "crm", "parameters": {}, "strict": True},
            {"type": "function", "name": "tool_two", "description": "two", "parameters": {}, "strict": True},
        ]
        self.mock_tool_service.get_tools_for_llm.return_value = full_tools
        self.mock_tool_service.get_always_include_tool_names.return_value = ["iat_sql_query"]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "authors metrics", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "tool_policy": {
                "mode": "explicit",
                "tool_names": ["crm_lookup", "missing_tool"],
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        selector_hook = MagicMock(return_value=[full_tools[2]])
        QueryService.register_tool_selector_hook(selector_hook)

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            question="authors metrics",
            model='gpt-test'
        )

        assert result["valid_response"] is True
        selector_hook.assert_not_called()
        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert [tool["name"] for tool in invoke_kwargs["tools"]] == ["iat_sql_query", "crm_lookup"]
        assert invoke_kwargs["execution_metadata"]["tool_router"]["selection_mode"] == "prompt_explicit"
        assert invoke_kwargs["execution_metadata"]["tool_router"]["router_skipped"] is True
        assert invoke_kwargs["execution_metadata"]["tool_router"]["missing_tool_names"] == ["missing_tool"]
        assert "Enabled Tools For This Request" in invoke_kwargs["context"]
        assert "Only the tools listed below are enabled for this request." in invoke_kwargs["context"]

    def test_llm_query_uses_prompt_explicit_empty_tool_policy_without_forced_tools(self):
        full_tools = [
            {"type": "function", "name": "iat_sql_query", "description": "sql", "parameters": {}, "strict": True},
            {"type": "function", "name": "crm_lookup", "description": "crm", "parameters": {}, "strict": True},
        ]
        self.mock_tool_service.get_tools_for_llm.return_value = full_tools
        self.mock_tool_service.get_always_include_tool_names.return_value = ["iat_sql_query"]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "authors metrics", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "tool_policy": {
                "mode": "explicit",
                "tool_names": [],
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        selector_hook = MagicMock(return_value=[full_tools[1]])
        QueryService.register_tool_selector_hook(selector_hook)

        result = self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            question="authors metrics",
            model='gpt-test'
        )

        assert result["valid_response"] is True
        selector_hook.assert_not_called()
        self.mock_tool_service.get_always_include_tool_names.assert_not_called()
        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["tools"] == []
        assert invoke_kwargs["execution_metadata"]["tool_router"]["selection_mode"] == "prompt_explicit"
        assert invoke_kwargs["execution_metadata"]["tool_router"]["router_skipped"] is True
        assert invoke_kwargs["execution_metadata"]["tool_router"]["selected_count"] == 0
        assert invoke_kwargs["execution_metadata"]["tool_router"]["hard_disable_tools"] is True
        assert "Enabled Tools For This Request" in invoke_kwargs["context"]
        assert "No tools are enabled for this request." in invoke_kwargs["context"]

    def test_llm_query_resolves_selected_system_prompt_keys_from_builder_when_session_cache_is_empty(self):
        self.mock_session_context.get_selected_system_prompt_keys.return_value = []
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "tool_one", "description": "one", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "question", [])

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="question",
            model='gpt-test'
        )

        self.mock_context_builder.get_selected_system_prompt_keys.assert_called_once_with(
            self.mock_company,
            query_text="question",
        )
        self.mock_session_context.save_selected_system_prompt_keys.assert_called_with(
            MOCK_COMPANY_SHORT_NAME,
            MOCK_LOCAL_USER_ID,
            ["query_main", "format_styles"],
        )

    def test_llm_query_ignores_invalid_selected_system_prompt_keys_from_session_cache(self):
        self.mock_session_context.get_selected_system_prompt_keys.return_value = MagicMock()
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "tool_one", "description": "one", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.get_selected_system_prompt_keys.return_value = ["query_main"]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "question", [])

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="question",
            model='gpt-test'
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["execution_metadata"]["tool_router"]["selected_system_prompt_keys"] == ["query_main"]

    def test_llm_query_passes_openai_json_schema_text_payload_when_prompt_contract_is_configured(self):
        self.model_registry.get_provider.return_value = "openai"
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "scored_prompt",
            "schema": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                },
            },
            "schema_mode": "strict",
            "response_mode": "structured_only",
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="scored_prompt",
            model="gpt-5"
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert "format" in invoke_kwargs["text"]
        assert invoke_kwargs["text"]["format"]["type"] == "json_schema"
        assert invoke_kwargs["text"]["format"]["strict"] is True
        assert invoke_kwargs["response_contract"]["schema_mode"] == "strict"
        assert invoke_kwargs["response_contract"]["response_mode"] == "structured_only"

    def test_llm_query_uses_prompt_llm_model_when_request_model_is_missing(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_model": "gpt-4.1-mini",
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["model"] == "gpt-4.1-mini"

    def test_llm_query_request_model_takes_precedence_over_prompt_llm_model(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_model": "gpt-4.1-mini",
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["model"] == "gpt-5"

    def test_llm_query_applies_prompt_request_options_for_openai_provider(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {
                "reasoning_effort": "high",
                "store": True,
                "text_verbosity": "high",
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["text"] == {"verbosity": "high"}
        assert invoke_kwargs["reasoning"] == {"effort": "high"}
        assert invoke_kwargs["store"] is True
        assert invoke_kwargs["execution_metadata"]["llm_request_options"]["applied"] == {
            "reasoning_effort": "high",
            "store": True,
            "text_verbosity": "high",
        }

    def test_llm_query_passes_prompt_tracking_metadata(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {
                "prompt_version": "4",
                "prompt_variant": "fewshot",
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["request_metadata"] == {
            "prompt_name": "sales_prompt",
            "prompt_version": "4",
            "prompt_variant": "fewshot",
        }
        assert invoke_kwargs["execution_metadata"]["request_metadata"] == {
            "prompt_name": "sales_prompt",
            "prompt_version": "4",
            "prompt_variant": "fewshot",
        }

    def test_llm_query_uses_default_prompt_tracking_metadata(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {},
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["request_metadata"] == {
            "prompt_name": "sales_prompt",
            "prompt_version": "1",
            "prompt_variant": "default",
        }

    def test_llm_query_ignores_prompt_request_options_for_unsupported_provider(self):
        self.mock_configuration_service.get_llm_model_config.return_value = {"provider": "anthropic"}
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {
                "reasoning_effort": "high",
                "store": False,
                "text_verbosity": "high",
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="claude-3-7-sonnet",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["text"] == {}
        assert invoke_kwargs["reasoning"] is None
        assert invoke_kwargs["store"] is None
        assert invoke_kwargs["execution_metadata"]["llm_request_options"]["ignored"] is True
        assert invoke_kwargs["execution_metadata"]["llm_request_options"]["reason"] == "provider_unsupported"

    def test_llm_query_preserves_store_false_when_history_is_enabled(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {
                "store": False,
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["store"] is False
        assert "store_forced_reason" not in invoke_kwargs["execution_metadata"]["llm_request_options"]

    def test_llm_query_preserves_store_false_when_tools_are_present(self):
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "tool_one", "description": "one", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {
                "store": False,
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
            ignore_history=True,
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["store"] is False
        assert "store_forced_reason" not in invoke_kwargs["execution_metadata"]["llm_request_options"]

    def test_llm_query_allows_store_false_when_history_is_ignored_and_no_tools_are_used(self):
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": None,
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
            "llm_request_options": {
                "store": False,
            },
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gpt-5",
            ignore_history=True,
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["store"] is False
        assert "store_forced_reason" not in invoke_kwargs["execution_metadata"]["llm_request_options"]

    def test_llm_query_passes_gemini_response_schema_payload_when_prompt_contract_is_configured(self):
        self.model_registry.get_provider.return_value = "gemini"
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "sales_prompt",
            "schema": {
                "type": "object",
                "required": ["sales_2025"],
                "properties": {
                    "sales_2025": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
            },
            "schema_mode": "strict",
            "response_mode": "structured_only",
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="sales_prompt",
            model="gemini-2.5-flash"
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert "prompt content" in invoke_kwargs["context"]
        assert "OUTPUT CONTRACT (MANDATORY)" in invoke_kwargs["context"]
        assert "format" not in invoke_kwargs["text"]
        assert invoke_kwargs["text"]["response_mime_type"] == "application/json"
        assert invoke_kwargs["text"]["response_schema"]["required"] == ["sales_2025"]
        assert invoke_kwargs["response_contract"]["schema_mode"] == "strict"
        assert invoke_kwargs["response_contract"]["response_mode"] == "structured_only"

    def test_llm_query_passes_deepseek_json_mode_and_reinforces_required_nested_keys(self):
        self.model_registry.get_provider.return_value = "deepseek"
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "paper_prompt",
            "schema": {
                "type": "object",
                "required": ["multiple_comparison_correction", "evidence"],
                "properties": {
                    "multiple_comparison_correction": {
                        "type": ["string", "null"],
                    },
                    "evidence": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["multiple_comparison_correction"],
                        "properties": {
                            "multiple_comparison_correction": {
                                "type": ["string", "null"],
                            },
                        },
                    },
                },
            },
            "schema_mode": "strict",
            "response_mode": "structured_only",
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="paper_prompt",
            model="deepseek-chat"
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["text"]["response_format"]["type"] == "json_object"
        assert "OUTPUT CONTRACT (MANDATORY)" in invoke_kwargs["context"]
        assert "Every required key must be present exactly once." in invoke_kwargs["context"]
        assert "evidence.multiple_comparison_correction" in invoke_kwargs["context"]
        assert invoke_kwargs["response_contract"]["provider"] == "deepseek"

    def test_llm_query_passes_openai_compatible_json_mode_and_reinforces_required_nested_keys(self):
        self.model_registry.get_provider.return_value = "openai_compatible"
        self.mock_tool_service.get_tools_for_llm.return_value = []
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt content", "question", [])
        self.mock_context_builder.get_prompt_output_contract.return_value = {
            "prompt_name": "paper_prompt",
            "schema": {
                "type": "object",
                "required": ["doi", "evidence"],
                "properties": {
                    "doi": {
                        "type": ["string", "null"],
                    },
                    "evidence": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["doi"],
                        "properties": {
                            "doi": {
                                "type": ["string", "null"],
                            },
                        },
                    },
                },
            },
            "schema_mode": "strict",
            "response_mode": "structured_only",
        }

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            prompt_name="paper_prompt",
            model="meta-llama/Llama-3.1-8B-Instruct"
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["text"]["response_format"]["type"] == "json_object"
        assert "OUTPUT CONTRACT (MANDATORY)" in invoke_kwargs["context"]
        assert "Every required key must be present exactly once." in invoke_kwargs["context"]
        assert "evidence.doi" in invoke_kwargs["context"]
        assert invoke_kwargs["response_contract"]["provider"] == "openai_compatible"

    def test_llm_query_forces_memory_search_for_explicit_memory_intent(self):
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "iat_memory_search", "description": "memory", "parameters": {}, "strict": True},
            {"type": "function", "name": "tool_two", "description": "other", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "usa mi memoria sobre onboarding", [])

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="usa mi memoria sobre onboarding",
            model='gpt-test'
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["tool_choice_override"] == "iat_memory_search"
        assert "call `iat_memory_search` before answering" in invoke_kwargs["context"]
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["reason"] == "fallback_memory_keywords"
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["confidence"] == 0.45
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["should_suggest_memory_search"] is True

    def test_llm_query_does_not_force_memory_search_without_explicit_memory_intent(self):
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "iat_memory_search", "description": "memory", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = ("prompt", "qué opinas del onboarding", [])

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="qué opinas del onboarding",
            model='gpt-test'
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["tool_choice_override"] is None
        assert "tool_policy" not in invoke_kwargs["execution_metadata"]

    def test_llm_query_suggests_memory_search_from_router_memory_ranking_without_forcing_it(self):
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "iat_memory_search", "description": "memory", "parameters": {}, "strict": True},
            {"type": "function", "name": "tool_two", "description": "other", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = (
            "prompt",
            "que tengo pensado para implementar esta semana en iatoolkit",
            [],
        )

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        def selector_hook(**kwargs):
            _ = kwargs
            return {
                "tools": kwargs["tools"],
                "metadata": {
                    "top_k": 8,
                    "selected_tool_names": ["iat_memory_search", "tool_two"],
                    "ranked_tools_preview": [
                        {"name": "iat_memory_search", "score": 0.81},
                        {"name": "tool_two", "score": 0.44},
                    ],
                },
            }

        QueryService.register_tool_selector_hook(selector_hook)
        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="que tengo pensado para implementar esta semana en iatoolkit",
            model='gpt-test'
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["tool_choice_override"] is None
        assert "call `iat_memory_search` before answering" in invoke_kwargs["context"]
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["reason"] == "router_ranked_memory_tool"
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["confidence"] == 0.81
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["should_suggest_memory_search"] is True
        assert invoke_kwargs["execution_metadata"]["tool_policy"]["metadata"] == {
            "memory_tool_rank": 1,
            "top_k": 8,
        }

    def test_llm_query_does_not_suggest_memory_when_document_search_competes(self):
        self.mock_tool_service.get_tools_for_llm.return_value = [
            {"type": "function", "name": "iat_memory_search", "description": "memory", "parameters": {}, "strict": True},
            {"type": "function", "name": "iat_document_search", "description": "docs", "parameters": {}, "strict": True},
        ]
        self.mock_context_builder.build_user_turn_prompt.return_value = (
            "prompt",
            "que dice la documentacion interna sobre onboarding",
            [],
        )

        def populate_side_effect(handle, prompt, ignore):
            handle.request_params = {'previous_response_id': None, 'context_history': None}
            return False

        def selector_hook(**kwargs):
            _ = kwargs
            return {
                "tools": kwargs["tools"],
                "metadata": {
                    "top_k": 8,
                    "selected_tool_names": ["iat_memory_search", "iat_document_search"],
                    "ranked_tools_preview": [
                        {"name": "iat_memory_search", "score": 0.88},
                        {"name": "iat_document_search", "score": 0.84},
                    ],
                },
            }

        QueryService.register_tool_selector_hook(selector_hook)
        self.mock_history_manager.populate_request_params.side_effect = populate_side_effect
        self.mock_llm_client.invoke.return_value = {'valid_response': True, 'answer': 'ok'}

        self.service.llm_query(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_LOCAL_USER_ID,
            question="que dice la documentacion interna sobre onboarding",
            model='gpt-test'
        )

        invoke_kwargs = self.mock_llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["tool_choice_override"] is None
        assert "call `iat_memory_search` before answering" not in invoke_kwargs["context"]
        assert "tool_policy" not in invoke_kwargs["execution_metadata"]
