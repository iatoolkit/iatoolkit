# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from iatoolkit.common.interfaces.signup_policy_resolver import SignupPolicyDecision
from iatoolkit.services.signup_policy_resolver import AllowAllSignupPolicyResolver


def test_allow_all_signup_policy_resolver_allows_signup():
    resolver = AllowAllSignupPolicyResolver()

    decision = resolver.evaluate_signup(
        company_short_name="acme",
        email="user@acme.com",
        invite_token=None,
    )

    assert isinstance(decision, SignupPolicyDecision)
    assert decision.allowed is True
    assert decision.metadata.get("policy_mode") == "allow_all"
