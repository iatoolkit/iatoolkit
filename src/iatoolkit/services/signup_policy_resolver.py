# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from iatoolkit.common.interfaces.signup_policy_resolver import (
    SignupPolicyDecision,
    SignupPolicyResolver,
)


class AllowAllSignupPolicyResolver(SignupPolicyResolver):
    """Default resolver used by community/core until enterprise overrides it."""

    def evaluate_signup(
        self,
        company_short_name: str,
        email: str,
        invite_token: str | None = None,
    ) -> SignupPolicyDecision:
        return SignupPolicyDecision(
            allowed=True,
            metadata={
                "policy_mode": "allow_all",
                "company_short_name": company_short_name,
                "email": email,
                "invite_token_present": bool(invite_token),
            },
        )
