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

    def _warmup_remote_text_embeddings(self, company_short_name: str):
        if not self._uses_remote_text_inference(company_short_name):
            logging.debug(
                "Warm-up skipped for company='%s': no remote embedding inference configured.",
                company_short_name
            )
            return

        # Prime the remote model/container.
        self.embedding_service.embed_text(company_short_name, "hello")

    def _uses_remote_text_inference(self, company_short_name: str) -> bool:
        embedding_cfg = self.config_service.get_configuration(company_short_name, "embedding_provider") or {}
        provider = (embedding_cfg.get("provider") or "").strip().lower()
        if provider != "huggingface":
            return False

        tool_name = (embedding_cfg.get("tool_name") or "text_embeddings").strip()
        if not tool_name:
            return False

        inference_tools = self.config_service.get_configuration(company_short_name, "inference_tools") or {}
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
