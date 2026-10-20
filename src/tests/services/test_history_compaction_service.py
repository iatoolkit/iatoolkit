# Compaction of a long conversation history (BL-009, Fase E): what is
# summarized, how the summary is applied, and when it is asked for.

import json
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.services.history_compaction_service import HistoryCompactionService
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.system_agent_runner import SystemAgentUnavailable


class FakeSession:
    """The session fields the history manager and the compaction use, in memory."""

    def __init__(self, history=None):
        self.history = list(history or [])
        self.context_tokens = 0
        self.locks = set()
        self.saved_histories = []

    def get_context_history(self, company_short_name, user_identifier, model=None):
        return [dict(m) for m in self.history]

    def save_context_history(self, company_short_name, user_identifier, context_history, model=None):
        self.history = [dict(m) for m in context_history]
        self.saved_histories.append(self.history)

    def save_context_tokens(self, company_short_name, user_identifier, context_tokens, model=None):
        self.context_tokens = int(context_tokens)

    def get_context_tokens(self, company_short_name, user_identifier, model=None):
        return self.context_tokens

    def acquire_lock(self, lock_key, expire_seconds):
        if lock_key in self.locks:
            return False
        self.locks.add(lock_key)
        return True

    def release_lock(self, lock_key):
        self.locks.discard(lock_key)

    def clear_llm_history(self, *args, **kwargs):
        self.history = []


def _turn(question, answer):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


def _history(turns):
    history = [{"role": "user", "content": "company context"}]
    for index in range(turns):
        history += _turn(f"q{index}", f"a{index}")
    return history


def _llm_client(tokens_per_message=10):
    client = MagicMock()
    client.count_tokens.return_value = tokens_per_message
    return client


def _manager(session, llm_client, budget=1000):
    manager = HistoryManagerService(
        session_context=session,
        i18n=MagicMock(),
        llm_query_repo=MagicMock(),
        profile_repo=MagicMock(),
        llm_client=llm_client,
    )
    manager.context_budget_tokens = MagicMock(return_value=budget)
    return manager


def _service(session, *, budget=1000, tokens_per_message=10, summary="the summary"):
    llm_client = _llm_client(tokens_per_message)
    manager = _manager(session, llm_client, budget)
    runner = MagicMock()
    runner.run.return_value = {"structured_output": {"summary": summary}}
    service = HistoryCompactionService(
        session_context=session,
        history_manager=manager,
        profile_repo=MagicMock(),
        system_agent_runner=runner,
        llm_client=llm_client,
    )
    return service, runner, manager


@pytest.fixture(autouse=True)
def _agent_enabled():
    with patch("iatoolkit.services.history_compaction_service.SystemAgentRunner.is_enabled", return_value=True):
        yield


class TestPlan:
    def test_two_turns_or_fewer_are_never_compacted(self):
        service, _, _ = _service(FakeSession())

        assert service.plan(_history(2), budget_tokens=1000) is None

    def test_recent_turns_are_kept_within_their_share_of_the_budget(self):
        service, _, _ = _service(FakeSession())
        history = _history(6)  # 13 messages of 10 tokens; each turn is 20

        # 30% of 200 = 60 tokens: three turns fit, so three are summarized.
        plan = service.plan(history, budget_tokens=200)

        assert plan.cut == 7
        assert [m["content"] for m in plan.material] == ["q0", "a0", "q1", "a1", "q2", "a2"]
        assert plan.previous_summary == ""

    def test_at_least_two_turns_stay_verbatim_whatever_their_size(self):
        service, _, _ = _service(FakeSession(), tokens_per_message=10_000)

        plan = service.plan(_history(4), budget_tokens=1000)

        assert plan.cut == 5  # q2 onwards stays
        assert [m["content"] for m in plan.material] == ["q0", "a0", "q1", "a1"]

    def test_a_previous_summary_is_merged_not_summarized_as_a_turn(self):
        service, _, _ = _service(FakeSession())
        history = (
            [{"role": "user", "content": "company context"},
             HistoryManagerService.summary_message("earlier facts")]
            + _turn("q0", "a0") + _turn("q1", "a1") + _turn("q2", "a2") + _turn("q3", "a3")
        )

        plan = service.plan(history, budget_tokens=100)

        assert plan.previous_summary == "earlier facts"
        assert plan.material[0] == {"role": "user", "content": "q0"}

    def test_a_turn_with_tools_is_summarized_whole(self):
        service, _, _ = _service(FakeSession())
        history = [
            {"role": "user", "content": "company context"},
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "sql", "arguments": "{}"}}]},
            {"type": "function_call_output", "call_id": "c1", "output": "rows"},
            {"role": "assistant", "content": "a0"},
        ] + _turn("q1", "a1") + _turn("q2", "a2")

        plan = service.plan(history, budget_tokens=60)

        assert plan.cut == 5
        assert history[plan.cut] == {"role": "user", "content": "q1"}


