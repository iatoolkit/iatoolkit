# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from iatoolkit.common.interfaces.identity_provider_resolver import (
    CompanyIdentityProvider,
    IdentityProviderResolver,
)


class NoIdentityProviderResolver(IdentityProviderResolver):
    """Community default: no company has an external identity provider."""

    def get_provider(self, company_short_name: str) -> CompanyIdentityProvider | None:
        return None
