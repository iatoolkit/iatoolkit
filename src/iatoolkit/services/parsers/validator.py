# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
import json
from PIL import Image

from iatoolkit.services.parsers.contracts import ParseResult


_ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg"}


def _ensure_json_serializable(value, field_name: str):
    try:
        json.dumps(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be JSON serializable: {exc}") from exc


def validate_parse_result(result: ParseResult):
    if not result.provider:
        raise ValueError("ParseResult.provider is required")

    if not isinstance(result.texts, list) or not isinstance(result.tables, list) or not isinstance(result.images, list):
        raise ValueError("ParseResult lists are malformed")

    if len(result.texts) == 0 and len(result.tables) == 0 and len(result.images) == 0:
        raise ValueError("ParseResult must contain at least one text, table or image")

    for index, text in enumerate(result.texts):
        if not text.text or not text.text.strip():
            raise ValueError(f"ParsedText at index {index} is empty")
        _ensure_json_serializable(text.meta, f"texts[{index}].meta")

    for index, table in enumerate(result.tables):
        if not table.text or not table.text.strip():
            raise ValueError(f"ParsedTable at index {index} is empty")
        if table.table_json is not None:
            _ensure_json_serializable(table.table_json, f"tables[{index}].table_json")
        _ensure_json_serializable(table.meta, f"tables[{index}].meta")

    for index, image in enumerate(result.images):
        if image.mime_type not in _ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError(f"images[{index}] has unsupported mime_type: {image.mime_type}")

        if image.color_mode.lower() != "rgb":
            raise ValueError(f"images[{index}] must be RGB")

        if image.width <= 0 or image.height <= 0:
            raise ValueError(f"images[{index}] has invalid dimensions")

        try:
            with Image.open(io.BytesIO(image.content)) as img:
                img.verify()
        except Exception as exc:
            raise ValueError(f"images[{index}] contains invalid image bytes: {exc}") from exc

        _ensure_json_serializable(image.meta, f"images[{index}].meta")

    _ensure_json_serializable(result.metrics, "ParseResult.metrics")
