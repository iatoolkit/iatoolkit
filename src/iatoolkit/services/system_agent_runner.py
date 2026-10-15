# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from injector import inject
from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from iatoolkit.repositories.models import Company
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.system_agent_catalog import SystemAgent, SystemAgentCatalog


class SystemAgentUnavailable(Exception):
    """The company has no model to run the agent with."""


@dataclass(frozen=True)
class ResolvedModel:
    model: str | None
    # Where it came from: "tenant" (company.yaml), "catalog" (the agent's default)
    # or "company" (the company's default model).
    source: str | None
    # The tenant's choice when it could not be used (no longer enabled).
    ignored_choice: str | None = None


class SystemAgentRunner:
    """
    Runs a system agent (see system_agent_catalog): renders its prompt with the
    inputs the caller built, resolves the model and calls it with the agent's
    output contract. Interpreting and repairing the answer stays with the caller.

    The model is resolved from the most specific to the most general: the one the
    tenant picked (`system_agents.<key>.model` in company.yaml), the agent's
    default in the catalog, the company's default model. A pick that is no
    longer among the company's models falls through to the next level, and a
    call that fails with a picked model is retried once with the company's
    default, so a bad choice never stops the agent.

    Deliberately light: it does not go through tasks or the agent runtime, so
    the services that use it gain no dependency beyond the model client.
    """

    CONFIG_SECTION = "system_agents"
    SOURCE_TENANT = "tenant"
    SOURCE_CATALOG = "catalog"
    SOURCE_COMPANY = "company"

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
            attachments: list | None = None) -> dict:
        """
        The model's response (as llmClient.invoke returns it). Raises
        SystemAgentUnavailable without a model, and whatever the model client
        raises when even the company's default model fails.
        """
        agent = SystemAgentCatalog.get(agent_key)
        resolved = self.resolve_model(company.short_name, agent)
        if not resolved.model:
            raise SystemAgentUnavailable(f"{company.short_name} has no model for system agent '{agent.key}'")
        prompt = self.render_prompt(agent, inputs)

        def invoke(model: str) -> dict:
            return self.llm_client.invoke(
                company=company,
                user_identifier=user_identifier,
                previous_response_id=None,
                question=question or agent.name,
                context=prompt,
                tools=[],
                text={},
                model=model,
                images=[],
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
                      llm_configuration: tuple | None = None) -> ResolvedModel:
        """
        `llm_configuration` is get_llm_configuration's (default, available) when
        the caller already read it: resolving many agents then costs one read,
        which in enterprise is a query to the model catalogue.
        """
        default_model, available = llm_configuration or self.configuration_service.get_llm_configuration(company_short_name)
        enabled = self._model_ids(available)

        def usable(model: str | None) -> bool:
            # Without a list of models, the company's own configuration is the only judge.
            return bool(model) and (not enabled or model in enabled)

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
        if usable(agent.default_model):
            return ResolvedModel(agent.default_model, self.SOURCE_CATALOG, ignored)
        return ResolvedModel(default_model or None, self.SOURCE_COMPANY if default_model else None, ignored)

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
            resolved = self.resolve_model(company_short_name, agent, llm_configuration)
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
            })
        return result
