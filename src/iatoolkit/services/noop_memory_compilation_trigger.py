# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.common.interfaces.memory_compilation_trigger import (
    MemoryCompilationTrigger,
    MemoryCompilationTriggerResult,
)


class NoopMemoryCompilationTrigger(MemoryCompilationTrigger):
    @inject
    def __init__(self):
        pass

    def trigger(
        self,
        company_short_name: str,
        user_identifier: str,
        trigger_item_id: int | None = None,
        reason: str = "capture",
    ) -> MemoryCompilationTriggerResult:
        return MemoryCompilationTriggerResult(
            triggered=False,
            mode="on_demand",
            metadata={
                "company_short_name": company_short_name,
                "user_identifier": user_identifier,
                "trigger_item_id": trigger_item_id,
                "reason": reason,
            },
        )

    def is_async_enabled(self) -> bool:
        return False