class TestTranscript:
    def test_tool_calls_and_results_are_written_out(self):
        transcript = HistoryCompactionService.render_transcript([
            {"role": "user", "content": "ventas 2025"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "iat_sql_query", "arguments": '{"query": "SELECT 1"}'}},
            ]},
            {"type": "function_call_output", "call_id": "c1", "output": '[{"total": 42}]'},
            {"role": "assistant", "content": "Hay 42."},
        ])

        assert "USER: ventas 2025" in transcript
        assert 'ASSISTANT called tool `iat_sql_query` with: {"query": "SELECT 1"}' in transcript
        assert 'TOOL RESULT: [{"total": 42}]' in transcript
        assert "ASSISTANT: Hay 42." in transcript

    def test_long_messages_are_clipped(self):
        transcript = HistoryCompactionService.render_transcript([
            {"type": "function_call_output", "call_id": "c1", "output": "x" * 10_000},
        ])

        assert len(transcript) < 5_000
        assert "characters cut" in transcript


class TestCompact:
    def test_the_summary_replaces_the_old_turns(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)

        result = service.compact("acme", "u1", "gpt-5")

        assert result == {"status": "compacted", "summarized_messages": 6, "kept_messages": 6, "chunks": 1}
        assert session.history[0] == {"role": "user", "content": "company context"}
        assert session.history[1] == HistoryManagerService.summary_message("the summary")
        assert [m["content"] for m in session.history[2:]] == ["q3", "a3", "q4", "a4", "q5", "a5"]
        inputs = runner.run.call_args.args[2]
        assert inputs["previous_summary"] == ""
        assert "USER: q0" in inputs["transcript"] and "q3" not in inputs["transcript"]
        # The stored measure describes the compacted history now.
        assert session.context_tokens == 80
        assert not session.locks

    def test_a_turn_that_arrived_during_the_summary_is_kept(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)

        def arrives_meanwhile(*args, **kwargs):
            session.history += _turn("q6", "a6")
            return {"structured_output": {"summary": "the summary"}}

        runner.run.side_effect = arrives_meanwhile

        service.compact("acme", "u1", "gpt-5")

        assert [m["content"] for m in session.history[-2:]] == ["q6", "a6"]
        assert session.history[1] == HistoryManagerService.summary_message("the summary")

    def test_a_history_reset_during_the_summary_is_never_overwritten(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)

        def reset_meanwhile(*args, **kwargs):
            session.history = _history(0)
            return {"structured_output": {"summary": "the summary"}}

        runner.run.side_effect = reset_meanwhile

        result = service.compact("acme", "u1", "gpt-5")

        assert result == {"status": "skipped", "reason": "history_changed"}
        assert session.history == _history(0)

    def test_a_busy_history_is_left_for_the_next_turn(self):
        session = FakeSession(_history(6))
        service, _, manager = _service(session, budget=200)
        session.locks.add(manager.history_lock_key("acme", "u1", "gpt-5"))

        result = service.compact("acme", "u1", "gpt-5")

        assert result == {"status": "skipped", "reason": "history_busy"}
        assert session.saved_histories == []

    def test_nothing_to_compact_does_not_call_the_agent(self):
        session = FakeSession(_history(2))
        service, runner, _ = _service(session)

        assert service.compact("acme", "u1", "gpt-5")["reason"] == "nothing_to_compact"
        runner.run.assert_not_called()

    def test_an_empty_summary_changes_nothing(self):
        session = FakeSession(_history(6))
        service, _, _ = _service(session, budget=200, summary="  ")

        assert service.compact("acme", "u1", "gpt-5") == {"status": "error", "reason": "empty_summary"}
        assert session.saved_histories == []

    def test_a_company_without_a_model_is_skipped(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)
        runner.run.side_effect = SystemAgentUnavailable("no model")

        assert service.compact("acme", "u1", "gpt-5")["status"] == "skipped"
        assert session.saved_histories == []

    def test_a_disabled_agent_is_skipped(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)

        with patch("iatoolkit.services.history_compaction_service.SystemAgentRunner.is_enabled", return_value=False):
            assert service.compact("acme", "u1", "gpt-5")["status"] == "skipped"
        runner.run.assert_not_called()


