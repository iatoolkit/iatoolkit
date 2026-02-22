# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SignupPolicyDecision:
    """Result of signup policy evaluation."""

    allowed: bool
    reason_key: str | None = None
    reason_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SignupPolicyResolver(ABC):
    """Contract for pluggable signup authorization policies."""

    @abstractmethod
    def evaluate_signup(
        self,
        company_short_name: str,
        email: str,
        invite_token: str | None = None,
    ) -> SignupPolicyDecision:
        """Evaluates whether the email can sign up for the target company."""
