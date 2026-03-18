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

    @inject
    def __init__(self, configuration_service: ConfigurationService, util: Utility):
        self.configuration_service = configuration_service
        self.util = util
        self._default_capabilities: dict | None = None
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

        for file_obj in files:
            stats["total_files"] += 1
            meta = self._normalize_file_meta(file_obj)
            filename = meta.get("name") or "attachment"

            if meta.get("is_image"):
                # Keep current image flow untouched (ContextBuilder -> images list).
                files_for_context.append(file_obj)
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