class _Handle:
    def __init__(self, model="gpt-5"):
        self.company_short_name = "acme"
        self.user_identifier = "u1"
        self.type = HistoryManagerService.TYPE_CLIENT_SIDE
        self.model = model
        self.request_params = {}


class TestTriggers:
    def _manager(self, session, budget=1000):
        manager = _manager(session, _llm_client(), budget)
        manager.compaction_trigger = MagicMock()
        manager.compaction_service = MagicMock()
        return manager

    def test_a_turn_past_seventy_percent_asks_for_a_background_compaction(self):
        session = FakeSession(_history(1))
        manager = self._manager(session)

        manager.update_history(_Handle(), "q1", {"answer": "a1", "stats": {"context_tokens": 700}})

        manager.compaction_trigger.trigger.assert_called_once_with("acme", "u1", "gpt-5")
        assert session.context_tokens == 700
        assert [m["content"] for m in session.history[-2:]] == ["q1", "a1"]

    def test_a_turn_below_the_threshold_asks_for_nothing(self):
        session = FakeSession(_history(1))
        manager = self._manager(session)

        manager.update_history(_Handle(), "q1", {"answer": "a1", "stats": {"context_tokens": 699}})

        manager.compaction_trigger.trigger.assert_not_called()

    def test_a_failing_trigger_never_fails_the_turn(self):
        session = FakeSession(_history(1))
        manager = self._manager(session)
        manager.compaction_trigger.trigger.side_effect = RuntimeError("queue down")

        manager.update_history(_Handle(), "q1", {"answer": "a1", "stats": {"context_tokens": 900}})

        assert [m["content"] for m in session.history[-2:]] == ["q1", "a1"]

    def test_a_turn_is_saved_even_if_the_history_lock_never_frees(self):
        session = FakeSession(_history(1))
        manager = self._manager(session)
        manager.HISTORY_LOCK_WAIT_SECONDS = 0.0
        session.locks.add(manager.history_lock_key("acme", "u1", "gpt-5"))

        manager.update_history(_Handle(), "q1", {"answer": "a1"})

        assert [m["content"] for m in session.history[-2:]] == ["q1", "a1"]
        # The lock it did not take is not released by it.
        assert manager.history_lock_key("acme", "u1", "gpt-5") in session.locks

    def test_without_workers_a_turn_that_would_not_fit_compacts_in_line(self):
        session = FakeSession(_history(1))
        session.context_tokens = 940
        manager = self._manager(session)
        manager.compaction_trigger.trigger.return_value = False  # nothing runs in the background

        # 940 measured + 10 for the new turn = 95% of 1000.
        manager.populate_request_params(_Handle(), "q1")

        manager.compaction_service.compact.assert_called_once_with("acme", "u1", "gpt-5", max_chunks=1)

    def test_with_workers_the_turn_asks_again_and_never_waits_for_a_summary(self):
        # A summary takes minutes; the request would die at the web timeout.
        session = FakeSession(_history(1))
        session.context_tokens = 940
        manager = self._manager(session)
        manager.compaction_trigger.trigger.return_value = True

        manager.populate_request_params(_Handle(), "q1")

        manager.compaction_trigger.trigger.assert_called_once_with("acme", "u1", "gpt-5")
        manager.compaction_service.compact.assert_not_called()

    def test_a_turn_that_fits_does_not_compact(self):
        session = FakeSession(_history(1))
        session.context_tokens = 900
        manager = self._manager(session)

        manager.populate_request_params(_Handle(), "q1")

        manager.compaction_service.compact.assert_not_called()

    def test_ignore_history_never_compacts(self):
        session = FakeSession(_history(1))
        session.context_tokens = 999
        manager = self._manager(session)

        manager.populate_request_params(_Handle(), "q1", ignore_history=True)

        manager.compaction_service.compact.assert_not_called()

    def test_a_failed_in_line_compaction_falls_back_to_the_trim(self):
        session = FakeSession(_history(1))
        session.context_tokens = 999
        manager = self._manager(session)
        manager.compaction_trigger.trigger.return_value = False
        manager.compaction_service.compact.side_effect = RuntimeError("model down")

        handle = _Handle()
        needs_rebuild = manager.populate_request_params(handle, "q1")

        # The request still goes out, on the (trimmed) history.
        assert needs_rebuild is False
        assert handle.request_params["context_history"][-1] == {"role": "user", "content": "q1"}

    def test_trimming_keeps_the_summary_with_the_context(self):
        session = FakeSession()
        manager = self._manager(session)
        history = (
            [{"role": "user", "content": "company context"}, HistoryManagerService.summary_message("facts")]
            + _turn("q0", "a0") + _turn("q1", "a1")
        )

        manager._trim_context_history(history, budget_tokens=45)

        assert history[1] == HistoryManagerService.summary_message("facts")
        assert [m["content"] for m in history[2:]] == ["q1", "a1"]


