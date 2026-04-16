# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
import ipaddress
import json
import socket
from urllib.parse import urlparse
from injector import inject
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.services.configuration_service import ConfigurationService


class HttpToolService:
    @inject
    def __init__(self,
                 call_service: CallServiceClient,
                 secret_provider: SecretProvider,
                 config_service: ConfigurationService):
        self.call_service = call_service
        self.secret_provider = secret_provider
        self.config_service = config_service

    def execute(self,
                company_short_name: str,
                tool_name: str,
                execution_config: dict,
                input_data: dict) -> dict:
        if not isinstance(execution_config, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Invalid execution_config for HTTP tool '{tool_name}'"
            )

        request_cfg = execution_config.get("request") or {}
        method = str(request_cfg.get("method", "")).upper()
        url = str(request_cfg.get("url", ""))

        if not method or not url:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Invalid request config for HTTP tool '{tool_name}'"
            )

        params = self._build_query_params(request_cfg, input_data)
        url = self._render_path_params(url, request_cfg, input_data)
        self._validate_target_url(company_short_name, execution_config, url)

        headers = dict(request_cfg.get("headers") or {})
        self._apply_auth(company_short_name, execution_config, headers, params)

        json_payload = self._build_json_payload(request_cfg, input_data)
        timeout_ms = request_cfg.get("timeout_ms") or 30000
        timeout = (5, float(timeout_ms) / 1000.0)

        response_data, status_code = self._call(method, url, params, headers, json_payload, timeout)

        return self._build_response(
            tool_name=tool_name,
            execution_config=execution_config,
            response_data=response_data,
            status_code=status_code,
        )

    def _call(self,
              method: str,
              url: str,
              params: dict,
              headers: dict,
              json_payload: dict | None,
              timeout):
        if method == "GET":
            return self.call_service.get(url, params=params, headers=headers, timeout=timeout)
        if method == "POST":
            return self.call_service.post(url, json_dict=json_payload, params=params, headers=headers, timeout=timeout)
        if method == "PUT":
            return self.call_service.put(url, json_dict=json_payload, params=params, headers=headers, timeout=timeout)
        if method == "PATCH":
            return self.call_service.patch(url, json_dict=json_payload, params=params, headers=headers, timeout=timeout)
        if method == "DELETE":
            return self.call_service.delete(url, json_dict=json_payload, params=params, headers=headers, timeout=timeout)

        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"HTTP method '{method}' is not supported"
        )

    def _validate_target_url(self, company_short_name: str, execution_config: dict, url: str):
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().lower()

        if parsed.scheme.lower() != "https" or not host:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "HTTP tools require an absolute HTTPS URL"
            )

        if host == "localhost" or host.endswith(".local"):
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"HTTP tool target host '{host}' is not allowed"
            )

        ip_value = self._to_ip_or_none(host)
        if ip_value:
            self._assert_public_ip(ip_value)
        else:
            self._assert_public_dns_target(host)

        allowed_hosts = self._resolve_allowed_hosts(company_short_name, execution_config)
        if allowed_hosts and not self._host_in_allowlist(host, allowed_hosts):
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"HTTP tool target host '{host}' is not in allowed_hosts"
            )

    @staticmethod
    def _to_ip_or_none(host: str):
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    def _assert_public_dns_target(self, hostname: str):
        # Best effort DNS check to reduce SSRF risk when DNS resolves to private ranges.
        try:
            entries = socket.getaddrinfo(hostname, None)
        except Exception:
            # If DNS cannot be resolved here, let the outbound request fail naturally.
            return

        for entry in entries:
            sockaddr = entry[4]
            if not sockaddr:
                continue
            ip_text = sockaddr[0]
            ip_value = self._to_ip_or_none(ip_text)
            if ip_value:
                self._assert_public_ip(ip_value)

    @staticmethod
    def _assert_public_ip(ip_value):
        if (ip_value.is_private or
                ip_value.is_loopback or
                ip_value.is_link_local or
                ip_value.is_reserved or
                ip_value.is_multicast or
                ip_value.is_unspecified):
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"HTTP tool target IP '{ip_value}' is not allowed"
            )

    def _resolve_allowed_hosts(self, company_short_name: str, execution_config: dict) -> list[str]:
        security_cfg = execution_config.get("security") or {}
        allowed_hosts = security_cfg.get("allowed_hosts")

        if allowed_hosts is None:
            company_params = self.config_service.get_configuration(company_short_name, "parameters") or {}
            http_tools_cfg = company_params.get("http_tools") or {}
            allowed_hosts = http_tools_cfg.get("allowed_hosts")

        if allowed_hosts is None:
            return []

        if not isinstance(allowed_hosts, list):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "allowed_hosts must be a list of host patterns"
            )

        normalized = []
        for host in allowed_hosts:
            if not isinstance(host, str) or not host.strip():
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "allowed_hosts must contain non-empty strings"
                )
            normalized.append(host.strip().lower())

        return normalized

    def _host_in_allowlist(self, host: str, allowed_hosts: list[str]) -> bool:
        for allowed in allowed_hosts:
            if self._host_matches_pattern(host, allowed):
                return True
        return False

    @staticmethod
    def _host_matches_pattern(host: str, pattern: str) -> bool:
        if pattern.startswith("*."):
            suffix = pattern[1:]  # includes leading dot
            return host.endswith(suffix)
        return host == pattern

    def _build_query_params(self, request_cfg: dict, input_data: dict) -> dict:
        query_map = request_cfg.get("query_params") or {}
        params = {}
        for query_key, input_key in query_map.items():
            if input_key in input_data and input_data[input_key] is not None:
                params[query_key] = input_data[input_key]
        return params

    def _render_path_params(self, url: str, request_cfg: dict, input_data: dict) -> str:
        path_map = request_cfg.get("path_params") or {}
        rendered = url

        for placeholder, input_key in path_map.items():
            if input_key not in input_data:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.MISSING_PARAMETER,
                    f"Missing required path parameter '{input_key}'"
                )
            rendered = rendered.replace(f"{{{placeholder}}}", str(input_data[input_key]))

        return rendered

    def _build_json_payload(self, request_cfg: dict, input_data: dict) -> dict | None:
        body_cfg = request_cfg.get("body") or {}
        mode = str(body_cfg.get("mode", "none")).lower()

        if mode == "none":
            return None

        if mode == "full_args":
            return dict(input_data)

        if mode == "json_map":
            json_map = body_cfg.get("json_map") or {}
            payload = {}
            for output_key, input_key in json_map.items():
                if input_key not in input_data:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.MISSING_PARAMETER,
                        f"Missing required body parameter '{input_key}'"
                    )
                payload[output_key] = input_data[input_key]
            return payload

        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"Invalid request body mode '{mode}'"
        )

    def _apply_auth(self,
                    company_short_name: str,
                    execution_config: dict,
                    headers: dict,
                    params: dict):
        auth_cfg = execution_config.get("auth") or {}
        auth_type = str(auth_cfg.get("type", "none")).lower()

        if auth_type == "none":
            return

        if auth_type == "bearer":
            secret = self._resolve_secret(company_short_name, auth_cfg.get("secret_ref"))
            headers["Authorization"] = f"Bearer {secret}"
            return

        if auth_type == "api_key_header":
            secret = self._resolve_secret(company_short_name, auth_cfg.get("secret_ref"))
            header_name = auth_cfg.get("header_name")
            headers[header_name] = secret
            return

        if auth_type == "api_key_query":
            secret = self._resolve_secret(company_short_name, auth_cfg.get("secret_ref"))
            query_param = auth_cfg.get("query_param")
            params[query_param] = secret
            return

        if auth_type == "basic":
            username = self._resolve_secret(company_short_name, auth_cfg.get("username_secret_ref"))
            password = self._resolve_secret(company_short_name, auth_cfg.get("password_secret_ref"))
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
            return

        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"Unsupported auth type '{auth_type}'"
        )

    def _resolve_secret(self, company_short_name: str, secret_ref: str | None) -> str:
        if not secret_ref:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "Missing required auth secret reference"
            )

        secret = self.secret_provider.get_secret(company_short_name, secret_ref)
        if not secret:
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                f"Secret '{secret_ref}' not found"
            )

        return secret

    def _build_response(self,
                        tool_name: str,
                        execution_config: dict,
                        response_data,
                        status_code: int) -> dict:
        response_cfg = execution_config.get("response") or {}
        success_codes = response_cfg.get("success_status_codes") or [200]
        mode = str(response_cfg.get("mode", "json")).lower()
        extract_path = response_cfg.get("extract_path")
        max_response_bytes = response_cfg.get("max_response_bytes") or (1024 * 1024)

        serialized_size = len(json.dumps(response_data, ensure_ascii=False, default=str).encode("utf-8"))
        if serialized_size > max_response_bytes:
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"HTTP tool '{tool_name}' response too large"
            )

        if status_code not in success_codes:
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"HTTP tool '{tool_name}' failed with status {status_code}"
            )

        value = response_data
        if extract_path:
            value = self._extract_path(response_data, str(extract_path))

        if mode == "text" and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)

        return {
            "status": "success",
            "http_status": status_code,
            "data": value,
        }

    def _extract_path(self, data, extract_path: str):
        current = data
        for segment in [p for p in extract_path.split(".") if p != ""]:
            if isinstance(current, list):
                try:
                    index = int(segment)
                except ValueError as exc:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        f"Invalid extract_path segment '{segment}' for list"
                    ) from exc
                try:
                    current = current[index]
                except IndexError as exc:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        f"extract_path index '{index}' out of range"
                    ) from exc
            elif isinstance(current, dict):
                if segment not in current:
                    raise IAToolkitException(
                        IAToolkitException.ErrorType.INVALID_PARAMETER,
                        f"extract_path key '{segment}' not found in response"
                    )
                current = current[segment]
            else:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"Cannot traverse extract_path over type '{type(current).__name__}'"
                )

        return current
