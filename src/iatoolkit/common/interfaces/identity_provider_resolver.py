# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Which external identity provider (Microsoft Entra ID, Okta, any OpenID Connect
provider) a company signs in with — BL-031.

Core owns the contract and the sign-in flow; where each company's provider is
configured and how its secret is stored belongs to the edition that offers it.
Community ships a resolver that answers "none", so the SSO routes exist but say
the provider is not available. Same shape as SignupPolicyResolver.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from iatoolkit.infra.oidc_client import OidcProviderConfig


@dataclass(frozen=True)
class CompanyIdentityProvider:
    """
    One company's identity provider, ready to sign people in.

    ``trusted_email_domains`` settles the providers that do not say whether the
    e-mail is verified (Entra ID never sends ``email_verified``): an address in
    one of these domains is taken as verified, any other is refused. A provider
    that does send the claim is believed when it says true and refused when it
    says false, whatever the domain.
    """
    company_short_name: str
    provider_type: str            # "entra", "okta", "oidc": for the button and the logs
    display_name: str             # button text, e.g. "Microsoft"
    oidc: OidcProviderConfig
    trusted_email_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyLoginMethods:
    """
    How people may sign in to a company. ``password`` off still lets the
    company's owners in with their password: the emergency door for when the
    identity provider is misconfigured or down.
    """
    sso: CompanyIdentityProvider | None = None
    google: bool = True
    password: bool = True


class IdentityProviderResolver(ABC):

    @abstractmethod
    def get_provider(self, company_short_name: str) -> CompanyIdentityProvider | None:
        """The company's active identity provider, or None when it has none."""

    def get_login_methods(self, company_short_name: str) -> CompanyLoginMethods:
        """Every method allowed, plus the provider when there is one."""
        return CompanyLoginMethods(sso=self.get_provider(company_short_name))
