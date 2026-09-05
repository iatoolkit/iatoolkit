import io
import sys
import types

import pytest
from PIL import Image

from iatoolkit.services.parsers.image_normalizer import normalize_image


def _image_bytes(mode="RGBA", color=(10, 20, 30, 128), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new(mode, (3, 2), color=color).save(buffer, format=fmt)
    return buffer.getvalue()


def test_normalize_image_converts_bytes_to_rgb_png():
    content, filename, mime_type, color_mode, width, height = normalize_image(
        _image_bytes(),
        filename_hint="scan.tiff",
    )

    assert filename == "scan.png"
    assert mime_type == "image/png"
    assert color_mode == "rgb"
    assert (width, height) == (3, 2)
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"


def test_normalize_image_supports_pil_input_and_jpeg_output():
    source = Image.new("L", (4, 5), color=128)

    content, filename, mime_type, color_mode, width, height = normalize_image(
        source,
        filename_hint="page",
        output_format="JPEG",
    )

    assert filename == "page.jpg"
    assert mime_type == "image/jpeg"
    assert color_mode == "rgb"
    assert (width, height) == (4, 5)
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_normalize_image_falls_back_to_png_for_unknown_output_format():
    content, filename, mime_type, _color_mode, _width, _height = normalize_image(
        _image_bytes(mode="RGB", color=(1, 2, 3)),
        filename_hint="photo.jpeg",
        output_format="WEBP",
    )

    assert filename == "photo.png"
    assert mime_type == "image/png"
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "PNG"


def test_normalize_image_supports_pixmap_like_objects(monkeypatch):
    class FakePixmap:
        n = 4
        alpha = 0

        def tobytes(self, fmt):
            assert fmt == "png"
            return _image_bytes(mode="RGB", color=(4, 5, 6))

    class ConvertedPixmap(FakePixmap):
        n = 3

    fake_fitz = types.SimpleNamespace(
        csRGB=object(),
        Pixmap=lambda _colorspace, _pixmap: ConvertedPixmap(),
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    content, filename, mime_type, color_mode, width, height = normalize_image(
        FakePixmap(),
        filename_hint="pix",
    )

    assert filename == "pix.png"
    assert mime_type == "image/png"
    assert color_mode == "rgb"
    assert (width, height) == (3, 2)
    with Image.open(io.BytesIO(content)) as image:
        assert image.mode == "RGB"


def test_normalize_image_wraps_pixmap_conversion_errors(monkeypatch):
    class BrokenPixmap:
        n = 4
        alpha = 0

        def tobytes(self, _fmt):
            raise RuntimeError("boom")

    fake_fitz = types.SimpleNamespace(
        csRGB=object(),
        Pixmap=lambda _colorspace, pixmap: pixmap,
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    with pytest.raises(ValueError, match="Could not convert pixmap to image: boom"):
        normalize_image(BrokenPixmap(), filename_hint="broken")


def test_normalize_image_rejects_unknown_input_type():
    with pytest.raises(ValueError, match="Unsupported image input type"):
        normalize_image(object(), filename_hint="bad")
