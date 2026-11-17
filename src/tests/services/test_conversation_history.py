"""Each conversation has its own history (BL-001, PR-2): its own Redis hash
and lock, compacted on its own, rebuilt from the database when Redis forgot it."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iatoolkit.common.interfaces.history_compaction_trigger import HistoryCompactionTrigger
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.history_compaction_service import HistoryCompactionService
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.user_session_context_service import UserSessionContextService

CO, USER, MODEL, CONV = "acme", "ana@acme.cl", "gpt-5.2", "c0ffee"


class MemorySession(UserSessionContextService):
    """The real key scheme over a dict instead of Redis."""

    def __init__(self):
        self.store = {}
        self.expiring = set()
        self.locks = set()

    def _hash(self, company, user, model=None, conversation_id=None):
        return self.store.setdefault(self._get_session_key(company, user, model=model,
                                                           conversation_id=conversation_id), {})

    def save_context_history(self, company, user, context_history, model=None, conversation_id=None):
        self._hash(company, user, model, conversation_id)["context_history"] = list(context_history)
        if conversation_id:
            self.expiring.add(self._get_session_key(company, user, model=model, conversation_id=conversation_id))

    def get_context_history(self, company, user, model=None, conversation_id=None):
        return list(self._hash(company, user, model, conversation_id).get("context_history") or [])

    def save_context_tokens(self, company, user, context_tokens, model=None, conversation_id=None):
        self._hash(company, user, model, conversation_id)["context_tokens"] = int(context_tokens)

    def get_context_tokens(self, company, user, model=None, conversation_id=None):
        return self._hash(company, user, model, conversation_id).get("context_tokens", 0)

    def acquire_lock(self, lock_key, expire_seconds):
        if lock_key in self.locks:
            return False
        self.locks.add(lock_key)
        return True

    def release_lock(self, lock_key):
        self.locks.discard(lock_key)


def _manager(session, trigger=None):
    manager = HistoryManagerService(
        session_context=session, i18n=MagicMock(spec=I18nService), llm_query_repo=MagicMock(spec=LLMQueryRepo),
        profile_repo=MagicMock(spec=ProfileRepo), llm_client=MagicMock(spec=llmClient))
    manager.context_budget_tokens = lambda company, model: 100_000
    manager.compaction_budget_tokens = lambda company, model: 10_000
    manager.compaction_trigger = trigger or MagicMock(spec=HistoryCompactionTrigger)
    manager.llm_client.count_tokens.side_effect = lambda text, *args: len(str(text)) // 4
    return manager


def _handle(conversation_id=CONV):
    return SimpleNamespace(company_short_name=CO, user_identifier=USER, model=MODEL,
                           conversation_id=conversation_id, request_params=None)


class TestSessionKeys:
    def test_a_conversation_has_its_own_hash_next_to_the_persons(self):
        session = UserSessionContextService()

        assert session._get_session_key(CO, USER, MODEL) == f"session:{CO}/{USER}-{MODEL}"
        assert session._get_session_key(CO, USER, MODEL, conversation_id=CONV) == \
            f"session:{CO}/{USER}-{MODEL}/conv:{CONV}"

    def test_a_conversation_history_expires(self):
        session = UserSessionContextService()
        with patch("iatoolkit.services.user_session_context_service.RedisSessionManager") as redis:
            session.save_context_history(CO, USER, [{"role": "user", "content": "x"}], model=MODEL,
                                         conversation_id=CONV)
            session.save_context_history(CO, USER, [{"role": "user", "content": "x"}], model=MODEL)

        redis.expire.assert_called_once_with(f"session:{CO}/{USER}-{MODEL}/conv:{CONV}",
                                             UserSessionContextService.CONVERSATION_HISTORY_TTL_SECONDS)


class TestConversationHistory:
    def setup_method(self):
        self.session = MemorySession()
        self.session.save_context_history(CO, USER, [{"role": "user", "content": "CONTEXTO"}], model=MODEL)
        self.manager = _manager(self.session)

    def test_a_turn_reads_and_writes_only_its_conversation(self):
        self.manager.start_conversation_history(CO, USER, MODEL, CONV, turns=[])
        handle = _handle()

        assert self.manager.populate_request_params(handle, "¿ventas?") is False
        self.manager.update_history(handle, "¿ventas?", {"answer": "100", "stats": {}})

        conversation = self.session.get_context_history(CO, USER, MODEL, conversation_id=CONV)
        assert [m["content"] for m in conversation] == ["CONTEXTO", "¿ventas?", "100"]
        # The person's own history is untouched: it is the template new conversations start from.
        assert self.session.get_context_history(CO, USER, MODEL) == [{"role": "user", "content": "CONTEXTO"}]

    def test_an_unknown_conversation_needs_a_rebuild(self):
        assert self.manager.populate_request_params(_handle("nuevo"), "hola") is True

    def test_the_lock_is_per_conversation(self):
        assert HistoryManagerService.history_lock_key(CO, USER, MODEL, CONV) != \
            HistoryManagerService.history_lock_key(CO, USER, MODEL)
        assert HistoryManagerService.history_lock_key(CO, USER, MODEL) == f"lock:history:{CO}/{USER}/{MODEL}"

    def test_a_compaction_is_asked_for_the_conversation(self):
        self.manager.start_conversation_history(CO, USER, MODEL, CONV, turns=[])

        self.manager.update_history(_handle(), "q", {"answer": "a", "stats": {"context_tokens": 9_000}})
        self.manager.update_history(_handle(None), "q", {"answer": "a", "stats": {"context_tokens": 9_000}})

        calls = self.manager.compaction_trigger.trigger.call_args_list
        assert calls[0].args == (CO, USER, MODEL) and calls[0].kwargs == {"conversation_id": CONV}
        # Without a conversation, the call is the one a trigger written before conversations expects.
        assert calls[1].args == (CO, USER, MODEL) and calls[1].kwargs == {}

    def test_a_reopened_conversation_starts_from_context_summary_and_its_turns(self):
        started = self.manager.start_conversation_history(
            CO, USER, MODEL, CONV, summary="Hablaron de ventas.",
            turns=[{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
                   {"role": "system_event", "content": "falló"}, {"role": "user", "content": "  "}])

        history = self.session.get_context_history(CO, USER, MODEL, conversation_id=CONV)
        assert started is True
        assert history[0]["content"] == "CONTEXTO"
        assert HistoryManagerService.summary_text(history[1]) == "Hablaron de ventas."
        assert history[2:] == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]

    def test_without_a_prepared_context_there_is_nothing_to_start_from(self):
        empty = MemorySession()

        assert _manager(empty).start_conversation_history(CO, USER, MODEL, CONV, turns=[]) is False


class TestConversationCompaction:
    def test_a_conversation_is_compacted_in_its_own_history_and_keeps_the_summary(self):
        session = MemorySession()
        history = [{"role": "user", "content": "CONTEXTO"}]
        for index in range(12):
            history += [{"role": "user", "content": f"pregunta {index} " + "x" * 3000},
                        {"role": "assistant", "content": f"respuesta {index} " + "y" * 3000}]
        session.save_context_history(CO, USER, history, model=MODEL, conversation_id=CONV)
        session.save_context_history(CO, USER, [{"role": "user", "content": "CONTEXTO"}], model=MODEL)
        manager = _manager(session)
        runner = MagicMock()
        runner.run.return_value = {"structured_output": {"summary": "Resumen."}}
        service = HistoryCompactionService(session, manager, MagicMock(), runner, MagicMock(spec=llmClient))
        service._count = lambda message: len(str(message.get("content", ""))) // 4

        with patch("iatoolkit.services.history_compaction_service.SystemAgentRunner.is_enabled", return_value=True), \
                patch.object(HistoryCompactionService, "_keep_summary_with_conversation") as keep:
            result = service.compact(CO, USER, MODEL, conversation_id=CONV)

        assert result["status"] == "compacted"
        compacted = session.get_context_history(CO, USER, MODEL, conversation_id=CONV)
        assert HistoryManagerService.summary_text(compacted[1]) == "Resumen."
        assert len(session.get_context_history(CO, USER, MODEL)) == 1
        keep.assert_called_once_with(CO, USER, CONV, "Resumen.")
