# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""OpenRouterAdapter read as a stream (BL-023), against chunks recorded from
OpenRouter (openai/gpt-5-mini; encrypted reasoning replaced by a placeholder)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import openai
import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_providers.deepseek_adapter import DeepseekAdapter
from iatoolkit.infra.llm_providers.openai_compatible_chat_adapter import OpenAICompatibleChatAdapter
from iatoolkit.infra.llm_providers.openrouter_adapter import OpenRouterAdapter
from iatoolkit.services.chat_stream import TurnCancelled

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "openrouter_stream_chunks.json").read_text())
TOOLS = [{"type": "function", "name": "iat_sql_query", "parameters": {"type": "object", "properties": {}}}]


def _as_objects(value):
    """The recorded chunks with attribute access, as the SDK hands them over."""
    return json.loads(json.dumps(value), object_hook=lambda d: SimpleNamespace(**d))


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

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


def _deltas(chunks, key):
    return "".join(
        (choice.get("delta") or {}).get(key) or ""
        for chunk in chunks for choice in chunk.get("choices") or []
    )


class TestOpenRouterStreaming:
    def setup_method(self):
        self.client = MagicMock()
        self.adapter = OpenRouterAdapter(openrouter_client=self.client)

    def _stream(self, name, objects=True):
        chunks = FIXTURES[name]
        stream = _Stream(_as_objects(chunks) if objects else chunks)
        self.client.chat.completions.create.return_value = stream
        return stream

    def test_only_openrouter_streams(self):
        assert OpenRouterAdapter.supports_streaming is True
        assert OpenAICompatibleChatAdapter.supports_streaming is False
        assert DeepseekAdapter.supports_streaming is False

    @pytest.mark.parametrize("objects", [True, False])
    def test_text_and_reasoning_go_out_and_the_response_is_whole(self, objects):
        stream = self._stream("text_reasoning", objects=objects)
        callbacks = _Callbacks()

        response = self.adapter.create_response(
            model="openai/gpt-5-mini", input=[{"role": "user", "content": "hola"}], stream_callbacks=callbacks,
        )

        call_kwargs = self.client.chat.completions.create.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_options"] == {"include_usage": True}
        assert stream.closed

        chunks = FIXTURES["text_reasoning"]
        expected_text = _deltas(chunks, "content")
        assert expected_text and "".join(callbacks.text) == expected_text
        assert response.output_text == expected_text
        assert response.status == "completed"
        assert response.output == []
        assert "".join(callbacks.reasoning) == _deltas(chunks, "reasoning")
        assert response.reasoning_content == _deltas(chunks, "reasoning")

        usage = chunks[-1]["usage"]
        assert response.usage.input_tokens == usage["prompt_tokens"]
        assert response.usage.output_tokens == usage["completion_tokens"]
        assert response.usage.total_tokens == usage["total_tokens"]
        assert response.id == "gen-test-text_reasoning"

    def test_tool_calls_and_reasoning_details_are_put_together(self):
        self._stream("tool_call")

        response = self.adapter.create_response(
            model="openai/gpt-5-mini", input=[{"role": "user", "content": "cuenta"}],
            tools=TOOLS, tool_choice="required", stream_callbacks=_Callbacks(),
        )

        assert response.status == "tool_calls"
        assert len(response.output) == 1
        call = response.output[0]
        assert call.name == "iat_sql_query"
        assert call.call_id.startswith("call_")
        assert "query" in json.loads(call.arguments)

        details = response.reasoning_details
        assert [detail["type"] for detail in details] == ["reasoning.summary", "reasoning.encrypted"]
        assert details[0]["summary"] == "".join(
            d.get("summary") or ""
            for chunk in FIXTURES["tool_call"] for choice in chunk.get("choices") or []
            for d in (choice.get("delta") or {}).get("reasoning_details") or []
            if d.get("type") == "reasoning.summary"
        )
        assert details[1]["data"] == "encrypted-test-data"

        # The assistant message waiting for the tool output carries the same
        # reasoning a plain call would have stored (sent back on the next call).
        pending = self.adapter._pending_assistant_tool_messages[call.call_id]["assistant_message"]
        assert pending["tool_calls"][0]["function"]["name"] == "iat_sql_query"
        assert pending["reasoning_details"] == details

    def test_maps_like_the_same_message_without_streaming(self):
        """Fed the plain shape of the streamed message, the mapper gives the same response."""
        self._stream("tool_call")
        streamed = self.adapter.create_response(
            model="m", input=[], tools=TOOLS, stream_callbacks=_Callbacks(),
        )

        call = streamed.output[0]
        chunks = FIXTURES["tool_call"]
        plain = _as_objects({
            "id": "gen-test-tool_call", "model": chunks[0]["model"], "usage": chunks[-1]["usage"],
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "reasoning": _deltas(chunks, "reasoning"),
                "tool_calls": [{"id": call.call_id, "type": "function",
                                "function": {"name": call.name, "arguments": call.arguments}}],
            }}],
        })
        # The SDK keeps fields it does not declare (reasoning_details) as plain dicts.
        plain.choices[0].message.reasoning_details = streamed.reasoning_details
        mapped = OpenRouterAdapter(openrouter_client=MagicMock())._map_chat_completion_response(plain)

        for field in ("id", "model", "status", "output_text", "output", "usage",
                      "reasoning_content", "reasoning_details", "content_parts"):
            assert getattr(streamed, field) == getattr(mapped, field), field

    def test_without_callbacks_nothing_streams(self):
        self.client.chat.completions.create.return_value = _as_objects({
            "id": "x", "model": "m", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
        })

        response = self.adapter.create_response(model="m", input=[])

        assert "stream" not in self.client.chat.completions.create.call_args.kwargs
        assert response.output_text == "ok"

    def test_an_error_chunk_raises(self):
        self.client.chat.completions.create.return_value = _Stream(_as_objects([
            {"id": "x", "model": "m", "choices": [{"index": 0, "delta": {"content": "Ho"}}]},
            {"id": "x", "model": "m", "error": {"message": "upstream overloaded"},
             "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "error"}]},
        ]))

        with pytest.raises(IAToolkitException, match="upstream overloaded"):
            self.adapter.create_response(model="m", input=[], stream_callbacks=_Callbacks())

    def test_a_cancelled_turn_stops_reading(self):
        stream = self._stream("text_reasoning")

        with pytest.raises(TurnCancelled):
            self.adapter.create_response(model="m", input=[], stream_callbacks=_Callbacks(cancel_after=3))

        assert stream.closed

    def test_connection_retries_still_apply_before_the_first_chunk(self, monkeypatch):
        monkeypatch.setattr(OpenRouterAdapter, "_CONNECTION_ERROR_RETRY_DELAY_SECONDS", 0)
        stream = _Stream(_as_objects(FIXTURES["text_reasoning"]))
        self.client.chat.completions.create.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
            stream,
        ]

        response = self.adapter.create_response(model="m", input=[], stream_callbacks=_Callbacks())

        assert response.output_text == _deltas(FIXTURES["text_reasoning"], "content")
        assert self.client.chat.completions.create.call_count == 2
