# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""HTTP client for OpenRouter's decision models (BL-008).

Decision models are not served by the chat completions API, so the OpenAI SDK
the proxy uses for OpenRouter cannot call them: this is a plain HTTP call to
`/api/alpha/decisions`. Credentials, endpoint and timeouts are the ones the
company already has for `openrouter`, resolved by `LLMProxy`.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from iatoolkit.common.decision_types import DecisionQuestion, DecisionResult
from iatoolkit.common.exceptions import IAToolkitException

DEFAULT_DECISIONS_PATH = "/api/alpha/decisions"
#: Relative to a gateway's OpenRouter base, which stands for `/api/v1`.
GATEWAY_DECISIONS_SUFFIX = "/systemone"
OPENROUTER_HOSTS = {"openrouter.ai", "www.openrouter.ai"}
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
DEFAULT_RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5


class OpenRouterDecisionClient:

    def __init__(self, http_client: httpx.Client | None = None, sleep=time.sleep):
        self._http_client = http_client
        self._sleep = sleep

    @staticmethod
    def decisions_url(base_url: str | None, path: str | None = None) -> str:
        """The decisions endpoint for the company's OpenRouter base URL.

        The configured `base_url` is the chat one, which stands for OpenRouter's
        `/api/v1` wherever it points. On openrouter.ai itself the decisions
        router sits outside that prefix, at `/api/alpha/decisions`. Anything else
        is a gateway or proxy that exposes only `/api/v1` under its own path —
        Cloudflare AI Gateway answers 404 to the alpha router — so the same
        contract is reached at `{base_url}/systemone`, which serves every
        decision model (measured through Maxxa's Cloudflare gateway, 2026-11-18).

        An explicit `path` (`llm.decisions.path`) is taken as is, on the origin.
        """
        raw_base = str(base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        parts = urlsplit(raw_base)
        origin = f"{parts.scheme or 'https'}://{parts.netloc or 'openrouter.ai'}"
        explicit_path = str(path or "").strip()
        if explicit_path:
            return f"{origin}{explicit_path if explicit_path.startswith('/') else '/' + explicit_path}"
        if (parts.netloc or "").lower() in OPENROUTER_HOSTS:
            return f"{origin}{DEFAULT_DECISIONS_PATH}"
        return f"{raw_base.rstrip('/')}{GATEWAY_DECISIONS_SUFFIX}"

    def decide(
        self,
        *,
        api_key: str,
        url: str,
        model: str,
        state: Any,
        questions: dict[str, DecisionQuestion],
        provider_policy: dict[str, Any] | None = None,
        default_headers: dict[str, str] | None = None,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 60.0,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        user: str | None = None,
        assets: dict[str, dict[str, str]] | None = None,
    ) -> DecisionResult:
        payload: dict[str, Any] = {
            "model": model,
            "state": state,
            "questions": {name: question.to_wire() for name, question in questions.items()},
        }
        if assets:
            payload["assets"] = assets
        if provider_policy:
            payload["provider"] = dict(provider_policy)
        if user:
            payload["user"] = user

        headers = dict(default_headers or {})
        # Behind a gateway that holds the provider key (Cloudflare's
        # cloudflare_managed mode) there is no key to send; an empty bearer is an
        # illegal header value, so the header is left out and the gateway's own
        # headers authenticate the call.
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers["Content-Type"] = "application/json"
        timeout = httpx.Timeout(read_timeout_seconds, connect=connect_timeout_seconds)

        attempts = max(0, int(retry_attempts)) + 1
        started = time.monotonic()
        last_error: str | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._post(url, payload, headers, timeout)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < attempts:
                    self._backoff(attempt)
                    continue
                raise IAToolkitException(
                    IAToolkitException.ErrorType.LLM_ERROR,
                    f"Decision model '{model}' could not be reached: {last_error}",
                ) from exc

            if response.status_code == 200:
                body = self._json_body(response)
                if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.LLM_ERROR,
                        f"Decision model '{model}' returned a response without answers.",
                    )
                latency_ms = int((time.monotonic() - started) * 1000)
                return DecisionResult.from_response(body, requested_model=model, latency_ms=latency_ms)

            message = self._error_message(response)
            # With images, a 5xx is how an oversized request answers (measured: a
            # bare 500); sending it again only repeats it. Rate limits still retry.
            retryable = response.status_code in RETRYABLE_STATUS and (
                not assets or response.status_code == 429
            )
            if retryable and attempt < attempts:
                logging.warning(
                    "Decision model '%s' answered %s (attempt %s/%s): %s",
                    model, response.status_code, attempt, attempts, message,
                )
                last_error = message
                self._backoff(attempt)
                continue
            raise self._error_for(model, response.status_code, message)

        raise IAToolkitException(  # pragma: no cover - the loop always returns or raises
            IAToolkitException.ErrorType.LLM_ERROR,
            f"Decision model '{model}' failed: {last_error}",
        )

    def _post(self, url: str, payload: dict, headers: dict, timeout: httpx.Timeout) -> httpx.Response:
        if self._http_client is not None:
            return self._http_client.post(url, json=payload, headers=headers, timeout=timeout)
        with httpx.Client(timeout=timeout) as client:
            return client.post(url, json=payload, headers=headers)

    def _backoff(self, attempt: int) -> None:
        self._sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

    @staticmethod
    def _json_body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    @classmethod
    def _error_message(cls, response: httpx.Response) -> str:
        body = cls._json_body(response)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if isinstance(error, str):
                return error
        return (response.text or "").strip()[:300] or f"HTTP {response.status_code}"

    @staticmethod
    def _error_for(model: str, status_code: int, message: str) -> IAToolkitException:
        if status_code == 404:
            # What a data policy that leaves no endpoint looks like: OpenRouter
            # found the model but no provider serving it under the policy sent.
            return IAToolkitException(
                IAToolkitException.ErrorType.MODEL,
                f"Decision model '{model}' is not available under the company's data policy "
                f"(llm.decisions.provider): {message}",
            )
        if status_code in (401, 403):
            return IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                f"OpenRouter refused the credentials for decision model '{model}': {message}",
            )
        if status_code == 400:
            return IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Decision model '{model}' rejected the request: {message}",
            )
        return IAToolkitException(
            IAToolkitException.ErrorType.LLM_ERROR,
            f"Decision model '{model}' failed with HTTP {status_code}: {message}",
        )
