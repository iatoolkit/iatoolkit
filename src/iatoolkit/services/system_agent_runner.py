# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from injector import inject
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from iatoolkit.common.model_registry import ModelRegistry
from iatoolkit.common.util import Utility
from iatoolkit.repositories.models import Company
from iatoolkit.services.attachment_policy_service import AttachmentPolicyService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.system_agent_catalog import SystemAgent, SystemAgentCatalog


class SystemAgentUnavailable(Exception):
    """The company has no model to run the agent with."""


class SystemAgentDisabled(SystemAgentUnavailable):
    """The platform turned the agent off: its work waits until it is turned on again."""


@dataclass(frozen=True)
class PlatformAgentSettings:
    """What the platform operator set for an agent, for every tenant (BL-012, Fase 2)."""
    default_model: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ResolvedModel:
    model: str | None
    # Where it came from: "tenant" (company.yaml), "platform" (the operator's
    # default for the agent), "catalog" (the agent's default in its pack) or
    # "company" (the company's default model).
    source: str | None
    # The tenant's choice when it could not be used (no longer enabled).
    ignored_choice: str | None = None
    # The platform's model when this company does not have it enabled.
    ignored_platform_model: str | None = None


class SystemAgentRunner:
    """
    Runs a system agent (see system_agent_catalog): renders its prompt with the
    inputs the caller built, resolves the model and calls it with the agent's
    output contract. Interpreting and repairing the answer stays with the caller.

    The model is resolved from the most specific to the most general: the one the
    tenant picked (`system_agents.<key>.model` in company.yaml), the one the
    platform set for the agent, the agent's default in the catalog, the
    company's default model. A model the company does not have enabled is
    skipped (the platform's too: a tenant is never charged for a model it does
    not have), and a call that fails with a picked model is retried once with
    the company's default, so a bad choice never stops the agent.

    The platform's settings (default model, on/off) come from a provider the
    deployment registers (`register_platform_settings_provider`); without one,
    every agent is on and has no platform model.

    Deliberately light: it does not go through tasks or the agent runtime, so
    the services that use it gain no dependency beyond the model client.
    """

    CONFIG_SECTION = "system_agents"
    SOURCE_TENANT = "tenant"
    SOURCE_PLATFORM = "platform"
    SOURCE_CATALOG = "catalog"
    SOURCE_COMPANY = "company"

    _platform_settings_provider: Callable[[str], PlatformAgentSettings | None] | None = None

    _template_env = ImmutableSandboxedEnvironment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    # Jinja's own `tojson` escapes <, > and & for HTML; prompts want the text as is.
    _template_env.filters["json"] = lambda value: json.dumps(value, ensure_ascii=False, default=str)

    @inject
    def __init__(self, llm_client: llmClient, configuration_service: ConfigurationService):
        self.llm_client = llm_client
        self.configuration_service = configuration_service
        self._attachment_policy = None
        self._model_registry = None

    # =====================================================================
    # Platform settings
    # =====================================================================

    @classmethod
    def register_platform_settings_provider(cls,
                                            provider: Callable[[str], PlatformAgentSettings | None] | None) -> None:
        """`provider(agent_key)` returns the platform's settings for an agent, or None for the defaults."""
        cls._platform_settings_provider = provider

    @classmethod
    def platform_settings(cls, agent_key: str) -> PlatformAgentSettings:
        provider = cls._platform_settings_provider
        if provider is None:
            return PlatformAgentSettings()
        try:
            settings = provider(agent_key)
        except Exception as exc:
            # The platform's store unreachable must not stop the tenants' agents.
            logging.warning("Platform settings of system agent '%s' could not be read: %s", agent_key, exc)
            return PlatformAgentSettings()
        return settings if isinstance(settings, PlatformAgentSettings) else PlatformAgentSettings()

    @classmethod
    def is_enabled(cls, agent_key: str) -> bool:
        return cls.platform_settings(agent_key).enabled

    # =====================================================================
    # Running
    # =====================================================================

    def run(self,
            company: Company,
            agent_key: str,
            inputs: dict,
            *,
            user_identifier: str,
            question: str | None = None,
            attachments: list | None = None,
            images: list | None = None) -> dict:
        """
        The model's response (as llmClient.invoke returns it). Raises
        SystemAgentDisabled when the platform turned the agent off,
        SystemAgentUnavailable without a model, and whatever the model client
        raises when even the company's default model fails.

        `images` ({"name", "mime_type", "base64"}) go to the model as images. An
        agent that `requires_vision` only runs on models that take them; for any
        other agent they are dropped, with a log, when the model does not.
        """
        agent = SystemAgentCatalog.get(agent_key)
        platform = self.platform_settings(agent.key)
        if not platform.enabled:
            raise SystemAgentDisabled(f"system agent '{agent.key}' is turned off by the platform")
        resolved = self.resolve_model(company.short_name, agent, platform=platform)
        if not resolved.model:
            raise SystemAgentUnavailable(f"{company.short_name} has no model for system agent '{agent.key}'")
        prompt = self.render_prompt(agent, inputs)
        images = list(images or [])

        def invoke(model: str) -> dict:
            sent_images = images
            if images and not agent.requires_vision and not self.supports_images(company.short_name, model):
                logging.info("System agent '%s': model '%s' takes no images; %s dropped.", agent.key, model, len(images))
                sent_images = []
            return self.llm_client.invoke(
                company=company,
                user_identifier=user_identifier,
                question=question or agent.name,
                context=prompt,
                tools=[],
                text={},
                model=model,
                images=sent_images,
                attachments=list(attachments or []),
                response_contract=agent.response_contract(),
                execution_trace={"prompt_name": agent.prompt_name},
            )

        try:
            return invoke(resolved.model)
        except Exception as exc:
            fallback = self._company_default(company.short_name)
            if resolved.source == self.SOURCE_COMPANY or not fallback or fallback == resolved.model:
                raise
            if agent.requires_vision and not self.supports_images(company.short_name, fallback):
                raise
            logging.warning(
                "System agent '%s' failed with model '%s' (%s) for %s; retrying with the company default '%s': %s",
                agent.key, resolved.model, resolved.source, company.short_name, fallback, exc,
            )
            return invoke(fallback)

    @classmethod
    def render_prompt(cls, agent: SystemAgent, inputs: dict) -> str:
        missing = [name for name in agent.inputs if name not in (inputs or {})]
        if missing:
            raise ValueError(f"system agent '{agent.key}' is missing inputs: {', '.join(missing)}")
        template = cls._template_env.from_string(agent.prompt_template)
        return template.render(**(inputs or {})).strip()

    # =====================================================================
    # Model
    # =====================================================================

    def resolve_model(self,
                      company_short_name: str,
                      agent: SystemAgent,
                      llm_configuration: tuple | None = None,
                      platform: PlatformAgentSettings | None = None) -> ResolvedModel:
        """
        `llm_configuration` is get_llm_configuration's (default, available) and
        `platform` the agent's platform settings, when the caller already read
        them: resolving many agents then costs one read of each.
        """
        default_model, available = llm_configuration or self.configuration_service.get_llm_configuration(company_short_name)
        enabled = self._model_ids(available)
        needs_vision = bool(getattr(agent, "requires_vision", False))

        def usable(model: str | None) -> bool:
            # Without a list of models, the company's own configuration is the only judge.
            if not model or (enabled and model not in enabled):
                return False
            return not needs_vision or self.supports_images(company_short_name, model)

        chosen = self.tenant_choice(company_short_name, agent.key)
        ignored = None
        if chosen:
            if usable(chosen):
                return ResolvedModel(chosen, self.SOURCE_TENANT)
            ignored = chosen
            logging.warning(
                "System agent '%s' of %s: model '%s' is no longer enabled; using the next level.",
                agent.key, company_short_name, chosen,
            )
        platform = platform or self.platform_settings(agent.key)
        ignored_platform = None
        if platform.default_model:
            if usable(platform.default_model):
                return ResolvedModel(platform.default_model, self.SOURCE_PLATFORM, ignored)
            ignored_platform = platform.default_model
        if usable(agent.default_model):
            return ResolvedModel(agent.default_model, self.SOURCE_CATALOG, ignored, ignored_platform)
        if needs_vision:
            # The company's default has to read images too; else the first enabled model that does.
            for model in [default_model, *sorted(enabled)]:
                if usable(model):
                    return ResolvedModel(model, self.SOURCE_COMPANY, ignored, ignored_platform)
            return ResolvedModel(None, None, ignored, ignored_platform)
        return ResolvedModel(default_model or None, self.SOURCE_COMPANY if default_model else None,
                             ignored, ignored_platform)

    def supports_images(self, company_short_name: str, model: str | None) -> bool:
        """Whether the model takes native images: its provider's adapter sends them and,
        when the model catalogue knows it, the model accepts them (BL-009, Fase F)."""
        if not model:
            return False
        try:
            model_config = self.configuration_service.get_llm_model_config(company_short_name, model) or {}
        except Exception:
            model_config = {}
        provider = str(model_config.get("provider") or "").strip().lower()
        if not provider:
            if self._model_registry is None:
                self._model_registry = ModelRegistry()
            provider = self._model_registry.get_provider(model)
        if self._attachment_policy is None:
            self._attachment_policy = AttachmentPolicyService(self.configuration_service, Utility())
        try:
            capabilities = self._attachment_policy.get_effective_capabilities(company_short_name, provider, model)
        except Exception as exc:
            logging.warning("Capabilities of provider '%s' could not be read: %s", provider, exc)
            return False
        return bool(capabilities.get("supports_native_images"))

    def tenant_choice(self, company_short_name: str, agent_key: str) -> str | None:
        section = self._tenant_section(company_short_name)
        entry = section.get(agent_key)
        if not isinstance(entry, dict):
            return None
        return str(entry.get("model") or "").strip() or None

    def set_tenant_choice(self, company_short_name: str, agent_key: str, model: str | None) -> dict:
        """
        Saves the tenant's model for an agent in company.yaml, or removes it
        (None) to go back to the platform's choice. Only enabled models.
        """
        agent = SystemAgentCatalog.find(agent_key)
        if agent is None:
            return {"status": "error", "error_code": "unknown_agent", "error_message": f"unknown system agent '{agent_key}'"}
        model = str(model or "").strip() or None
        if model:
            _, available = self.configuration_service.get_llm_configuration(company_short_name)
            if model not in self._model_ids(available):
                return {"status": "error", "error_code": "model_not_enabled",
                        "error_message": f"model '{model}' is not enabled for this company"}
            if agent.requires_vision and not self.supports_images(company_short_name, model):
                return {"status": "error", "error_code": "model_without_vision",
                        "error_message": f"model '{model}' does not read images, and this agent does"}

        section = {
            key: dict(value)
            for key, value in self._tenant_section(company_short_name).items()
            if isinstance(value, dict)
        }
        entry = section.get(agent.key, {})
        if model:
            entry["model"] = model
            section[agent.key] = entry
        else:
            entry.pop("model", None)
            if entry:
                section[agent.key] = entry
            else:
                section.pop(agent.key, None)

        if section:
            _, errors = self.configuration_service.update_configuration_key(company_short_name, self.CONFIG_SECTION, section)
        else:
            # Every agent is back on the platform's choice: no empty section left in company.yaml.
            _, errors = self.configuration_service.remove_configuration_key(company_short_name, self.CONFIG_SECTION)
        if errors:
            return {"status": "error", "error_code": "invalid_configuration", "error_message": "; ".join(errors)}
        logging.info("System agent '%s' of %s now uses model %s.", agent.key, company_short_name, model or "(platform default)")
        return {"status": "success", "model": model}

    def _tenant_section(self, company_short_name: str) -> dict:
        try:
            section = self.configuration_service.get_configuration(company_short_name, self.CONFIG_SECTION)
        except Exception as exc:
            logging.warning("Could not read system_agents of %s: %s", company_short_name, exc)
            return {}
        return section if isinstance(section, dict) else {}

    def _company_default(self, company_short_name: str) -> str | None:
        default_model, _ = self.configuration_service.get_llm_configuration(company_short_name)
        return default_model or None

    @staticmethod
    def _model_ids(available) -> set[str]:
        ids = set()
        for entry in available or []:
            if isinstance(entry, dict):
                model_id = str(entry.get("id") or "").strip()
            else:
                model_id = str(entry or "").strip()
            if model_id:
                ids.add(model_id)
        return ids

    # =====================================================================
    # Describing (for the admin screens)
    # =====================================================================

    def describe(self, company_short_name: str, llm_configuration: tuple | None = None) -> list[dict]:
        """Every system agent with the model it runs with for this company."""
        llm_configuration = llm_configuration or self.configuration_service.get_llm_configuration(company_short_name)
        result = []
        for agent in SystemAgentCatalog.list():
            platform = self.platform_settings(agent.key)
            resolved = self.resolve_model(company_short_name, agent, llm_configuration, platform)
            result.append({
                "key": agent.key,
                "name": agent.name,
                "name_en": agent.name_en or agent.name,
                "description": agent.description,
                "description_en": agent.description_en or agent.description,
                "module": agent.module,
                "prompt_name": agent.prompt_name,
                "prompt": agent.prompt_template,
                "inputs": list(agent.inputs),
                "output_schema": agent.output_schema,
                "default_model": agent.default_model,
                "tenant_model": self.tenant_choice(company_short_name, agent.key),
                "effective_model": resolved.model,
                "model_source": resolved.source,
                "ignored_model": resolved.ignored_choice,
                "platform_model": platform.default_model,
                "ignored_platform_model": resolved.ignored_platform_model,
                "enabled": platform.enabled,
                "requires_vision": agent.requires_vision,
            })
        return result
