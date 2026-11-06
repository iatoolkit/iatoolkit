# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""MIME helpers shared by the OpenAI-style adapters.

Native attachments can come from the user or from a tool result
(`__native_attachments__`). OpenAI rejects images sent as files, so the adapters
use these helpers to send image attachments as image parts instead.
"""

import mimetypes
from typing import Any, Dict

#: Image formats OpenAI accepts as image input (Responses and Chat Completions).
INLINE_IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
})


def resolve_attachment_mime(attachment: Dict[str, Any], default: str = "application/octet-stream") -> str:
    filename = str(attachment.get("name") or attachment.get("filename") or "").strip()
    mime_type = str(
        attachment.get("mime_type")
        or attachment.get("type")
        or mimetypes.guess_type(filename)[0]
        or default
    ).strip().lower()
    return mime_type.split(";", 1)[0].strip()


def is_image_mime(mime_type: str) -> bool:
    return str(mime_type or "").strip().lower().startswith("image/")


def is_inline_image_mime(mime_type: str) -> bool:
    return str(mime_type or "").strip().lower() in INLINE_IMAGE_MIME_TYPES
