# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Live events of a chat turn (BL-023).

A turn that runs for the chat web can hand `QueryService.llm_query` an event
sink. The tool loop reports on it what the user would otherwise wait for in
silence: each model round, each tool that starts and ends, and (for providers
that stream) the text and reasoning as they arrive. The sink is optional at
every layer: without one, nothing is emitted and the turn runs exactly as it
always did, which is what every other caller (API, MCP, tasks, loops,
evaluations, system agents) gets.

Events and their payloads:

    round_start      {"round": n}
    reasoning_delta  {"text": "..."}
    text_delta       {"text": "..."}
    round_end        {"round": n, "has_tool_calls": bool}
    tool_start       {"call_id": "...", "name": "..."}
    tool_end         {"call_id": "...", "name": "...", "ok": bool, "ms": int}
    final            the dict `llm_query` returns
    error            {"error_message": "..."}

`tool_start` carries the tool's name only, never its arguments: SQL or
document queries are not something every viewer of the chat may see.
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, Iterator, Optional, Tuple


class TurnCancelled(Exception):
    """The person stopped the turn (or left): stop calling models and tools."""


class ChatEventSink:
    """Where a turn reports its progress. The base class drops every event."""

    def emit(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        _ = event, payload

    def is_cancelled(self) -> bool:
        return False

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise TurnCancelled("The turn was cancelled.")


def raise_if_cancelled(event_sink: Optional[ChatEventSink]) -> None:
    """Stop the turn when the person stopped it. No sink, nothing to stop."""
    if event_sink is None:
        return
    is_cancelled = getattr(event_sink, "is_cancelled", None)
    if callable(is_cancelled) and is_cancelled() is True:
        raise TurnCancelled("The turn was cancelled.")


def emit_safely(event_sink: Optional[ChatEventSink], event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Report an event without ever letting the report break the turn."""
    if event_sink is None:
        return
    try:
        event_sink.emit(event, payload or {})
    except Exception:
        logging.exception("chat stream: could not emit event %s", event)


class StreamMetrics:
    """What a live turn looked like to the person (BL-023), for `LLMQuery.stats`.

    Times are milliseconds from the start of the turn to the first piece the
    chat actually showed: text held back (JSON answers) does not count.
    """

    def __init__(self):
        self._started = time.monotonic()
        self.first_text_ms: Optional[int] = None
        self.first_reasoning_ms: Optional[int] = None
        self.text_deltas = 0
        self.reasoning_deltas = 0

    def _elapsed_ms(self) -> int:
        return int(round((time.monotonic() - self._started) * 1000))

    def text_shown(self) -> None:
        self.text_deltas += 1
        if self.first_text_ms is None:
            self.first_text_ms = self._elapsed_ms()

    def reasoning_shown(self) -> None:
        self.reasoning_deltas += 1
        if self.first_reasoning_ms is None:
            self.first_reasoning_ms = self._elapsed_ms()

    def as_stats(self) -> Dict[str, Any]:
        """`mode` says what the person saw live: the answer's text, or only the
        activity (a provider that does not stream, or a JSON answer)."""
        stats: Dict[str, Any] = {
            "mode": "text" if self.text_deltas else "activity",
            "text_deltas": self.text_deltas,
            "reasoning_deltas": self.reasoning_deltas,
        }
        if self.first_text_ms is not None:
            stats["first_text_ms"] = self.first_text_ms
        if self.first_reasoning_ms is not None:
            stats["first_reasoning_ms"] = self.first_reasoning_ms
        return stats


class RoundStream:
    """What a streaming adapter reports during one model call.

    The adapter hands over text and reasoning as they arrive; this decides
    what reaches the sink. Text is held back for turns whose answer is JSON
    (an output schema, or a model that answers in the legacy
    `{"answer": ...}` format): it would mean nothing to the person and the
    final event renders it properly. The decision is made on the first
    visible characters of each call.
    """

    _JSON_FENCE = "```"

    def __init__(self, event_sink: ChatEventSink, stream_text: bool = True,
                 metrics: Optional[StreamMetrics] = None):
        self._sink = event_sink
        self._stream_text = stream_text
        self._metrics = metrics
        self._pending = ""
        self._text_decision: Optional[bool] = None if stream_text else False
        #: Everything the model wrote in this call, shown or not: what a call
        #: cut short is estimated to have cost.
        self.received_text = ""

    def is_cancelled(self) -> bool:
        return bool(self._sink.is_cancelled())

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise TurnCancelled("The turn was cancelled.")

    def on_reasoning_delta(self, text: str) -> None:
        if text:
            self.received_text += text
            emit_safely(self._sink, "reasoning_delta", {"text": text})
            if self._metrics is not None:
                self._metrics.reasoning_shown()

    def on_text_delta(self, text: str) -> None:
        if text:
            self.received_text += text
        if not text or self._text_decision is False:
            return
        if self._text_decision is True:
            self._emit_text(text)
            return

        self._pending += text
        visible = self._pending.lstrip()
        if not visible:
            return
        if visible.startswith("{"):
            self._text_decision = False
        elif visible.startswith("`"):
            if len(visible) < len(self._JSON_FENCE) and self._JSON_FENCE.startswith(visible):
                return  # one or two backticks: not enough to tell yet
            self._text_decision = not visible.startswith(self._JSON_FENCE)
        else:
            self._text_decision = True

        if self._text_decision:
            self._emit_text(self._pending)
        self._pending = ""

    def _emit_text(self, text: str) -> None:
        emit_safely(self._sink, "text_delta", {"text": text})
        if self._metrics is not None:
            self._metrics.text_shown()


class QueueEventSink(ChatEventSink):
    """A sink a web response reads from: the turn runs in its own thread and
    writes here; the streaming response drains the queue.

    Built on the standard library, so it works the same under gevent (where
    `queue` and `threading` are monkey-patched and the thread is a greenlet)
    and under threaded workers.
    """

    _CLOSE = object()

    def __init__(self):
        self._queue: "queue.Queue" = queue.Queue()
        self._cancelled = threading.Event()

    def emit(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._queue.put((event, payload or {}))

    def close(self) -> None:
        """No more events: the reader stops after draining what is queued."""
        self._queue.put(self._CLOSE)

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def events(self, heartbeat_seconds: float) -> Iterator[Optional[Tuple[str, Dict[str, Any]]]]:
        """Queued events in order; `None` when `heartbeat_seconds` pass without one."""
        while True:
            try:
                item = self._queue.get(timeout=heartbeat_seconds)
            except queue.Empty:
                yield None
                continue
            if item is self._CLOSE:
                return
            yield item