def test_context_tokens_is_what_the_last_call_read_and_wrote():
    from iatoolkit.infra.llm_response import LLMResponse, Usage
    from iatoolkit.services.llm_client_service import llmClient

    response = LLMResponse('r', 'gpt-5', 'completed', json.dumps({"answer": "x"}), [], Usage(900, 50, 950))

    assert llmClient._context_tokens(response) == 950


class TestSummaryAndStoredHistory:
    @pytest.mark.parametrize("response, expected", [
        ({"structured_output": {"summary": "a"}}, "a"),
        ({"structured_output": None, "parsed_output": {"summary": "b"}}, "b"),
        # The model answered the Markdown alone: that is the summary.
        ({"structured_output": None, "answer": "**Objective**: c"}, "**Objective**: c"),
        ({"structured_output": None, "answer": '{"summary": "d"}'}, "d"),
        ({"structured_output": None, "answer": "  "}, ""),
        (None, ""),
    ])
    def test_the_summary_is_read_however_the_model_returned_it(self, response, expected):
        assert HistoryCompactionService._summary_from(response) == expected

    def test_a_long_stretch_is_summarized_in_parts_oldest_first(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)
        calls = []

        def summarize(*args, **kwargs):
            calls.append(args[2])
            return {"structured_output": {"summary": f"summary {len(calls)}"}}

        runner.run.side_effect = summarize

        with patch.object(HistoryCompactionService, "MAX_TRANSCRIPT_CHARS", 40):
            result = service.compact("acme", "u1", "gpt-5")

        assert result["status"] == "compacted"
        assert result["chunks"] == len(calls) >= 2
        # Each part extends the summary of the one before; the oldest goes first.
        assert calls[0]["previous_summary"] == ""
        assert "q0" in calls[0]["transcript"]
        assert calls[1]["previous_summary"] == "summary 1"
        assert session.history[1] == HistoryManagerService.summary_message(f"summary {len(calls)}")

    def test_parts_beyond_the_limit_are_left_out_and_reported(self):
        session = FakeSession(_history(6))
        service, runner, _ = _service(session, budget=200)

        with patch.object(HistoryCompactionService, "MAX_TRANSCRIPT_CHARS", 10):
            result = service.compact("acme", "u1", "gpt-5", max_chunks=1)

        assert runner.run.call_count == 1
        assert result["dropped_chunks"] >= 1

    def test_chunks_never_split_a_turn(self):
        material = [
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "sql", "arguments": "{}"}}]},
            {"type": "function_call_output", "call_id": "c1", "output": "rows"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]

        with patch.object(HistoryCompactionService, "MAX_TRANSCRIPT_CHARS", 10):
            chunks = HistoryCompactionService.chunk_material(material)

        assert [len(chunk) for chunk in chunks] == [4, 2]

    def test_the_stored_history_is_capped_at_two_budgets(self):
        long = "x" * 4000
        session = FakeSession(
            [{"role": "user", "content": "company context"}]
            + [m for i in range(30) for m in _turn(f"q{i} {long}", f"a{i} {long}")]
        )
        manager = _manager(session, _llm_client(tokens_per_message=1000), budget=10_000)
        manager.compaction_trigger = MagicMock()

        manager.update_history(_Handle(), "new question", {"answer": "new answer"})

        # 63 messages of 1000 tokens against a cap of 20,000: the oldest whole turns go.
        assert len(session.history) * 1000 <= 20_000
        assert session.history[0] == {"role": "user", "content": "company context"}
        assert [m["content"] for m in session.history[-2:]] == ["new question", "new answer"]

    def test_a_stored_history_well_under_the_cap_is_not_even_counted(self):
        session = FakeSession(_history(3))
        llm_client = _llm_client(tokens_per_message=1)
        manager = _manager(session, llm_client, budget=10_000)
        manager.compaction_trigger = MagicMock()

        manager.update_history(_Handle(), "q", {"answer": "a"})

        llm_client.count_tokens.assert_not_called()
