# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging
import time
from injector import inject

from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.company_registry import get_registered_companies
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.embedding_service import EmbeddingService


class WarmupService:
    """
    Lightweight warm-up orchestrator.
    Keep it simple: no shared state, no locking, no dedup.
    """

    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 embedding_service: EmbeddingService,
                 secret_provider: SecretProvider):
        self.config_service = config_service
        self.embedding_service = embedding_service
        self.secret_provider = secret_provider

    def warmup_company(self, company_short_name: str, trigger: str = "manual"):
        start = time.perf_counter()
        try:
            self._warmup_remote_text_embeddings(company_short_name)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logging.info(
                "🔥 Warm-up done for company='%s' trigger='%s' in %.2f ms",
                company_short_name,
                trigger,
                elapsed_ms
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logging.debug(
                "⚠️ Warm-up failed for company='%s' trigger='%s' in %.2f ms: %s",
                company_short_name,
                trigger,
                elapsed_ms,
                e
            )

    def warmup_registered_companies(self, trigger: str = "manual"):
        for company_short_name in get_registered_companies().keys():
            self.warmup_company(company_short_name, trigger=trigger)

    def warmup_startup_configured_companies(self, trigger: str = "startup") -> list[str]:
        warmed_companies: list[str] = []
        for company_short_name in get_registered_companies().keys():
            warmed_profiles = self._warmup_remote_text_embeddings(company_short_name, startup_only=True)
            if not warmed_profiles:
                logging.debug(
                    "Startup warm-up skipped for company='%s': no embedding provider enabled warmup_on_startup.",
                    company_short_name,
                )
                continue

            warmed_companies.append(company_short_name)

        return warmed_companies

    def is_startup_warmup_enabled(self, company_short_name: str) -> bool:
        return bool(self._get_remote_text_embedding_profiles(company_short_name, startup_only=True))

    def _warmup_remote_text_embeddings(self, company_short_name: str, startup_only: bool = False) -> list[tuple[str, str, str]]:
        profiles = self._get_remote_text_embedding_profiles(company_short_name, startup_only=startup_only)
        if not profiles:
            logging.debug(
                "Warm-up skipped for company='%s': no remote embedding inference configured.",
                company_short_name
            )
            return []

        warmed_profiles = []
        for model_type, config_section, tool_name in profiles:
            try:
                # Prime the remote model/container and download/cache model weights.
                self.embedding_service.embed_text(
                    company_short_name,
                    "hello",
                    model_type=model_type,
                    suppress_error_logging=True,
                )
                logging.debug(
                    "Warm-up primed remote embedding profile company='%s' section='%s' model_type='%s' tool='%s'.",
                    company_short_name,
                    config_section,
                    model_type,
                    tool_name,
                )
                warmed_profiles.append((model_type, config_section, tool_name))
            except Exception as e:
                logging.debug(
                    "Warm-up failed for remote embedding profile company='%s' section='%s' model_type='%s' tool='%s': %s",
                    company_short_name,
                    config_section,
                    model_type,
                    tool_name,
                    e,
                )

        return warmed_profiles

    def _uses_remote_text_inference(self, company_short_name: str) -> bool:
        return bool(self._get_remote_text_embedding_profiles(company_short_name))

    def _get_remote_text_embedding_profiles(
            self,
            company_short_name: str,
            startup_only: bool = False,
    ) -> list[tuple[str, str, str]]:
        profiles: list[tuple[str, str, str, dict]] = []

        embedding_cfg = self.config_service.get_configuration(company_short_name, "embedding_provider") or {}
        if isinstance(embedding_cfg, dict):
            profiles.append(("text", "embedding_provider", embedding_cfg.get("tool_name") or "text_embeddings", embedding_cfg))

        embedding_providers = self.config_service.get_configuration(company_short_name, "embedding_providers") or {}
        if isinstance(embedding_providers, dict):
            for model_type, embedding_provider_cfg in embedding_providers.items():
                if not isinstance(embedding_provider_cfg, dict):
                    continue
                normalized_model_type = str(model_type or "").strip()
                if not normalized_model_type:
                    continue
                profiles.append((
                    normalized_model_type,
                    f"embedding_providers.{normalized_model_type}",
                    embedding_provider_cfg.get("tool_name") or normalized_model_type,
                    embedding_provider_cfg,
                ))

        inference_tools = self.config_service.get_configuration(company_short_name, "inference_tools") or {}
        if not isinstance(inference_tools, dict):
            return []

        remote_profiles = [
            (model_type, config_section, str(tool_name or "").strip())
            for model_type, config_section, tool_name, embedding_cfg in profiles
            if self._is_remote_embedding_profile(company_short_name, embedding_cfg, inference_tools, str(tool_name or "").strip())
            and (not startup_only or bool(embedding_cfg.get("warmup_on_startup")))
        ]

        # Leave the default text profile warm last. It is the profile used by rag_search.
        return sorted(remote_profiles, key=lambda item: 1 if item[0] == "text" else 0)

    def _is_remote_embedding_profile(
            self,
            company_short_name: str,
            embedding_cfg: dict,
            inference_tools: dict,
            tool_name: str,
    ) -> bool:
        provider = (embedding_cfg.get("provider") or "").strip().lower()
        if provider != "huggingface":
            return False

        if not tool_name:
            return False

        defaults = inference_tools.get("_defaults") or {}
        if not isinstance(defaults, dict):
            defaults = {}

        tool_cfg = inference_tools.get(tool_name) or {}
        if not isinstance(tool_cfg, dict):
            return False

        resolved_cfg = {**defaults, **tool_cfg}
        endpoint_url = (resolved_cfg.get("endpoint_url") or "").strip()
        if not endpoint_url:
            endpoint_url_secret_ref = (resolved_cfg.get("endpoint_url_secret_ref") or "").strip()
            if endpoint_url_secret_ref:
                endpoint_url = (
                    resolve_secret(self.secret_provider, company_short_name, endpoint_url_secret_ref, default="") or ""
                ).strip()
        if not endpoint_url:
            endpoint_url_env = (resolved_cfg.get("endpoint_url_env") or "").strip()
            if endpoint_url_env:
                endpoint_url = (
                    resolve_secret(self.secret_provider, company_short_name, endpoint_url_env, default="") or ""
                ).strip()

        return bool(endpoint_url)
