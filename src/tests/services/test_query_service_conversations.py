"""A turn that lives in a conversation (BL-001, PR-3)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.repositories.conversation_repo import ConversationRepo
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, ConversationMessage
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.conversation_service import ConversationService
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.query_service import QueryService

ANA, BETO = "ana@acme.cl", "beto@acme.cl"


@pytest.fixture
def env():
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all()
    session = db.get_session()
    session.add(Company(name="Acme", short_name="acme"))
    session.commit()
    conversations = ConversationService(ConversationRepo(db), ProfileRepo(db))
    service = QueryService.__new__(QueryService)
    service.conversation_service = conversations
    service.i18n_service = MagicMock(**{"t.side_effect": lambda key, **kw: key})
    service.history_manager = MagicMock(spec=HistoryManagerService)
    service.session_context = MagicMock()
    service._turn = MagicMock(return_value={"valid_response": True, "answer": "<p>42</p>",
                                            "answer_text": "**42**", "query_id": None})
    service._llm_query_turn = service._turn
    return SimpleNamespace(service=service, conversations=conversations)


class TestTurnInAConversation:
    def test_a_turn_without_a_conversation_is_as_before(self, env):
        env.service.llm_query("acme", ANA, question="hola")

        assert "conversation" not in env.service._turn.call_args.kwargs

    def test_create_conversation_starts_one_and_records_the_turn(self, env):
        response = env.service.llm_query("acme", ANA, question="¿cuántas garantías hubo en 2026?",
                                         create_conversation=True, client_data={"source": "chat_ui"})

        conversation = env.conversations.get_for_user("acme", ANA, response["conversation_id"])
        assert conversation.title == "¿cuántas garantías hubo en 2026?"
        assert env.service._turn.call_args.kwargs["conversation"].public_id == conversation.public_id
        messages = env.conversations.messages(conversation)
        assert [(m.role, m.content) for m in messages] == [
            (ConversationMessage.ROLE_USER, "¿cuántas garantías hubo en 2026?"),
            (ConversationMessage.ROLE_ASSISTANT, "**42**"),
        ]
        assert response["user_message_id"] == messages[0].id
        assert response["assistant_message_id"] == messages[1].id
        assert response["conversation"]["title"] == conversation.title

    def test_a_second_turn_continues_the_conversation(self, env):
        first = env.service.llm_query("acme", ANA, question="uno", create_conversation=True)
        second = env.service.llm_query("acme", ANA, question="dos", conversation_id=first["conversation_id"])

        conversation = env.conversations.get_for_user("acme", ANA, first["conversation_id"])
        assert second["conversation_id"] == first["conversation_id"]
        assert [m.content for m in env.conversations.messages(conversation)] == ["uno", "**42**", "dos", "**42**"]

    def test_someone_elses_conversation_is_not_found(self, env):
        first = env.service.llm_query("acme", ANA, question="uno", create_conversation=True)

        response = env.service.llm_query("acme", BETO, question="dos", conversation_id=first["conversation_id"])

        assert response["error"] is True and response["status_code"] == 404
        assert env.service._turn.call_count == 1

    def test_a_failed_turn_keeps_the_question_and_the_error(self, env):
        env.service._turn.return_value = {"error": True, "error_message": "el modelo falló"}

        response = env.service.llm_query("acme", ANA, question="x", create_conversation=True)

        messages = env.conversations.messages(env.conversations.get_for_user("acme", ANA, response["conversation_id"]))
        assert [(m.role, m.content) for m in messages] == [
            (ConversationMessage.ROLE_USER, "x"), (ConversationMessage.ROLE_SYSTEM_EVENT, "el modelo falló")]

    def test_a_stopped_turn_keeps_only_the_question(self, env):
        env.service._turn.return_value = {"error": True, "cancelled": True, "error_message": "cancelled"}

        response = env.service.llm_query("acme", ANA, question="x", create_conversation=True)

        [message] = env.conversations.messages(env.conversations.get_for_user("acme", ANA, response["conversation_id"]))
        assert message.meta == {"stopped": True}
        assert "assistant_message_id" not in response


class TestConversationHistoryIsRebuilt:
    def _service(self, env, has_context=True):
        service = env.service
        service._access_changed_since_context = MagicMock(return_value=False)
        service.prepare_context = MagicMock()
        service.set_context_for_llm = MagicMock()
        service.session_context.get_context_history.return_value = (
            [{"role": "user", "content": "CONTEXTO"}] if has_context else [])
        # Redis forgot the conversation; once rebuilt, it is there.
        service.history_manager.populate_request_params.side_effect = [True, False]
        service.history_manager.start_conversation_history.return_value = True
        return service

    def _conversation(self, env):
        conversation = env.conversations.create("acme", ANA)
        env.conversations.append_turn(conversation, question="q1", answer_text="a1", llm_query_id=None,
                                      user_identifier=ANA)
        env.conversations.append_cancelled_turn(conversation, question="detenida", user_identifier=ANA)
        env.conversations.append_turn(conversation, question="q2", answer_text="a2", llm_query_id=None,
                                      user_identifier=ANA)
        return conversation

    def test_from_its_turns_without_the_stopped_ones(self, env):
        service = self._service(env)
        conversation = self._conversation(env)
        company = SimpleNamespace(short_name="acme")

        handle, error = service._ensure_valid_history(company, ANA, "gpt-5.2", "q3", "q3", False,
                                                      conversation=conversation)

        assert error is None and handle.conversation_id == conversation.public_id
        args = service.history_manager.start_conversation_history.call_args
        assert args.args == ("acme", ANA, "gpt-5.2", conversation.public_id)
        assert [t["content"] for t in args.kwargs["turns"]] == ["q1", "a1", "q2", "a2"]
        service.prepare_context.assert_not_called()

    def test_with_its_summary_and_fewer_turns(self, env):
        service = self._service(env)
        conversation = self._conversation(env)
        env.conversations.save_meta(conversation, compaction_summary="Hablaron de ventas.")

        service._ensure_valid_history(SimpleNamespace(short_name="acme"), ANA, "gpt-5.2", "q", "q", False,
                                      conversation=conversation)

        assert service.history_manager.start_conversation_history.call_args.kwargs["summary"] == "Hablaron de ventas."

    def test_the_prepared_context_is_rebuilt_first_when_missing(self, env):
        service = self._service(env, has_context=False)

        service._ensure_valid_history(SimpleNamespace(short_name="acme"), ANA, "gpt-5.2", "q", "q", False,
                                      conversation=self._conversation(env))

        service.prepare_context.assert_called_once()
        service.set_context_for_llm.assert_called_once()

    def test_a_history_in_redis_is_used_as_it_is(self, env):
        service = self._service(env)
        service.history_manager.populate_request_params.side_effect = [False]

        handle, error = service._ensure_valid_history(SimpleNamespace(short_name="acme"), ANA, "gpt-5.2", "q", "q",
                                                      False, conversation=self._conversation(env))

        assert error is None
        service.history_manager.start_conversation_history.assert_not_called()
