# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
import os
from typing import Tuple

from PIL import Image


def normalize_image(input_image, filename_hint: str, output_format: str = "PNG") -> Tuple[bytes, str, str, int, int]:
    """
    Converts any supported input image to normalized RGB PNG/JPEG bytes.
    Returns: (content, filename, mime_type, width, height)
    """
    output_format = (output_format or "PNG").upper()
    if output_format not in {"PNG", "JPEG"}:
        output_format = "PNG"

    image = _to_pil_image(input_image)
    if image.mode != "RGB":
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format=output_format)
    content = buffer.getvalue()

    ext = ".png" if output_format == "PNG" else ".jpg"
    mime_type = "image/png" if output_format == "PNG" else "image/jpeg"

    base_name, _ = os.path.splitext(filename_hint or "image")
    filename = f"{base_name}{ext}"

    return content, filename, mime_type, "rgb", image.width, image.height


def _to_pil_image(input_image) -> Image.Image:
    # Raw bytes
    if isinstance(input_image, (bytes, bytearray)):
        with Image.open(io.BytesIO(bytes(input_image))) as img:
            return img.copy()

    # PIL image
    if isinstance(input_image, Image.Image):
        return input_image.copy()

    # PyMuPDF Pixmap-like object
    if hasattr(input_image, "tobytes") and hasattr(input_image, "n"):
        # Convert CMYK-like pixmaps to RGB before exporting
        try:
            import fitz
            pix = input_image
            if pix.n - pix.alpha >= 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            raw = pix.tobytes("png")
            with Image.open(io.BytesIO(raw)) as img:
                return img.copy()
        except Exception as exc:
            raise ValueError(f"Could not convert pixmap to image: {exc}") from exc

    raise ValueError(f"Unsupported image input type: {type(input_image)}")
