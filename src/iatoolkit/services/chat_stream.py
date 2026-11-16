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


def emit_safely(event_sink: Optional[ChatEventSink], event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Report an event without ever letting the report break the turn."""
    if event_sink is None:
        return
    try:
        event_sink.emit(event, payload or {})
    except Exception:
        logging.exception("chat stream: could not emit event %s", event)


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
