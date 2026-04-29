from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import logging
import threading

from injector import inject

from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.services.configuration_service import ConfigurationService


@dataclass
class TelemetryExecution:
    enabled: bool = False
    record_stats: bool = False
    provider: str | None = None
    project: str | None = None
    disabled_reason: str | None = None
    runtime_error: str | None = None
    span: Any | None = None
    bridge: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    trace_url: str | None = None
    _finalized: bool = False

    def finalize(
        self,
        *,
        query_id: int | None = None,
        success: bool | None = None,
        answer_preview: str | None = None,
        metrics: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        if self._finalized:
            return
        self._finalized = True

        if not self.enabled or not self.span or not self.bridge:
            return

        try:
            metadata: dict[str, Any] = {}
            if query_id is not None:
                metadata["query_id"] = query_id
            if success is not None:
                metadata["valid_response"] = bool(success)
            if error_message:
                metadata["error_message"] = str(error_message)
            if metrics:
                metadata["metrics"] = dict(metrics)

            event: dict[str, Any] = {}
            if metadata:
                event["metadata"] = metadata
            if answer_preview:
                event["output"] = {"answer_preview": str(answer_preview)[:1000]}
            if event:
                self.bridge.log_span(self.span, event)
        except Exception as exc:
            logging.debug("Telemetry finalization log failed: %s", exc)

        try:
            self.bridge.end_span(self.span)
        except Exception as exc:
            logging.debug("Telemetry span end failed: %s", exc)

        self.trace_id = str(getattr(self.span, "id", "") or "").strip() or None
        try:
            self.trace_url = self.bridge.get_trace_url(self.span)
        except Exception as exc:
            logging.debug("Telemetry trace URL resolution failed: %s", exc)
            self.trace_url = None

    def build_stats(self) -> dict[str, Any] | None:
        if not self.record_stats:
            return None

        payload: dict[str, Any] = {
            "enabled": bool(self.enabled),
            "provider": self.provider,
        }
        if self.project:
            payload["project"] = self.project
        if self.disabled_reason:
            payload["reason"] = self.disabled_reason
        if self.runtime_error:
            payload["runtime_error"] = self.runtime_error
        if self.trace_id:
            payload["trace_id"] = self.trace_id
        if self.trace_url:
            payload["trace_url"] = self.trace_url
        return payload


class NoopTelemetryService:
    def resolve_execution_request(self, **kwargs) -> dict[str, Any]:
        return {}

    def start_execution(self, request: dict[str, Any] | None) -> TelemetryExecution:
        return TelemetryExecution()


class BraintrustTelemetryBridge:
    _instrumented = False
    _instrument_lock = threading.Lock()
    _logger_cache: dict[tuple[str, str, str], Any] = {}
    _logger_lock = threading.Lock()

    def __init__(self) -> None:
        self._braintrust = None

    def start_execution(self, request: dict[str, Any]) -> TelemetryExecution:
        project = str(request.get("project") or "").strip()
        api_key = str(request.get("api_key") or "").strip()
        app_url = str(request.get("api_url") or "").strip()
        metadata = dict(request.get("metadata") or {})

        if not project:
            return TelemetryExecution(
                enabled=False,
                record_stats=True,
                provider="braintrust",
                disabled_reason="project_missing",
            )
        if not api_key:
            return TelemetryExecution(
                enabled=False,
                record_stats=True,
                provider="braintrust",
                project=project,
                disabled_reason="api_key_missing",
            )

        self._ensure_runtime()
        logger = self._get_or_create_logger(project=project, api_key=api_key, app_url=app_url)
        span = self.start_span(
            logger,
            name=str(request.get("execution_name") or "iatoolkit.llm_execution"),
            span_type="task",
            event={"metadata": metadata},
        )

        return TelemetryExecution(
            enabled=True,
            record_stats=True,
            provider="braintrust",
            project=project,
            span=span,
            bridge=self,
            metadata=metadata,
        )

    def _ensure_runtime(self) -> None:
        if self._braintrust is not None and self._instrumented:
            return

        with self._instrument_lock:
            if self._braintrust is None:
                try:
                    import braintrust  # type: ignore
                except Exception as exc:  # pragma: no cover - exercised through runtime fallback
                    raise RuntimeError(
                        "Braintrust SDK is not installed. Add 'braintrust' to the project dependencies."
                    ) from exc
                self._braintrust = braintrust

            if not self._instrumented:
                self._braintrust.auto_instrument(
                    openai=True,
                    anthropic=True,
                    google_genai=True,
                )
                self._instrumented = True

    def _get_or_create_logger(self, *, project: str, api_key: str, app_url: str) -> Any:
        cache_key = (project, api_key, app_url)
        with self._logger_lock:
            if cache_key in self._logger_cache:
                return self._logger_cache[cache_key]

            init_kwargs: dict[str, Any] = {
                "project": project,
                "api_key": api_key,
                "set_current": False,
            }
            if app_url:
                init_kwargs["app_url"] = app_url
            logger = self._braintrust.init_logger(**init_kwargs)
            self._logger_cache[cache_key] = logger
            return logger

    def start_span(self, parent: Any, *, name: str, span_type: str, event: dict[str, Any]) -> Any:
        start_kwargs = {
            "name": name,
            "type": span_type,
            "set_current": True,
        }

        try:
            return parent.start_span(event=event, **start_kwargs)
        except TypeError:
            try:
                return parent.start_span(**start_kwargs, **event)
            except TypeError:
                span = parent.start_span(**start_kwargs)
                self.log_span(span, event)
                return span

    @staticmethod
    def log_span(span: Any, event: dict[str, Any]) -> None:
        if not event:
            return
        try:
            span.log(event)
        except TypeError:
            span.log(**event)

    @staticmethod
    def end_span(span: Any) -> None:
        span.end()
        flush = getattr(span, "flush", None)
        if callable(flush):
            flush()

    @staticmethod
    def get_trace_url(span: Any) -> str | None:
        link = getattr(span, "link", None)
        if callable(link):
            candidate = link()
            if candidate:
                return str(candidate)

        permalink = getattr(span, "permalink", None)
        if callable(permalink):
            candidate = permalink()
            if candidate:
                return str(candidate)

        return None


class TelemetryService:
    PROVIDER_BRAINTRUST = "braintrust"

    @inject
    def __init__(
        self,
        configuration_service: ConfigurationService,
        secret_provider: SecretProvider,
    ):
        self.configuration_service = configuration_service
        self.secret_provider = secret_provider
        self._braintrust_bridge = BraintrustTelemetryBridge()

    def resolve_execution_request(
        self,
        *,
        company_short_name: str,
        prompt_output_contract: dict | None,
        model: str | None,
        provider: str | None,
        task_id: int | None,
        user_identifier: str | None,
        execution_metadata: dict | None = None,
        request_metadata: dict | None = None,
    ) -> dict[str, Any]:
        prompt_options = dict((prompt_output_contract or {}).get("llm_request_options") or {})
        if prompt_options.get("telemetry_enabled") is not True:
            return {}

        telemetry_config = self.configuration_service.get_llm_telemetry_config(company_short_name) or {}
        provider_name = str(telemetry_config.get("provider") or "").strip().lower()
        enabled = bool(telemetry_config.get("enabled"))
        prompt_name = str((prompt_output_contract or {}).get("prompt_name") or "").strip()
        execution_mode = str((prompt_output_contract or {}).get("execution_mode") or "").strip().lower() or None
        request: dict[str, Any] = {
            "requested": True,
            "record_stats": True,
            "company_short_name": company_short_name,
            "provider": provider_name or None,
            "metadata": {
                "company": str(company_short_name or "").strip() or None,
                "agent_name": prompt_name or None,
                "provider": provider,
                "model": model,
                "task_id": task_id,
                "user_identifier": user_identifier,
                "execution_mode": execution_mode,
            },
            "execution_name": prompt_name or "iatoolkit.llm_execution",
        }

        if isinstance(request_metadata, dict):
            prompt_version = str(request_metadata.get("prompt_version") or "").strip()
            prompt_variant = str(request_metadata.get("prompt_variant") or "").strip()
            if prompt_version:
                request["metadata"]["prompt_version"] = prompt_version
            if prompt_variant:
                request["metadata"]["prompt_variant"] = prompt_variant

        if isinstance(execution_metadata, dict):
            structured_output = execution_metadata.get("structured_output")
            if isinstance(structured_output, dict):
                request["metadata"]["structured_output"] = dict(structured_output)

            tool_router = execution_metadata.get("tool_router")
            if isinstance(tool_router, dict):
                request["metadata"]["tool_router"] = dict(tool_router)

            llm_request_options = execution_metadata.get("llm_request_options")
            if isinstance(llm_request_options, dict):
                request["metadata"]["llm_request_options"] = dict(llm_request_options)

            attachments = execution_metadata.get("attachments")
            if isinstance(attachments, dict):
                attachment_metadata: dict[str, Any] = {}
                if isinstance(attachments.get("stats"), dict):
                    attachment_metadata["stats"] = dict(attachments.get("stats") or {})
                if attachments.get("provider") is not None:
                    attachment_metadata["provider"] = attachments.get("provider")
                if isinstance(attachments.get("policy"), dict):
                    attachment_metadata["policy"] = dict(attachments.get("policy") or {})
                if attachment_metadata:
                    request["metadata"]["attachments"] = attachment_metadata

        if not enabled:
            request["disabled_reason"] = "company_disabled"
            return request

        if provider_name != self.PROVIDER_BRAINTRUST:
            request["disabled_reason"] = "provider_unsupported"
            return request

        provider_config = telemetry_config.get(self.PROVIDER_BRAINTRUST)
        if not isinstance(provider_config, dict):
            request["disabled_reason"] = "provider_config_missing"
            return request

        project = str(provider_config.get("project") or "").strip()
        api_key_ref = str(provider_config.get("api_key") or "").strip()
        api_url = str(provider_config.get("api_url") or "").strip()

        if not project:
            request["disabled_reason"] = "project_missing"
            return request
        if not api_key_ref:
            request["disabled_reason"] = "api_key_missing"
            return request

        api_key_value = str(
            resolve_secret(
                self.secret_provider,
                company_short_name,
                api_key_ref,
                default="",
            ) or ""
        ).strip()
        if not api_key_value:
            request["disabled_reason"] = "api_key_unresolved"
            request["project"] = project
            return request

        request.update({
            "enabled": True,
            "project": project,
            "api_key": api_key_value,
            "api_url": api_url,
        })
        return request

    def start_execution(self, request: dict[str, Any] | None) -> TelemetryExecution:
        if not isinstance(request, dict) or not request.get("requested"):
            return TelemetryExecution()

        if not request.get("enabled"):
            return TelemetryExecution(
                enabled=False,
                record_stats=bool(request.get("record_stats")),
                provider=request.get("provider"),
                project=request.get("project"),
                disabled_reason=str(request.get("disabled_reason") or "").strip() or None,
                metadata=dict(request.get("metadata") or {}),
            )

        provider_name = str(request.get("provider") or "").strip().lower()
        if provider_name != self.PROVIDER_BRAINTRUST:
            return TelemetryExecution(
                enabled=False,
                record_stats=bool(request.get("record_stats")),
                provider=provider_name or None,
                project=request.get("project"),
                disabled_reason="provider_unsupported",
                metadata=dict(request.get("metadata") or {}),
            )

        try:
            return self._braintrust_bridge.start_execution(request)
        except Exception as exc:
            logging.warning(
                "Telemetry runtime unavailable for company '%s': %s",
                request.get("company_short_name"),
                exc,
            )
            return TelemetryExecution(
                enabled=False,
                record_stats=bool(request.get("record_stats")),
                provider=provider_name,
                project=request.get("project"),
                disabled_reason="runtime_error",
                runtime_error=str(exc),
                metadata=dict(request.get("metadata") or {}),
            )
