# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from abc import ABC, abstractmethod


class HistoryCompactionTrigger(ABC):
    """Asks for a conversation history to be compacted in the background (BL-009).

    The core has no task queue, so its default does nothing and a history is
    compacted in line, on the turn that would no longer fit. A deployment with
    workers (enterprise) binds one that queues the work instead.
    """

    @abstractmethod
    def trigger(self, company_short_name: str, user_identifier: str, model: str) -> bool:
        """Queues the compaction. True when something was queued or already was."""
