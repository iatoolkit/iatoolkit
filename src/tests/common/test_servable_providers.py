# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

"""The provider list offered to a person must match the adapters that exist.

The value a person picks reaches `LLMProxy._build_adapter` verbatim, and anything
it does not recognise raises. So the choice has to be exactly the set it handles:
one entry too many is a model that saves fine, publishes fine, and fails on its
first real request.
"""

import inspect

from iatoolkit.common.model_registry import SERVABLE_PROVIDERS


def _adapter_branches() -> set[str]:
    """The providers `_build_adapter` actually returns an adapter for."""
    from iatoolkit.infra.llm_proxy import LLMProxy

    source = inspect.getsource(LLMProxy._build_adapter)
    found = set()
    for name, value in vars(LLMProxy).items():
        if name.startswith("PROVIDER_") and isinstance(value, str):
            if f"self.{name}" in source:
                found.add(value)
    return found


def test_every_offered_provider_has_an_adapter():
    missing = set(SERVABLE_PROVIDERS) - _adapter_branches()

    assert missing == set(), f"offered but unservable: {sorted(missing)}"


def test_no_adapter_is_left_unoffered():
    # An adapter nobody can choose is dead weight, and the drift usually means a
    # provider was added to the proxy and forgotten here.
    extra = _adapter_branches() - set(SERVABLE_PROVIDERS)

    assert extra == set(), f"servable but never offered: {sorted(extra)}"


def test_xai_is_deliberately_absent():
    # It is in ProviderType and normalize_provider accepts it, and a client is
    # even built for it — but there is no xAI adapter, so a model declared `xai`
    # raises on its first request. Offering it would be offering a broken choice.
    assert "xai" not in SERVABLE_PROVIDERS
