# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.common.interfaces.history_compaction_trigger import HistoryCompactionTrigger


class NoopHistoryCompactionTrigger(HistoryCompactionTrigger):
    """Without workers nothing runs in the background: the history is compacted in line."""

    @inject
    def __init__(self):
        pass

    def trigger(self, company_short_name: str, user_identifier: str, model: str) -> bool:
        return False
