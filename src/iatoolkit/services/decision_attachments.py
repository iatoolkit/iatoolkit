# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Attachments of a decision agent (BL-008, Etapa 2): images and PDFs.

Decision models take images only as PNG or JPEG `assets`, and each one limits
what it accepts: Jev refuses anything over ~1568 px on its longest side, and
every model tested answered a bare 500 to a 4 MB image. A PDF is not an asset
at all. So nothing goes out as it came in:

- every image, and every PDF page sent as an image, is normalized to a JPEG of
  at most 1568 px, which fits every model, keeps the request small, lowers the
  cost (image tokens grow with resolution) and accepts any format Pillow reads;
- a PDF's text, when the agent asks for it, joins the case as text, through
  the same extractor the chat agents use.

What reaches the model is decided by the agent's attachment mode, the same
setting chat agents have:

| mode                    | image         | PDF                         |
|-------------------------|---------------|-----------------------------|
| `extracted_only`        | refused       | its text joins the case     |
| `native_only`           | sent as image | its pages are sent as images|
| `native_plus_extracted` | sent as image | text and pages              |
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any, Callable

from iatoolkit.common.exceptions import IAToolkitException

MODE_EXTRACTED = "extracted_only"
MODE_NATIVE = "native_only"
MODE_BOTH = "native_plus_extracted"
MODES = (MODE_EXTRACTED, MODE_NATIVE, MODE_BOTH)

#: Longest side of every image sent. Jev's limit, measured (1568 passes, 2048
#: fails); every other model tested accepts it.
MAX_IMAGE_SIDE = 1568
JPEG_QUALITY = 85
#: Bytes of one image after normalization. 2.7 MB passed and 4 MB failed with a
#: 500; a 1568 px JPEG is far below this, so it only guards odd inputs.
MAX_IMAGE_BYTES = 2_500_000
DEFAULT_MAX_IMAGES = 5

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif")


@dataclass(frozen=True)
class DecisionImage:
    """One image as sent: a normalized JPEG, named after where it came from."""
    name: str
    data: bytes
    source: str
    page: int | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class PreparedAttachments:
    images: list[DecisionImage] = field(default_factory=list)
    #: Extracted text, ready to follow the rendered case.
    text: str = ""
    #: What was received and what was made of it, for the record (never the bytes).
    manifest: list[dict[str, Any]] = field(default_factory=list)


def _refuse(message: str) -> IAToolkitException:
    return IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, message)


def normalize_image(data: bytes, name: str = "image") -> bytes:
    """Any image Pillow reads, as a JPEG of at most MAX_IMAGE_SIDE px."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise _refuse(f"The attachment '{name}' is not an image this platform can read ({exc}).") from exc

    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        # JPEG has no transparency: flatten on white, as the page it came from.
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))

    quality = JPEG_QUALITY
    while True:
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= MAX_IMAGE_BYTES or quality <= 40:
            break
        quality -= 15
    if len(encoded) > MAX_IMAGE_BYTES:
        raise _refuse(f"The image '{name}' is still over {MAX_IMAGE_BYTES // 1_000_000} MB after resizing.")
    return encoded


def render_pdf_pages(data: bytes, name: str) -> list[bytes]:
    """Every page of a PDF as a normalized JPEG."""
    import fitz

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise _refuse(f"The PDF '{name}' could not be opened ({exc}).") from exc
    pages = []
    with document:
        for page in document:
            longest = max(page.rect.width, page.rect.height) or 1
            zoom = min(MAX_IMAGE_SIDE / longest, 4.0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            pages.append(normalize_image(pixmap.tobytes("png"), name))
    return pages


def pdf_page_count(data: bytes) -> int:
    import fitz

    with fitz.open(stream=data, filetype="pdf") as document:
        return document.page_count


def _is_image(filename: str) -> bool:
    return filename.lower().endswith(_IMAGE_EXTENSIONS)


def _is_pdf(filename: str) -> bool:
    return filename.lower().endswith(".pdf")


def prepare_decision_attachments(
    files: list[dict] | None,
    *,
    mode: str | None,
    max_images: int = DEFAULT_MAX_IMAGES,
    decode: Callable[[Any], bytes],
    extract_text: Callable[[str, bytes], str],
) -> PreparedAttachments:
    """What a decision agent sends for its attachments, or an error that says why not.

    `decode` turns a file's payload (base64, possibly a data URL) into bytes;
    `extract_text` is the extractor chat agents use for documents.
    """
    prepared = PreparedAttachments()
    if not files:
        return prepared
    mode = str(mode or MODE_EXTRACTED).strip().lower()
    if mode not in MODES:
        mode = MODE_EXTRACTED
    native = mode in (MODE_NATIVE, MODE_BOTH)
    extracted = mode in (MODE_EXTRACTED, MODE_BOTH)
    text_parts: list[str] = []

    for document in files:
        filename = str(document.get("file_id") or document.get("filename") or document.get("name") or "").strip()
        payload = document.get("base64") or document.get("content")
        if not filename or not payload:
            raise _refuse("An attachment has no name or no content.")
        data = decode(payload)
        if isinstance(data, str):
            data = data.encode("utf-8")
        entry: dict[str, Any] = {
            "name": filename,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

        if _is_image(filename):
            if not native:
                raise _refuse(
                    f"'{filename}' is an image, and this agent's attachment mode only sends extracted text. "
                    "Change it to native to send images."
                )
            _check_room(prepared, 1, max_images, filename)
            prepared.images.append(DecisionImage(
                name=f"img_{len(prepared.images) + 1}",
                data=normalize_image(data, filename),
                source=filename,
            ))
            entry["sent_as"] = "image"
            entry["images"] = 1

        elif _is_pdf(filename):
            entry["pages"] = pdf_page_count(data)
            sent_as = []
            if extracted:
                text = (extract_text(filename, data) or "").strip()
                if text:
                    text_parts.append(f"Documento adjunto '{filename}':\n{text}")
                    sent_as.append("text")
                elif not native:
                    raise _refuse(
                        f"The PDF '{filename}' has no text to extract (it looks scanned). "
                        "Change the agent's attachment mode to native to send its pages as images."
                    )
            if native:
                _check_room(prepared, entry["pages"], max_images, filename)
                for page_number, page in enumerate(render_pdf_pages(data, filename), start=1):
                    prepared.images.append(DecisionImage(
                        name=f"img_{len(prepared.images) + 1}",
                        data=page,
                        source=filename,
                        page=page_number,
                    ))
                sent_as.append("pages")
                entry["images"] = entry["pages"]
            entry["sent_as"] = "+".join(sent_as)

        else:
            if not extracted:
                raise _refuse(
                    f"'{filename}' is neither an image nor a PDF; in native mode a decision agent sends only those."
                )
            text = (extract_text(filename, data) or "").strip()
            if not text:
                raise _refuse(f"No text could be extracted from '{filename}'.")
            text_parts.append(f"Documento adjunto '{filename}':\n{text}")
            entry["sent_as"] = "text"

        prepared.manifest.append(entry)

    prepared.text = "\n\n".join(text_parts)
    return prepared


def _check_room(prepared: PreparedAttachments, needed: int, max_images: int, filename: str) -> None:
    if len(prepared.images) + needed > max_images:
        raise _refuse(
            f"'{filename}' would take the images sent to {len(prepared.images) + needed}; "
            f"a decision agent sends at most {max_images} (llm.decisions.max_images)."
        )
