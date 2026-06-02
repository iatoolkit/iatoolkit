import os
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.infra.llm_gateway_resolver import LLMGatewayResolver
from iatoolkit.services.configuration_service import ConfigurationService


class TestLLMGatewayResolver:
    def setup_method(self):
        self.config_service_mock = MagicMock(spec=ConfigurationService)
        self.secret_provider_mock = MagicMock(spec=SecretProvider)
        self.secret_provider_mock.get_secret.side_effect = (
            lambda _company, key_name, default=None: os.getenv(key_name, default)
        )
        self.resolver = LLMGatewayResolver(
            configuration_service=self.config_service_mock,
            secret_provider=self.secret_provider_mock,
        )
        self.company_short_name = "test_company"

    def test_resolve_returns_disabled_when_gateway_is_not_configured(self):
        self.config_service_mock.get_llm_gateway_config.return_value = {}

        resolved = self.resolver.resolve(self.company_short_name, "openai", "sk-openai")

        assert resolved == {
            "enabled": False,
            "api_key": "sk-openai",
            "base_url": "",
            "default_headers": {},
        }

    def test_resolve_maps_deepseek_to_cloudflare_deepseek_provider_path(self):
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "provider_key_in_request",
        }

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CF_ACCOUNT_ID", "cf-account")
            mp.setenv("CF_API_TOKEN", "cf-token")
            resolved = self.resolver.resolve(self.company_short_name, "deepseek", "sk-deepseek")

        assert resolved["base_url"] == (
            "https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/deepseek"
        )
        assert resolved["api_key"] == "sk-deepseek"
        assert resolved["default_headers"]["cf-aig-authorization"] == "Bearer cf-token"

    def test_resolve_maps_gemini_to_google_ai_studio_provider_path(self):
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "cloudflare_managed",
            "byok_alias": "production",
        }

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CF_ACCOUNT_ID", "cf-account")
            mp.setenv("CF_API_TOKEN", "cf-token")
            resolved = self.resolver.resolve(self.company_short_name, "gemini", "")

        assert resolved["base_url"] == (
            "https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/google-ai-studio"
        )
        assert resolved["api_key"] == ""
        assert resolved["default_headers"] == {
            "cf-aig-authorization": "Bearer cf-token",
            "cf-aig-byok-alias": "production",
        }

    def test_resolve_rejects_cloudflare_managed_without_authenticated_gateway(self):
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "credential_mode": "cloudflare_managed",
        }

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CF_ACCOUNT_ID", "cf-account")
            with pytest.raises(IAToolkitException, match="authenticated_gateway: true"):
                self.resolver.resolve(self.company_short_name, "openai", "")
