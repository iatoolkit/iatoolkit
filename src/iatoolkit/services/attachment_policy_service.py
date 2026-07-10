# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import base64
import logging
import mimetypes
import threading
import time

import requests

from injector import inject

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.util import Utility


class AttachmentPolicyService:
    MODE_EXTRACTED_ONLY = "extracted_only"
    MODE_NATIVE_ONLY = "native_only"
    MODE_NATIVE_PLUS_EXTRACTED = "native_plus_extracted"
    FALLBACK_EXTRACT = "extract"
    FALLBACK_FAIL = "fail"

    DEFAULT_MODE = MODE_EXTRACTED_ONLY
    DEFAULT_FALLBACK = FALLBACK_EXTRACT
    OPENROUTER_MODELS_CACHE_TTL_SECONDS = 300
    OPENROUTER_MODELS_TIMEOUT_SECONDS = 8

    @inject
    def __init__(self, configuration_service: ConfigurationService, util: Utility):
        self.configuration_service = configuration_service
        self.util = util
        self._default_capabilities: dict | None = None
        self._openrouter_models_cache: dict[str, dict[str, Any]] = {}
        self._openrouter_models_cache_lock = threading.Lock()
        self._default_capabilities_path = (
            Path(__file__).resolve().parent.parent / "config" / "llm_capabilities.yaml"
        )

    def normalize_mode(self, mode: str | None) -> str:
        candidate = str(mode or self.DEFAULT_MODE).strip().lower()
        allowed = {
            self.MODE_EXTRACTED_ONLY,
            self.MODE_NATIVE_ONLY,
            self.MODE_NATIVE_PLUS_EXTRACTED,
        }
        if candidate in allowed:
            return candidate
        return self.DEFAULT_MODE

    def normalize_fallback(self, fallback: str | None) -> str:
        candidate = str(fallback or self.DEFAULT_FALLBACK).strip().lower()
        allowed = {self.FALLBACK_EXTRACT, self.FALLBACK_FAIL}
        if candidate in allowed:
            return candidate
        return self.DEFAULT_FALLBACK

    def build_attachment_plan(
        self,
        company_short_name: str,
        provider: str,
        files: list | None,
        policy: dict | None = None,
        model: str | None = None,
    ) -> dict:
        mode = self.normalize_mode((policy or {}).get("attachment_mode"))
        fallback = self.normalize_fallback((policy or {}).get("attachment_fallback"))
        capabilities = self.get_effective_provider_capabilities(company_short_name, provider)

        if not files:
            return {
                "files_for_context": [],
                "native_attachments": [],
                "errors": [],
                "policy": {"attachment_mode": mode, "attachment_fallback": fallback},
                "capabilities": capabilities,
                "stats": {
                    "total_files": 0,
                    "native_sent_count": 0,
                    "extract_candidates": 0,
                    "fallback_to_extract": 0,
                    "errors": 0,
                },
            }

        files_for_context: list = []
        native_attachments: list = []
        errors: list[str] = []
        max_native_files = int(capabilities.get("max_files_per_request") or 0)

        stats = {
            "total_files": 0,
            "native_sent_count": 0,
            "extract_candidates": 0,
            "fallback_to_extract": 0,
            "errors": 0,
        }
        openrouter_native_image_error: str | None = None
        openrouter_native_image_checked = False

        for file_obj in files:
            stats["total_files"] += 1
            meta = self._normalize_file_meta(file_obj)
            filename = meta.get("name") or "attachment"

            if meta.get("is_image"):
                wants_native = self._wants_native(mode, meta, capabilities)
                wants_extract = self._wants_extract(mode, meta, capabilities)
                native_ok = False

                if wants_native:
                    if str(provider or "").strip().lower() == "openrouter":
                        if not openrouter_native_image_checked:
                            openrouter_native_image_error = self._get_openrouter_native_image_error(
                                company_short_name=company_short_name,
                                model=model,
                            )
                            openrouter_native_image_checked = True
                        if openrouter_native_image_error:
                            if openrouter_native_image_error not in errors:
                                errors.append(openrouter_native_image_error)
                            continue
                    if bool(capabilities.get("supports_native_images")):
                        files_for_context.append(dict(file_obj))
                        native_ok = True
                        stats["native_sent_count"] += 1
                    elif fallback == self.FALLBACK_EXTRACT or wants_extract:
                        stats["fallback_to_extract"] += 1
                        wants_extract = True
                    else:
                        errors.append(
                            f"Image attachment '{filename}' cannot be sent as native image for provider '{provider}'."
                        )

                if wants_extract:
                    extract_copy = dict(file_obj)
                    extract_copy["force_text_extraction"] = True
                    files_for_context.append(extract_copy)
                    stats["extract_candidates"] += 1

                if wants_native and not native_ok and not wants_extract:
                    stats["errors"] += 1
                continue

            wants_native = self._wants_native(mode, meta, capabilities)
            wants_extract = self._wants_extract(mode, meta, capabilities)

            native_ok = False
            if wants_native:
                if max_native_files > 0 and len(native_attachments) >= max_native_files:
                    if fallback == self.FALLBACK_EXTRACT or wants_extract:
                        stats["fallback_to_extract"] += 1
                        wants_extract = True
                    else:
                        errors.append(
                            f"Attachment '{filename}' exceeds provider native file count limit ({max_native_files})."
                        )
                elif self._is_native_supported(meta, capabilities):
                    native_attachments.append(
                        {
                            "name": meta["name"],
                            "mime_type": meta["mime_type"],
                            "base64": meta["payload"],
                            "size_bytes": meta.get("size_bytes"),
                        }
                    )
                    native_ok = True
                    stats["native_sent_count"] += 1
                elif fallback == self.FALLBACK_EXTRACT or wants_extract:
                    stats["fallback_to_extract"] += 1
                    wants_extract = True
                else:
                    errors.append(
                        f"Attachment '{filename}' cannot be sent as native file for provider '{provider}'."
                    )

            if wants_extract:
                files_for_context.append(file_obj)
                stats["extract_candidates"] += 1

            if wants_native and not native_ok and not wants_extract:
                stats["errors"] += 1

        stats["errors"] = len(errors)
        return {
            "files_for_context": files_for_context,
            "native_attachments": native_attachments,
            "errors": errors,
            "policy": {"attachment_mode": mode, "attachment_fallback": fallback},
            "capabilities": capabilities,
            "stats": stats,
        }

    def get_effective_provider_capabilities(self, company_short_name: str, provider: str) -> dict:
        provider_key = str(provider or "unknown").strip().lower() or "unknown"
        defaults = self._load_default_capabilities().get(provider_key) or self._load_default_capabilities().get("unknown", {})

        overrides = {}
        try:
            llm_config = self.configuration_service.get_configuration(company_short_name, "llm") or {}
            override_map = llm_config.get("capabilities_overrides") or {}
            if isinstance(override_map, dict):
                overrides = override_map.get(provider_key) or {}
        except Exception as e:
            logging.debug("Could not load capabilities overrides for '%s': %s", company_short_name, e)

        return self._merge_capabilities(defaults, overrides)

    def get_company_default_policy(self, company_short_name: str) -> dict:
        llm_config = {}
        try:
            llm_config = self.configuration_service.get_configuration(company_short_name, "llm") or {}
        except Exception as e:
            logging.debug("Could not load company llm defaults for '%s': %s", company_short_name, e)

        return {
            "attachment_mode": self.normalize_mode(llm_config.get("default_attachment_mode")),
            "attachment_fallback": self.normalize_fallback(llm_config.get("default_attachment_fallback")),
        }

    def _load_default_capabilities(self) -> dict:
        if isinstance(self._default_capabilities, dict):
            return self._default_capabilities

        try:
            loaded = self.util.load_schema_from_yaml(str(self._default_capabilities_path)) or {}
            if not isinstance(loaded, dict):
                loaded = {}
        except Exception as e:
            logging.warning("Could not load llm_capabilities.yaml: %s", e)
            loaded = {}

        if "unknown" not in loaded:
            loaded["unknown"] = {
                "supports_native_files": False,
                "supports_native_images": False,
                "supported_mime_types": [],
                "preferred_native_mime_types": [],
                "max_file_size_mb": 0,
                "max_files_per_request": 0,
            }

        self._default_capabilities = loaded
        return loaded

    def _merge_capabilities(self, defaults: dict, overrides: dict) -> dict:
        merged = dict(defaults or {})
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                merged[key] = value

        merged.setdefault("supports_native_files", False)
        merged.setdefault("supports_native_images", False)
        merged.setdefault("supported_mime_types", [])
        merged.setdefault("preferred_native_mime_types", [])
        merged.setdefault("max_file_size_mb", 0)
        merged.setdefault("max_files_per_request", 0)
        return merged

    def _get_openrouter_native_image_error(self, company_short_name: str, model: str | None) -> str | None:
        model_id = str(model or "").strip()
        if not model_id:
            return "No se pudo validar soporte de imagen nativa en OpenRouter porque no se resolvio el modelo efectivo."

        model_metadata, verified = self._lookup_openrouter_model_metadata(company_short_name, model_id)
        if not verified:
            return None
        if not isinstance(model_metadata, dict):
            return (
                f"OpenRouter no publica metadata para el modelo '{model_id}', por lo que no puedo confirmar "
                "si acepta imagenes nativas."
            )

        architecture = model_metadata.get("architecture") or {}
        raw_input_modalities = architecture.get("input_modalities") or []
        input_modalities = [
            str(modality or "").strip().lower()
            for modality in raw_input_modalities
            if str(modality or "").strip()
        ]
        if "image" in input_modalities:
            return None

        published_model_id = str(model_metadata.get("id") or model_id).strip() or model_id
        published_modalities = ", ".join(input_modalities) if input_modalities else "(vacio)"
        return (
            f"El modelo de OpenRouter '{published_model_id}' no publica 'image' en 'input_modalities' "
            f"(publica: {published_modalities}), por lo que no puede recibir imagenes nativas."
        )

    def _lookup_openrouter_model_metadata(self, company_short_name: str, model: str) -> tuple[dict | None, bool]:
        provider_config = self.configuration_service.get_llm_provider_config(company_short_name, "openrouter") or {}
        base_url = str(provider_config.get("base_url") or "https://openrouter.ai/api/v1").strip()
        models_url = f"{base_url.rstrip('/')}/models"
        catalog = self._get_openrouter_models_catalog(models_url)
        if catalog is None:
            return None, False

        model_key = str(model or "").strip().lower()
        for item in catalog:
            if not isinstance(item, dict):
                continue
            candidates = {
                str(item.get("id") or "").strip().lower(),
                str(item.get("canonical_slug") or "").strip().lower(),
            }
            candidates.update(
                {
                    candidate.split("/")[-1]
                    for candidate in list(candidates)
                    if candidate and "/" in candidate
                }
            )
            if model_key and model_key in candidates:
                return item, True

        return None, True

    def _get_openrouter_models_catalog(self, models_url: str) -> list[dict] | None:
        current_time = time.time()
        with self._openrouter_models_cache_lock:
            cached_entry = self._openrouter_models_cache.get(models_url)
            if cached_entry and (current_time - float(cached_entry.get("fetched_at") or 0)) < self.OPENROUTER_MODELS_CACHE_TTL_SECONDS:
                cached_data = cached_entry.get("data")
                if isinstance(cached_data, list):
                    return cached_data

        try:
            response = requests.get(
                models_url,
                params={"output_modalities": "all"},
                timeout=self.OPENROUTER_MODELS_TIMEOUT_SECONDS,
                headers={"User-Agent": "IAToolkit AttachmentPolicy/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            catalog = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(catalog, list):
                logging.warning("OpenRouter models API returned an unexpected payload shape for '%s'.", models_url)
                return None
        except Exception as exc:
            logging.warning("Could not fetch OpenRouter model metadata from '%s': %s", models_url, exc)
            return None

        with self._openrouter_models_cache_lock:
            self._openrouter_models_cache[models_url] = {
                "fetched_at": current_time,
                "data": catalog,
            }
        return catalog

    def _normalize_file_meta(self, file_obj: dict) -> dict:
        if not isinstance(file_obj, dict):
            return {"name": "attachment", "payload": "", "mime_type": "application/octet-stream", "is_image": False}

        filename = (
            file_obj.get("filename")
            or file_obj.get("name")
            or file_obj.get("file_id")
            or "attachment"
        )
        payload = file_obj.get("content")
        if payload is None:
            payload = file_obj.get("base64")

        if isinstance(payload, bytes):
            payload = base64.b64encode(payload).decode("ascii")
        elif payload is None:
            payload = ""
        else:
            payload = str(payload)

        mime_type = str(file_obj.get("type") or "").strip().lower()
        if not mime_type:
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        size_bytes = None
        if payload:
            try:
                size_bytes = len(self.util.normalize_base64_payload(payload))
            except Exception:
                size_bytes = len(payload.encode("utf-8", errors="ignore"))

        return {
            "name": filename,
            "payload": payload,
            "mime_type": mime_type,
            "is_image": self._is_image_mime_or_ext(mime_type, filename),
            "size_bytes": size_bytes,
        }

    @staticmethod
    def _is_image_mime_or_ext(mime_type: str, filename: str) -> bool:
        if str(mime_type).lower().startswith("image/"):
            return True
        return str(filename).lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))

    def _wants_native(self, mode: str, file_meta: dict, capabilities: dict) -> bool:
        if mode == self.MODE_NATIVE_ONLY:
            return True
        if mode == self.MODE_NATIVE_PLUS_EXTRACTED:
            return True
        return False

    def _wants_extract(self, mode: str, file_meta: dict, capabilities: dict) -> bool:
        if mode == self.MODE_EXTRACTED_ONLY:
            return True
        if mode == self.MODE_NATIVE_PLUS_EXTRACTED:
            return True
        return False

    def _is_native_supported(self, file_meta: dict, capabilities: dict) -> bool:
        if not bool(capabilities.get("supports_native_files")):
            return False

        mime_type = str(file_meta.get("mime_type") or "").lower()
        supported_mimes = capabilities.get("supported_mime_types")
        if isinstance(supported_mimes, list) and supported_mimes:
            if not self._mime_matches(mime_type, supported_mimes):
                return False

        max_size_mb = float(capabilities.get("max_file_size_mb") or 0)
        size_bytes = file_meta.get("size_bytes")
        if max_size_mb > 0 and isinstance(size_bytes, int) and size_bytes > int(max_size_mb * 1024 * 1024):
            return False

        payload = str(file_meta.get("payload") or "")
        return bool(payload.strip())

    @staticmethod
    def _mime_matches(mime_type: str, rules: List[str]) -> bool:
        mime = str(mime_type or "").lower()
        for rule in rules:
            rule_value = str(rule or "").lower().strip()
            if not rule_value:
                continue
            if rule_value in ("*", "*/*"):
                return True
            if rule_value.endswith("/*"):
                if mime.startswith(rule_value[:-1]):
                    return True
                continue
            if mime == rule_value:
                return True
        return False
