# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Runs a decision model on a case (BL-008).

It sits beside `LLMProxy`, not inside it: a decision model answers questions with
probabilities instead of writing text, so it shares the proxy's credentials and
endpoint but none of its adapters.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from injector import inject

from iatoolkit.common.decision_types import (
    DecisionResult,
    DecisionSpecError,
    parse_decision_spec,
)
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_proxy import LLMProxy
from iatoolkit.infra.openrouter_decision_client import OpenRouterDecisionClient
from iatoolkit.services.configuration_service import ConfigurationService

DECISION_MODEL_KIND = "decision"
DECISION_PROVIDER = "openrouter"
#: Characters per token, to warn about a state that will not fit. A rough
#: estimate on purpose: the model counts, this only says when to look.
_CHARS_PER_TOKEN = 4


def model_kind(model_config: dict | None) -> str:
    """The kind of model a configuration describes: "decision" or "" for chat.

    Comes from the catalogue (`capabilities.kind`, written by `models-sync`); a
    company.yaml entry outside the catalogue may state it at the top level.
    """
    if not isinstance(model_config, dict):
        return ""
    capabilities = model_config.get("capabilities")
    kind = capabilities.get("kind") if isinstance(capabilities, dict) else None
    return str(kind or model_config.get("kind") or "").strip().lower()


def is_decision_model(model_config: dict | None) -> bool:
    return model_kind(model_config) == DECISION_MODEL_KIND


class DecisionService:

    @inject
    def __init__(
        self,
        configuration_service: ConfigurationService,
        llm_proxy: LLMProxy,
        client: OpenRouterDecisionClient | None = None,
    ):
        self.configuration_service = configuration_service
        self.llm_proxy = llm_proxy
        self.client = client or OpenRouterDecisionClient()

    def decisions_config(self, company_short_name: str) -> dict:
        """`llm.decisions` of the company: data policy (`provider`) and endpoint `path`."""
        llm_config = self.configuration_service.get_configuration(company_short_name, "llm") or {}
        decisions = llm_config.get("decisions") if isinstance(llm_config, dict) else None
        return dict(decisions) if isinstance(decisions, dict) else {}

    def resolve_model_config(self, company_short_name: str, model: str) -> dict:
        """The configuration of a decision model the company may use, or an error.

        Aliases are refused: OpenRouter accepts `~typesafe/jev-latest`, and a
        decision that changes model underneath cannot be audited or compared.
        """
        model_key = str(model or "").strip()
        if not model_key:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MODEL,
                "A decision agent needs a decision model; none was set and the company has no default.",
            )
        if model_key.startswith("~"):
            raise IAToolkitException(
                IAToolkitException.ErrorType.MODEL,
                f"'{model_key}' is an alias. A decision agent needs a fixed model version.",
            )

        _default_model, available_models = self.configuration_service.get_llm_configuration(company_short_name)
        enabled = {str((entry or {}).get("id") or "").strip() for entry in available_models or [] if isinstance(entry, dict)}
        model_config = self.configuration_service.get_llm_model_config(company_short_name, model_key)
        if model_key not in enabled or not is_decision_model(model_config):
            raise IAToolkitException(
                IAToolkitException.ErrorType.MODEL,
                f"Model '{model_key}' is not a decision model enabled for this company.",
            )

        provider = str(model_config.get("provider") or "").strip().lower() or DECISION_PROVIDER
        if provider != DECISION_PROVIDER:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MODEL,
                f"Decision model '{model_key}' is routed to '{provider}'; only OpenRouter serves decision models.",
            )
        return model_config

    def decide(
        self,
        company_short_name: str,
        *,
        model: str,
        state: Any,
        decision_spec: dict,
        user_identifier: str | None = None,
        telemetry_execution: Any = None,
    ) -> DecisionResult:
        try:
            questions = parse_decision_spec(decision_spec)
        except DecisionSpecError as exc:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, str(exc)) from exc

        model_config = self.resolve_model_config(company_short_name, model)
        model_key = str(model).strip()

        # Sent as text by default: ScaleDown refuses a JSON state, and every model
        # tested reads text. The template already renders the case as text.
        state_text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, default=str)
        if not state_text.strip():
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "The case to decide on is empty: the agent template rendered no text.",
            )
        self._warn_if_too_long(company_short_name, model_key, model_config, state_text)

        client_config = self.llm_proxy.resolve_client_config(
            company_short_name, DECISION_PROVIDER, model_config=model_config
        )
        decisions_config = self.decisions_config(company_short_name)
        provider_policy = decisions_config.get("provider")
        url = self.client.decisions_url(client_config.get("base_url"), decisions_config.get("path"))
        wire_model = self.llm_proxy.wire_model(model_key, model_config)

        span = None
        if telemetry_execution is not None:
            span = telemetry_execution.start_child_span(
                name="iatoolkit.decision",
                span_type="llm",
                event={
                    "input": {"state": state_text, "questions": {n: q.to_wire() for n, q in questions.items()}},
                    "metadata": {"model": wire_model, "company": company_short_name},
                },
            )

        # Everything the call needs from the database is resolved by now.
        LLMProxy._release_database_transaction()
        try:
            result = self.client.decide(
                api_key=client_config.get("api_key") or "",
                url=url,
                model=wire_model,
                state=state_text,
                questions=questions,
                provider_policy=provider_policy if isinstance(provider_policy, dict) else None,
                default_headers=client_config.get("default_headers") or {},
                connect_timeout_seconds=client_config.get("connect_timeout_seconds") or 10.0,
                read_timeout_seconds=client_config.get("read_timeout_seconds") or 60.0,
                user=user_identifier,
            )
        except Exception as exc:
            if span is not None:
                telemetry_execution.log_child_span(span, {"error": str(exc)})
                telemetry_execution.end_child_span(span)
            raise

        if span is not None:
            telemetry_execution.log_child_span(span, {
                "output": result.answers_dict(),
                "metadata": {"resolved_model": result.model, "provider": result.provider},
                "metrics": {
                    "prompt_tokens": result.input_tokens,
                    "completion_tokens": result.output_tokens,
                    "latency_ms": result.latency_ms,
                },
            })
            telemetry_execution.end_child_span(span)

        logging.info(
            "Decision model '%s' (%s) answered %s question(s) for '%s' in %s ms, cost=%s",
            result.model, result.provider, len(result.answers), company_short_name,
            result.latency_ms, result.cost_usd,
        )
        return result

    @staticmethod
    def _warn_if_too_long(company_short_name: str, model: str, model_config: dict, state_text: str) -> None:
        try:
            context_window = int(model_config.get("context_window") or 0)
        except (TypeError, ValueError):
            context_window = 0
        estimated_tokens = len(state_text) // _CHARS_PER_TOKEN
        if context_window and estimated_tokens > context_window:
            logging.warning(
                "Decision case for '%s' on '%s' is ~%s tokens, over the model's %s-token window.",
                company_short_name, model, estimated_tokens, context_window,
            )
