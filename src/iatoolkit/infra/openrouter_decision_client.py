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
        """The decisions endpoint on the company's OpenRouter host.

        The configured `base_url` is the chat one (`https://openrouter.ai/api/v1`);
        the decisions router lives on the same host under its own path, so only
        the origin is kept. A gateway in front of OpenRouter keeps working as long
        as it forwards that path.
        """
        parts = urlsplit(str(base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL)
        origin = f"{parts.scheme or 'https'}://{parts.netloc or 'openrouter.ai'}"
        decision_path = str(path or DEFAULT_DECISIONS_PATH).strip() or DEFAULT_DECISIONS_PATH
        if not decision_path.startswith("/"):
            decision_path = f"/{decision_path}"
        return f"{origin}{decision_path}"

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
    ) -> DecisionResult:
        payload: dict[str, Any] = {
            "model": model,
            "state": state,
            "questions": {name: question.to_wire() for name, question in questions.items()},
        }
        if provider_policy:
            payload["provider"] = dict(provider_policy)
        if user:
            payload["user"] = user

        headers = dict(default_headers or {})
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
            if response.status_code in RETRYABLE_STATUS and attempt < attempts:
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
