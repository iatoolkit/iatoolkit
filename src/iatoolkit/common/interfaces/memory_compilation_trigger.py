# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryCompilationTriggerResult:
    triggered: bool
    mode: str = "on_demand"
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryCompilationTrigger(ABC):
    @abstractmethod
    def trigger(
        self,
        company_short_name: str,
        user_identifier: str,
        trigger_item_id: int | None = None,
        reason: str = "capture",
    ) -> MemoryCompilationTriggerResult:
        """Triggers memory compilation work for a user when supported."""

    @abstractmethod
    def is_async_enabled(self) -> bool:
        """Returns True when memory compilation is expected to happen asynchronously."""
