from __future__ import annotations

import copy
from typing import Any

from iatoolkit.common.exceptions import IAToolkitException


ALLOWED_OUTPUT_KINDS = {"json", "html", "image", "file", "audio", "video"}
ALLOWED_OUTPUT_TRANSPORTS = {"inline_base64", "signed_url", "attachment"}
ALLOWED_OUTPUT_CONTRACT_KEYS = {
    "kind",
    "mime_type",
    "transport",
    "url_field",
    "base64_field",
    "filename_field",
}


def normalize_output_contract(output_contract: Any) -> dict | None:
    if output_contract in (None, "", {}):
        return None
    if not isinstance(output_contract, dict):
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            "output_contract must be a JSON object",
        )

    unknown_keys = sorted(key for key in output_contract.keys() if key not in ALLOWED_OUTPUT_CONTRACT_KEYS)
    if unknown_keys:
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"output_contract has unsupported keys: {unknown_keys}",
        )

    kind = str(output_contract.get("kind") or "").strip().lower()
    if kind not in ALLOWED_OUTPUT_KINDS:
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"output_contract.kind must be one of {sorted(ALLOWED_OUTPUT_KINDS)}",
        )

    normalized = {"kind": kind}
    mime_type = _normalize_optional_string(output_contract.get("mime_type"))
    transport = _normalize_optional_string(output_contract.get("transport"))
    url_field = _normalize_optional_string(output_contract.get("url_field"))
    base64_field = _normalize_optional_string(output_contract.get("base64_field"))
    filename_field = _normalize_optional_string(output_contract.get("filename_field"))

    if mime_type:
        normalized["mime_type"] = mime_type
    if transport:
        transport = transport.lower()
        if transport not in ALLOWED_OUTPUT_TRANSPORTS:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"output_contract.transport must be one of {sorted(ALLOWED_OUTPUT_TRANSPORTS)}",
            )
        normalized["transport"] = transport
    if url_field:
        normalized["url_field"] = url_field
    if base64_field:
        normalized["base64_field"] = base64_field
    if filename_field:
        normalized["filename_field"] = filename_field

    if kind in {"json", "html"}:
        if transport or url_field or base64_field or filename_field:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "output_contract transport fields are not allowed for json/html outputs",
            )
        return normalized

    if not transport:
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            f"output_contract.transport is required for output kind '{kind}'",
        )
    if transport == "signed_url" and not url_field:
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            "output_contract.url_field is required when transport is 'signed_url'",
        )
    if transport == "inline_base64" and not base64_field:
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            "output_contract.base64_field is required when transport is 'inline_base64'",
        )
    if transport == "attachment" and not filename_field:
        raise IAToolkitException(
            IAToolkitException.ErrorType.INVALID_PARAMETER,
            "output_contract.filename_field is required when transport is 'attachment'",
        )

    return normalized


def clone_output_contract(output_contract: Any) -> dict | None:
    if isinstance(output_contract, dict):
        return copy.deepcopy(output_contract)
    return None


def _normalize_optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
