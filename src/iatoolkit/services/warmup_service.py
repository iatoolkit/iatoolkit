# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from injector import inject

from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.company_registry import get_registered_companies
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.embedding_service import EmbeddingService


class WarmupService:
    """
    Lightweight warm-up orchestrator.
    Keep it simple: no shared state, no locking.

    The one exception is the startup path, which deduplicates by resolved
    endpoint URL. That is not coordination between processes — each process
    still knocks on its own — it is not knocking N times for N tenants that
    share one endpoint.
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
        """Wakes each distinct inference endpoint once. Returns the hosts woken.

        Once per endpoint, not once per tenant: waking is a property of the
        endpoint, and tenants normally share one. Doing it per tenant only
        multiplied requests against a container that was already starting, each
        one willing to spend the tool's whole retry budget getting there.

        Nothing is awaited beyond the call. Surviving a cold start is the
        inference client's job, through ``retry_budget_seconds``; this only has
        to knock on the door.
        """
        targets = self._startup_endpoints()
        if not targets:
            logging.info("Startup warm-up skipped: no embedding provider enabled warmup_on_startup.")
            return []

        woken: list[str] = []
        for endpoint_url, (company_short_name, profile) in targets.items():
            model_type, _config_section, _tool_name = profile
            label = self._format_profile_labels([profile])[0]
            host = self._endpoint_host(endpoint_url)
            try:
                self.embedding_service.embed_text(
                    company_short_name,
                    "hello",
                    model_type=model_type,
                    suppress_error_logging=True,
                )
                logging.info(
                    "🔥 Startup warm-up woke endpoint='%s' via company='%s' profile=%s trigger='%s'.",
                    host, company_short_name, label, trigger,
                )
                woken.append(host)
            except Exception as e:
                logging.warning(
                    "Startup warm-up could not wake endpoint='%s' via company='%s' profile=%s: %s",
                    host, company_short_name, label, e,
                )

        return woken

    def _startup_endpoints(self) -> dict[str, tuple[str, tuple[str, str, str]]]:
        """One representative (company, profile) per distinct endpoint URL.

        Keyed by the resolved URL rather than by company or tool name, so a
        deployment where every tenant shares one endpoint knocks once, and a
        tenant later pointed somewhere else gets its own knock without anyone
        having to remember this function exists.
        """
        targets: dict[str, tuple[str, tuple[str, str, str]]] = {}
        for company_short_name in get_registered_companies().keys():
            inference_tools = self.config_service.get_configuration(company_short_name, "inference_tools") or {}
            if not isinstance(inference_tools, dict):
                continue

            for profile in self._get_remote_text_embedding_profiles(company_short_name, startup_only=True):
                _model_type, _config_section, tool_name = profile
                endpoint_url = self._resolve_endpoint_url(company_short_name, inference_tools, tool_name)
                if not endpoint_url:
                    continue

                existing = targets.get(endpoint_url)
                # Prefer the default text profile as the representative: it is the
                # one rag_search uses, so if the container loads models on demand
                # the one most likely to be asked for first is the one primed.
                if existing is None or (profile[0] == "text" and existing[1][0] != "text"):
                    targets[endpoint_url] = (company_short_name, profile)

        return targets

    @staticmethod
    def _endpoint_host(endpoint_url: str) -> str:
        """Host only: the URL can come from a secret, and the host is enough to log."""
        return urlparse(endpoint_url).hostname or "unknown"

        return warmed_companies

    def is_startup_warmup_enabled(self, company_short_name: str) -> bool:
        return bool(self._get_remote_text_embedding_profiles(company_short_name, startup_only=True))

    def _warmup_remote_text_embeddings(
            self,
            company_short_name: str,
            startup_only: bool = False,
            profiles: list[tuple[str, str, str]] | None = None,
    ) -> list[tuple[str, str, str]]:
        if profiles is None:
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
                log_fn = logging.warning if startup_only else logging.debug
                log_fn(
                    "Warm-up failed for remote embedding profile company='%s' section='%s' model_type='%s' tool='%s': %s",
                    company_short_name,
                    config_section,
                    model_type,
                    tool_name,
                    e,
                )

        return warmed_profiles

    @staticmethod
    def _format_profile_labels(profiles: list[tuple[str, str, str]]) -> list[str]:
        return [
            f"{config_section}:{model_type}:{tool_name}"
            for model_type, config_section, tool_name in profiles
        ]

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

        return bool(self._resolve_endpoint_url(company_short_name, inference_tools, tool_name))

    def _resolve_endpoint_url(
            self,
            company_short_name: str,
            inference_tools: dict,
            tool_name: str,
    ) -> str:
        """Where a tool's requests actually go, or "" when it resolves nowhere.

        Same precedence the inference client uses — literal, secret ref, then
        environment variable — because this is what identifies the thing being
        woken. Two profiles that resolve here to the same URL are one endpoint,
        whatever they are called in the company's configuration.
        """
        if not tool_name:
            return ""

        defaults = inference_tools.get("_defaults") or {}
        if not isinstance(defaults, dict):
            defaults = {}

        tool_cfg = inference_tools.get(tool_name) or {}
        if not isinstance(tool_cfg, dict):
            return ""

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

        return endpoint_url
