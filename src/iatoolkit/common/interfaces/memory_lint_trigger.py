# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryLintTriggerResult:
    triggered: bool
    mode: str = "inline"
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryLintTrigger(ABC):
    @abstractmethod
    def trigger(
        self,
        company_short_name: str,
        user_identifier: str,
        reason: str = "manual",
    ) -> MemoryLintTriggerResult:
        """Triggers memory lint work for a user when supported."""

    @abstractmethod
    def is_async_enabled(self) -> bool:
        """Returns True when memory lint is expected to happen asynchronously."""
