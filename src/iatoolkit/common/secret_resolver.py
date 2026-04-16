from __future__ import annotations

from iatoolkit.common.interfaces.secret_provider import SecretProvider


def normalize_secret_ref(secret_ref: str | None) -> str:
    return str(secret_ref or "").strip()


def resolve_secret(
    secret_provider: SecretProvider,
    company_short_name: str,
    secret_ref: str | None,
    default: str | None = None,
) -> str | None:
    normalized_ref = normalize_secret_ref(secret_ref)
    if not normalized_ref:
        return default

    return secret_provider.get_secret(company_short_name, normalized_ref, default=default)
