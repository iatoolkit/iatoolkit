# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest

from iatoolkit.services.chat_stream import QueueEventSink, RoundStream, TurnCancelled


class _Sink:
    def __init__(self):
        self.events = []
        self.cancelled = False

    def emit(self, event, payload=None):
        self.events.append((event, payload))

    def is_cancelled(self):
        return self.cancelled


def _texts(sink):
    return "".join(p["text"] for e, p in sink.events if e == "text_delta")


class TestRoundStream:
    def test_plain_text_goes_out_as_it_arrives(self):
        sink = _Sink()
        stream = RoundStream(sink)
        for piece in ["\n", "Hola", " mundo"]:
            stream.on_text_delta(piece)
        assert sink.events == [("text_delta", {"text": "\nHola"}), ("text_delta", {"text": " mundo"})]

    @pytest.mark.parametrize("pieces", [
        ["  {", '"answer": "x"}'],
        ["`", "``json\n{}", "```"],
        ["```", "json"],
    ])
    def test_json_answers_are_held_back(self, pieces):
        sink = _Sink()
        stream = RoundStream(sink)
        for piece in pieces:
            stream.on_text_delta(piece)
        assert _texts(sink) == ""

    def test_inline_code_at_the_start_is_text(self):
        sink = _Sink()
        stream = RoundStream(sink)
        stream.on_text_delta("`")
        stream.on_text_delta("x` es una variable")
        assert _texts(sink) == "`x` es una variable"

    def test_no_text_when_the_turn_asks_for_json(self):
        sink = _Sink()
        stream = RoundStream(sink, stream_text=False)
        stream.on_text_delta("Hola")
        stream.on_reasoning_delta("pienso")
        assert sink.events == [("reasoning_delta", {"text": "pienso"})]

    def test_cancellation_comes_from_the_sink(self):
        sink = _Sink()
        stream = RoundStream(sink)
        stream.raise_if_cancelled()
        sink.cancelled = True
        with pytest.raises(TurnCancelled):
            stream.raise_if_cancelled()


class TestQueueEventSink:
    def test_events_in_order_then_heartbeat_then_close(self):
        sink = QueueEventSink()
        sink.emit("round_start", {"round": 1})
        events = sink.events(heartbeat_seconds=0.01)
        assert next(events) == ("round_start", {"round": 1})
        assert next(events) is None  # nothing queued: heartbeat
        sink.close()
        assert list(events) == []

    def test_cancel(self):
        sink = QueueEventSink()
        assert not sink.is_cancelled()
        sink.cancel()
        assert sink.is_cancelled()
