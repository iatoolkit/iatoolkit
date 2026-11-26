# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
What a file has to be before IAToolkit stores, parses or forwards it (BL-034, R12).

A name and a declared type are whatever the sender says. This module looks at the
bytes:

- An executable (Windows PE, ELF, Mach-O) is refused whatever it is called, and a
  `#!` script unless it is named as a text file.
- A file whose extension names a known binary format (PDF, Office, images) must
  start like that format: a `.pdf` that is really an HTML page or a ZIP is refused.
- A text format (`.txt`, `.csv`, `.md`, `.json`…) must be text: no NUL bytes.
- No file may be larger than IAT_MAX_UPLOAD_MB (50 by default).

An extension it does not know only gets the executable check. Every refusal is
logged as `event=upload_rejected` with the reason and the extension, never the
content.

The whole request body is capped separately by Flask's MAX_CONTENT_LENGTH
(IAT_MAX_REQUEST_MB, 100 by default; see core.py), which covers every endpoint,
including those that carry files as base64 inside JSON.
"""

from __future__ import annotations

import logging
import os

from iatoolkit.common.exceptions import IAToolkitException

MAX_UPLOAD_ENV = "IAT_MAX_UPLOAD_MB"
DEFAULT_MAX_UPLOAD_MB = 50
MAX_REQUEST_ENV = "IAT_MAX_REQUEST_MB"
DEFAULT_MAX_REQUEST_MB = 100

# How many leading bytes the checks need.
HEAD_BYTES = 8192

_EXECUTABLE_SIGNATURES = (
    (b"\x7fELF", "elf_executable"),
    (b"\xfe\xed\xfa\xce", "macho_executable"),
    (b"\xfe\xed\xfa\xcf", "macho_executable"),
    (b"\xce\xfa\xed\xfe", "macho_executable"),
    (b"\xcf\xfa\xed\xfe", "macho_executable"),
    (b"\xca\xfe\xba\xbe", "macho_executable"),
)


def _is_windows_executable(data: bytes) -> bool:
    """MZ followed, at the offset it names, by the PE header: a real .exe/.dll, not text starting "MZ"."""
    if not data.startswith(b"MZ") or len(data) < 0x40:
        return False
    offset = int.from_bytes(data[0x3C:0x40], "little")
    return data[offset:offset + 4] == b"PE\x00\x00"

_PDF = (b"%PDF-",)
_ZIP = (b"PK\x03\x04", b"PK\x05\x06")          # docx, xlsx, pptx, odt… (and an empty zip)
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)  # doc, xls, ppt, msg
_PNG = (b"\x89PNG\r\n\x1a\n",)
_JPEG = (b"\xff\xd8\xff",)
_GIF = (b"GIF87a", b"GIF89a")
_TIFF = (b"II*\x00", b"MM\x00*")
_BMP = (b"BM",)

_WEBP_MARK = b"WEBP"  # RIFF....WEBP, checked apart: the mark is at offset 8
_IMAGE = _PNG + _JPEG + _GIF + _TIFF + _BMP

# An image renamed to another image extension (a JPEG saved as .png) is common and
# harmless, so any image extension accepts any image format.
_BINARY_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": _PDF,
    "docx": _ZIP, "xlsx": _ZIP, "pptx": _ZIP, "odt": _ZIP, "ods": _ZIP, "odp": _ZIP, "zip": _ZIP,
    "doc": _OLE, "ppt": _OLE, "msg": _OLE,
    "xls": _OLE + _ZIP,  # an .xlsx saved as .xls: the Excel reader goes by content
    **{extension: _IMAGE for extension in ("png", "jpg", "jpeg", "gif", "tif", "tiff", "bmp", "webp")},
}


def _is_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == _WEBP_MARK


_TEXT_EXTENSIONS = frozenset({
    "txt", "csv", "tsv", "md", "markdown", "json", "jsonl", "xml", "yaml", "yml",
    "html", "htm", "log", "sql", "ini", "rtf",
})


def _megabytes_from_env(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        logging.warning("%s=%r is not a number; using %s.", name, raw, default)
        value = default
    return int((value if value > 0 else default) * 1024 * 1024)


def max_upload_bytes() -> int:
    return _megabytes_from_env(MAX_UPLOAD_ENV, DEFAULT_MAX_UPLOAD_MB)


def max_request_bytes() -> int:
    return _megabytes_from_env(MAX_REQUEST_ENV, DEFAULT_MAX_REQUEST_MB)


def extension_of(filename: str | None) -> str:
    name = str(filename or "").strip().lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def upload_problem(filename: str | None, head: bytes, size: int | None = None) -> str | None:
    """Why the file is refused, or None. `head` = its first bytes (HEAD_BYTES is enough)."""
    data = bytes(head or b"")
    if size is None:
        size = len(data)
    if size > max_upload_bytes():
        return "too_large"

    extension = extension_of(filename)
    if _is_windows_executable(data):
        return "windows_executable"
    for signature, kind in _EXECUTABLE_SIGNATURES:
        if data.startswith(signature):
            return kind
    # A script is only text to IAToolkit, which never runs what it receives; it is
    # refused when it does not even claim to be a text file.
    if data.startswith(b"#!") and extension not in _TEXT_EXTENSIONS:
        return "script"

    if not data:
        return None
    expected = _BINARY_SIGNATURES.get(extension)
    if expected is not None and not any(data.startswith(signature) for signature in expected):
        if not (expected is _BINARY_SIGNATURES["png"] and _is_webp(data)):
            return "content_does_not_match_extension"
    if extension in _TEXT_EXTENSIONS and b"\x00" in data[:HEAD_BYTES]:
        # UTF-16 text starts with a byte-order mark and is full of NULs; it is text.
        if not data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "binary_content_in_text_file"
    return None


_MESSAGES = {
    "too_large": "The file is larger than the allowed size.",
    "content_does_not_match_extension": "The file content does not match its extension.",
    "binary_content_in_text_file": "The file is not a text file, as its extension says.",
}


def check_upload(filename: str | None, content: bytes | None, size: int | None = None) -> None:
    """Raise if the file must not be accepted. `content` may be the whole file or its head."""
    problem = upload_problem(filename, (content or b"")[:HEAD_BYTES],
                             size if size is not None else len(content or b""))
    if problem is None:
        return
    logging.warning("event=upload_rejected reason=%s extension=%s size=%s",
                    problem, extension_of(filename) or "-", size if size is not None else len(content or b""))
    message = _MESSAGES.get(problem, "Executable files and scripts are not accepted.")
    raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR, message)
