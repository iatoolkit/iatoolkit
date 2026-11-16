# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""OpenAIAdapter read as a stream (BL-023): deltas go out as they arrive and the
mapped response is the one a plain call would give."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_providers.openai_adapter import OpenAIAdapter
from iatoolkit.services.chat_stream import TurnCancelled


def _response():
    return SimpleNamespace(
        id="resp_1",
        model="gpt-5",
        status="completed",
        output_text="",
        output=[
            SimpleNamespace(
                type="reasoning",
                id="rs_1",
                encrypted_content="enc",
                summary=[SimpleNamespace(text="Primero miro."), SimpleNamespace(text="Luego sumo.")],
                content=[],
            ),
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="Hola **mundo**")],
            ),
            SimpleNamespace(type="function_call", call_id="c1", name="iat_sql_query", arguments='{"q": 1}'),
        ],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18),
    )


class _Stream:
    def __init__(self, events):
        self._events = events
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def close(self):
        self.closed = True


class _Callbacks:
    def __init__(self, cancel_after=None):
        self.text = []
        self.reasoning = []
        self.checks = 0
        self._cancel_after = cancel_after

    def on_text_delta(self, text):
        self.text.append(text)

    def on_reasoning_delta(self, text):
        self.reasoning.append(text)

    def raise_if_cancelled(self):
        self.checks += 1
        if self._cancel_after is not None and self.checks > self._cancel_after:
            raise TurnCancelled()


def _events(response):
    return [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.reasoning_summary_part.added", item_id="rs_1", summary_index=0),
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Primero miro."),
        SimpleNamespace(type="response.reasoning_summary_part.added", item_id="rs_1", summary_index=1),
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Luego sumo."),
        SimpleNamespace(type="response.output_text.delta", delta="Hola "),
        SimpleNamespace(type="response.output_text.delta", delta="**mundo**"),
        SimpleNamespace(type="response.completed", response=response),
    ]


class TestOpenAIAdapterStreaming:
    def setup_method(self):
        self.client = MagicMock()
        self.adapter = OpenAIAdapter(openai_client=self.client)

    def test_declares_streaming(self):
        assert OpenAIAdapter.supports_streaming is True

    def test_streamed_response_maps_like_a_plain_call(self):
        response = _response()
        stream = _Stream(_events(response))
        self.client.responses.create.return_value = stream
        callbacks = _Callbacks()

        streamed = self.adapter.create_response(
            model="gpt-5", input=[{"role": "user", "content": "hola"}], stream_callbacks=callbacks,
        )

        assert self.client.responses.create.call_args.kwargs["stream"] is True
        assert stream.closed
        assert callbacks.text == ["Hola ", "**mundo**"]
        assert "".join(callbacks.reasoning) == "Primero miro.\nLuego sumo."

        self.client.responses.create.return_value = response
        plain = self.adapter.create_response(model="gpt-5", input=[{"role": "user", "content": "hola"}])

        assert "stream" not in self.client.responses.create.call_args.kwargs
        for field in ("id", "model", "status", "output_text", "output", "usage",
                      "reasoning_content", "reasoning_details", "content_parts"):
            assert getattr(streamed, field) == getattr(plain, field), field

    def test_a_failed_stream_raises_an_llm_error(self):
        failed = SimpleNamespace(error=SimpleNamespace(message="rate limited"))
        self.client.responses.create.return_value = _Stream([
            SimpleNamespace(type="response.output_text.delta", delta="Ho"),
            SimpleNamespace(type="response.failed", response=failed),
        ])

        with pytest.raises(IAToolkitException, match="rate limited"):
            self.adapter.create_response(model="gpt-5", input=[], stream_callbacks=_Callbacks())

    def test_a_stream_without_a_final_response_raises(self):
        self.client.responses.create.return_value = _Stream([
            SimpleNamespace(type="response.output_text.delta", delta="Ho"),
        ])

        with pytest.raises(IAToolkitException, match="without a response"):
            self.adapter.create_response(model="gpt-5", input=[], stream_callbacks=_Callbacks())

    def test_a_cancelled_turn_stops_reading_and_closes_the_stream(self):
        stream = _Stream(_events(_response()))
        self.client.responses.create.return_value = stream
        callbacks = _Callbacks(cancel_after=2)

        with pytest.raises(TurnCancelled):
            self.adapter.create_response(model="gpt-5", input=[], stream_callbacks=callbacks)

        assert stream.closed
        assert callbacks.text == []
