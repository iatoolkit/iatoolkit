from __future__ import annotations

from typing import Any, Dict

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.services.configuration_service import ConfigurationService


class LLMGatewayResolver:
    """Resolves optional outbound LLM gateway transport settings."""

    PROVIDER_SLUGS = {
        "openai": "openai",
        "deepseek": "deepseek",
        "anthropic": "anthropic",
        "gemini": "google-ai-studio",
    }
    SUPPORTED_PROVIDERS = frozenset(PROVIDER_SLUGS)
    CREDENTIAL_MODE_PROVIDER_KEY = "provider_key_in_request"
    CREDENTIAL_MODE_CLOUDFLARE_MANAGED = "cloudflare_managed"

    def __init__(self, configuration_service: ConfigurationService, secret_provider: SecretProvider):
        self.configuration_service = configuration_service
        self.secret_provider = secret_provider

    def resolve(self, company_short_name: str, provider: str, provider_api_key: str | None) -> Dict[str, Any]:
        normalized_provider = str(provider or "").strip().lower()
        gateway_cfg = self.configuration_service.get_llm_gateway_config(company_short_name, normalized_provider) or {}
        if not isinstance(gateway_cfg, dict) or gateway_cfg.get("enabled") is not True:
            return {
                "enabled": False,
                "api_key": provider_api_key or "",
                "base_url": "",
                "default_headers": {},
            }

        vendor = str(gateway_cfg.get("vendor") or "").strip().lower()
        if vendor != "cloudflare":
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"Unsupported llm.gateway vendor '{vendor}'.",
            )

        mode = str(gateway_cfg.get("mode") or "").strip().lower()
        if mode != "provider_native":
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"Unsupported llm.gateway mode '{mode}'.",
            )

        provider_slug = self.PROVIDER_SLUGS.get(normalized_provider)
        if not provider_slug:
            return {
                "enabled": False,
                "api_key": provider_api_key or "",
                "base_url": "",
                "default_headers": {},
            }

        account_id = self._resolve_gateway_value(
            company_short_name,
            gateway_cfg,
            direct_key="account_id",
            secret_ref_key="account_id_secret_ref",
            env_key="account_id_env",
        )
        gateway_id = str(gateway_cfg.get("gateway_id") or "").strip()
        if not account_id or not gateway_id:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "Cloudflare gateway requires resolved account_id and gateway_id.",
            )

        credential_mode = str(
            gateway_cfg.get("credential_mode") or self.CREDENTIAL_MODE_PROVIDER_KEY
        ).strip().lower()
        authenticated_gateway = gateway_cfg.get("authenticated_gateway") is True
        default_headers: dict[str, str] = {}

        cloudflare_api_token = self._resolve_gateway_value(
            company_short_name,
            gateway_cfg,
            direct_key="cloudflare_api_token",
            secret_ref_key="cloudflare_api_token_secret_ref",
            env_key="cloudflare_api_token_env",
        )
        if authenticated_gateway:
            if not cloudflare_api_token:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    "Authenticated Cloudflare gateway requires a resolved cloudflare_api_token.",
                )
            default_headers["cf-aig-authorization"] = f"Bearer {cloudflare_api_token}"

        if credential_mode == self.CREDENTIAL_MODE_PROVIDER_KEY:
            if not provider_api_key:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.API_KEY,
                    (
                        f"Cloudflare gateway for provider '{normalized_provider}' requires the provider API key "
                        "when credential_mode is 'provider_key_in_request'."
                    ),
                )
            resolved_api_key = provider_api_key
        elif credential_mode == self.CREDENTIAL_MODE_CLOUDFLARE_MANAGED:
            if not authenticated_gateway:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    (
                        "credential_mode 'cloudflare_managed' requires "
                        "'authenticated_gateway: true' so requests can be authorized with Cloudflare."
                    ),
                )
            # Some SDKs insist on a non-null api_key even when upstream credentials are injected by Cloudflare.
            resolved_api_key = "" if normalized_provider in {"openai", "deepseek", "gemini"} else None
        else:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"Unsupported llm.gateway credential_mode '{credential_mode}'.",
            )

        byok_alias = str(gateway_cfg.get("byok_alias") or "").strip()
        if byok_alias:
            default_headers["cf-aig-byok-alias"] = byok_alias

        return {
            "enabled": True,
            "api_key": resolved_api_key,
            "base_url": f"https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/{provider_slug}",
            "default_headers": default_headers,
            "vendor": vendor,
            "mode": mode,
            "credential_mode": credential_mode,
            "authenticated_gateway": authenticated_gateway,
        }

    def _resolve_gateway_value(
        self,
        company_short_name: str,
        gateway_cfg: Dict[str, Any],
        *,
        direct_key: str,
        secret_ref_key: str,
        env_key: str,
    ) -> str:
        direct_value = str(gateway_cfg.get(direct_key) or "").strip()
        if direct_value:
            return direct_value

        secret_ref = str(gateway_cfg.get(secret_ref_key) or "").strip()
        if secret_ref:
            return str(
                resolve_secret(self.secret_provider, company_short_name, secret_ref, default="") or ""
            ).strip()

        env_ref = str(gateway_cfg.get(env_key) or "").strip()
        if env_ref:
            return str(
                resolve_secret(self.secret_provider, company_short_name, env_ref, default="") or ""
            ).strip()

        return ""
