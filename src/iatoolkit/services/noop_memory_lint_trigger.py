# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.common.interfaces.memory_lint_trigger import (
    MemoryLintTrigger,
    MemoryLintTriggerResult,
)


class NoopMemoryLintTrigger(MemoryLintTrigger):
    @inject
    def __init__(self):
        pass

    def trigger(
        self,
        company_short_name: str,
        user_identifier: str,
        reason: str = "manual",
    ) -> MemoryLintTriggerResult:
        return MemoryLintTriggerResult(
            triggered=False,
            mode="inline",
            metadata={
                "company_short_name": company_short_name,
                "user_identifier": user_identifier,
                "reason": reason,
            },
        )

    def is_async_enabled(self) -> bool:
        return False
