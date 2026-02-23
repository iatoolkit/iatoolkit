import unittest
from unittest.mock import MagicMock
from iatoolkit.services.history_manager_service import HistoryManagerService as HistoryManager, HistoryManagerService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.repositories.models import Company, LLMQuery

# Mocking HistoryHandle dynamically to avoid importing QueryService (which has many deps)
from dataclasses import dataclass


class MockHistoryHandle:
    def __init__(self, company_short_name, user_identifier, type_, model=None):
        self.company_short_name = company_short_name
        self.user_identifier = user_identifier
        self.type = type_
        self.model = model
        self.request_params = {}


class TestHistoryManager(unittest.TestCase):

    def setUp(self):
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_i18n = MagicMock(spec=I18nService)
        self.mock_llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_llm_client = MagicMock(spec=llmClient)

        self.manager = HistoryManagerService(
            session_context=self.mock_session_context,
            i18n=self.mock_i18n,
            llm_query_repo=self.mock_llm_query_repo,
            profile_repo=self.mock_profile_repo,
            llm_client=self.mock_llm_client
        )

        self.company_short_name = "test_company"
        self.user_identifier = "user123"
        self.mock_company = Company(id=1, name="Test Company", short_name=self.company_short_name)

    # --- initialize_context Tests ---

    def test_initialize_context_server_side(self):
        """Test initialization for server-side history (e.g., OpenAI)."""
        model = "gpt-4"
        prepared_context = "System prompt"
        fake_response_id = "resp_123"

        self.mock_llm_client.set_company_context.return_value = fake_response_id

        result = self.manager.initialize_context(
            self.company_short_name, self.user_identifier,
            HistoryManager.TYPE_SERVER_SIDE, prepared_context, self.mock_company, model
        )

        # Assertions
        self.mock_session_context.clear_llm_history.assert_called_once_with(self.company_short_name,
                                                                            self.user_identifier,
                                                                            model=model)
        self.mock_llm_client.set_company_context.assert_called_once()
        self.mock_session_context.save_last_response_id.assert_called_with(self.company_short_name,
                                                                           self.user_identifier,
                                                                           fake_response_id,
                                                                           model=model)
        self.assertEqual(result, {'response_id': fake_response_id})

    def test_initialize_context_client_side(self):
        """Test initialization for client-side history (e.g., Gemini)."""
        model = "gemini-pro"
        prepared_context = "System prompt"

        result = self.manager.initialize_context(
            self.company_short_name, self.user_identifier,
            HistoryManager.TYPE_CLIENT_SIDE, prepared_context, self.mock_company, model
        )

        # Assertions
        self.mock_session_context.clear_llm_history.assert_called_once()
        expected_history = [{"role": "user", "content": prepared_context}]
        self.mock_session_context.save_context_history.assert_called_with(self.company_short_name, self.user_identifier,
                                                                          expected_history,model=model)
        self.assertEqual(result, {})

    # --- populate_request_params Tests ---

    def test_populate_params_server_side_success(self):
        """Test populating params for server-side when ID exists."""
        handle = MockHistoryHandle(self.company_short_name, self.user_identifier, HistoryManager.TYPE_SERVER_SIDE)
        self.mock_session_context.get_last_response_id.return_value = "prev_id_123"

        rebuild_needed = self.manager.populate_request_params(handle, "User prompt")

        self.assertFalse(rebuild_needed)
        self.assertEqual(handle.request_params, {'previous_response_id': "prev_id_123"})

    def test_populate_params_server_side_missing_id(self):
        """Test populating params for server-side when ID is missing (rebuild needed)."""
        handle = MockHistoryHandle(self.company_short_name, self.user_identifier, HistoryManager.TYPE_SERVER_SIDE)
        self.mock_session_context.get_last_response_id.return_value = None

        rebuild_needed = self.manager.populate_request_params(handle, "User prompt")

        self.assertTrue(rebuild_needed)
        self.assertEqual(handle.request_params, {})

    def test_populate_params_server_side_ignore_history(self):
        """Test populating params server-side with ignore_history=True (uses initial ID)."""
        handle = MockHistoryHandle(self.company_short_name, self.user_identifier, HistoryManager.TYPE_SERVER_SIDE)
        self.mock_session_context.get_initial_response_id.return_value = "init_id_123"

        rebuild_needed = self.manager.populate_request_params(handle, "User prompt", ignore_history=True)

        self.assertFalse(rebuild_needed)
        self.assertEqual(handle.request_params, {'previous_response_id': "init_id_123"})

    def test_populate_params_client_side_success(self):
        """Test populating params for client-side: appends user turn."""
        handle = MockHistoryHandle(self.company_short_name, self.user_identifier, HistoryManager.TYPE_CLIENT_SIDE)
        existing_history = [{"role": "user", "content": "System"}]
        self.mock_session_context.get_context_history.return_value = existing_history

        # Mock count_tokens to avoid issues in _trim_context_history
        self.mock_llm_client.count_tokens.return_value = 10

        rebuild_needed = self.manager.populate_request_params(handle, "New question")

        self.assertFalse(rebuild_needed)
        # Check that the user prompt was appended to the params (but not yet saved to DB/Redis)
        expected_history = [
            {"role": "user", "content": "System"},
            {"role": "user", "content": "New question"}
        ]
        self.assertEqual(handle.request_params['context_history'], expected_history)

    def test_populate_params_client_side_missing_history(self):
        """Test populating params client-side when history is empty (rebuild needed)."""
        handle = MockHistoryHandle(self.company_short_name, self.user_identifier, HistoryManager.TYPE_CLIENT_SIDE)
        self.mock_session_context.get_context_history.return_value = []

        rebuild_needed = self.manager.populate_request_params(handle, "New question")

        self.assertTrue(rebuild_needed)

    def test_populate_params_client_side_trimming(self):
        """Test that history is trimmed when tokens exceed limit."""
        handle = MockHistoryHandle(self.company_short_name, self.user_identifier, HistoryManagerService.TYPE_CLIENT_SIDE)

        # Setup history with 3 messages
        # Index 0: System
        # Index 1: Oldest (This one should be evicted first)
        # Index 2: Answer
        existing_history = [
            {"role": "user", "content": "System"},
            {"role": "user", "content": "Oldest"},
            {"role": "model", "content": "Answer"}
        ]
        self.mock_session_context.get_context_history.return_value = existing_history

        # Choose a size that guarantees:
        # - 4 messages exceed the limit
        # - 3 messages fit within the limit
        # This ensures only the oldest message gets evicted.
        tokens_per_message = HistoryManagerService.MAX_TOKENS_CONTEXT_HISTORY // 3
        self.mock_llm_client.count_tokens.return_value = tokens_per_message

        self.manager.populate_request_params(handle, "New User Prompt")

        final_history = handle.request_params['context_history']

        # Expected Result: [System, Answer, New User Prompt]
        self.assertEqual(final_history[0]["content"], "System")
        self.assertNotIn({"role": "user", "content": "Oldest"}, final_history)
        self.assertEqual(final_history[-1]["content"], "New User Prompt")
        self.assertEqual(len(final_history), 3)

    # --- update_history Tests ---

    def test_update_history_server_side(self):
        """Test updating history for server-side (saves new ID)."""
        handle = MockHistoryHandle(self.company_short_name,
                                   self.user_identifier,
                                   HistoryManager.TYPE_SERVER_SIDE,
                                   model="gpt-4")
        response = {"response_id": "new_id_999"}

        self.manager.update_history(handle, "Prompt", response)

        self.mock_session_context.save_last_response_id.assert_called_with(
            self.company_short_name, self.user_identifier, "new_id_999", model="gpt-4"
        )

    def test_update_history_client_side(self):
        """Test updating history for client-side (appends model response)."""
        handle = MockHistoryHandle(self.company_short_name,
                                   self.user_identifier,
                                   HistoryManagerService.TYPE_CLIENT_SIDE,
                                   model="deepseek_chat",
                                   )

        # Current history in session (System prompt only)
        initial_history = [{"role": "user", "content": "System"}]
        self.mock_session_context.get_context_history.return_value = initial_history.copy()

        user_turn = "User Question"
        response = {"answer": "Model Answer"}

        self.manager.update_history(handle, user_turn, response)

        expected_saved_history = [
            {"role": "user", "content": "System"},
            {"role": "user", "content": user_turn},
            {"role": "assistant", "content": "Model Answer"}
        ]

        self.mock_session_context.save_context_history.assert_called_with(
            self.company_short_name, self.user_identifier, expected_saved_history, model="deepseek_chat"
        )

    # --- get_full_history Tests ---

    def test_get_full_history_success(self):
        """Test fetching full history from database."""
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company

        mock_query = MagicMock(spec=LLMQuery)
        mock_query.to_dict.return_value = {"query": "Hi"}
        self.mock_llm_query_repo.get_history.return_value = [mock_query]

        result = self.manager.get_full_history(self.company_short_name, self.user_identifier)

        self.assertEqual(result['message'], 'history loaded ok')
        self.assertEqual(len(result['history']), 1)
        self.assertEqual(result['history'][0]['query'], "Hi")

    def test_get_full_history_company_not_found(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = None
        self.mock_i18n.t.return_value = "Company not found error"

        result = self.manager.get_full_history("unknown", self.user_identifier)

        self.assertIn("error", result)
        self.assertEqual(result["error"], "Company not found error")
