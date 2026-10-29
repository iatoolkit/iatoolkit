import base64
import io

import fitz
import pytest
from PIL import Image

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.decision_attachments import (
    MAX_IMAGE_SIDE,
    normalize_image,
    prepare_decision_attachments,
)


def _png(width=800, height=500, mode="RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _webp() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "WEBP")
    return buffer.getvalue()


def _pdf(pages: int = 1, text: str | None = "Total a pagar $ 1.250.000") -> bytes:
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page()
        if text:
            page.insert_text((72, 90), text, fontsize=14)
    return document.tobytes()


def _file(name: str, data: bytes) -> dict:
    return {"filename": name, "base64": base64.b64encode(data).decode()}


def _prepare(files, mode, max_images=5, extract=None):
    return prepare_decision_attachments(
        files,
        mode=mode,
        max_images=max_images,
        decode=lambda payload: base64.b64decode(payload),
        extract_text=extract or (lambda name, data: fitz.open(stream=data, filetype="pdf")[0].get_text()
                                 if name.endswith(".pdf") else data.decode()),
    )


def _size(jpeg: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(jpeg)).size


class TestNormalizeImage:
    def test_a_large_image_becomes_a_jpeg_within_the_limit(self):
        jpeg = normalize_image(_png(4000, 3000))
        assert jpeg[:3] == b"\xff\xd8\xff"
        assert max(_size(jpeg)) == MAX_IMAGE_SIDE

    def test_a_small_image_keeps_its_size(self):
        assert _size(normalize_image(_png(800, 500))) == (800, 500)

    def test_webp_and_transparency_are_accepted(self):
        assert normalize_image(_webp())[:3] == b"\xff\xd8\xff"
        assert normalize_image(_png(100, 100, mode="RGBA"))[:3] == b"\xff\xd8\xff"

    def test_bytes_that_are_not_an_image_are_refused(self):
        with pytest.raises(IAToolkitException) as exc:
            normalize_image(b"not an image", "x.png")
        assert "x.png" in str(exc.value)


class TestPrepareDecisionAttachments:
    def test_nothing_attached_sends_nothing(self):
        prepared = _prepare([], "native_only")
        assert prepared.images == [] and prepared.text == "" and prepared.manifest == []

    def test_extracted_mode_puts_pdf_text_in_the_case(self):
        prepared = _prepare([_file("factura.pdf", _pdf())], "extracted_only")

        assert prepared.images == []
        assert prepared.text.startswith("Documento adjunto 'factura.pdf':")
        assert "1.250.000" in prepared.text
        assert prepared.manifest[0]["sent_as"] == "text"
        assert prepared.manifest[0]["pages"] == 1
        assert len(prepared.manifest[0]["sha256"]) == 64

    def test_extracted_mode_refuses_images_and_scanned_pdfs(self):
        with pytest.raises(IAToolkitException) as exc:
            _prepare([_file("foto.png", _png())], "extracted_only")
        assert "native" in str(exc.value)
        with pytest.raises(IAToolkitException) as exc:
            _prepare([_file("escaneado.pdf", _pdf(text=None))], "extracted_only")
        assert "scanned" in str(exc.value)

    def test_native_mode_sends_images_and_pdf_pages_as_images(self):
        prepared = _prepare([_file("foto.png", _png()), _file("doc.pdf", _pdf(pages=2))], "native_only")

        assert [(i.name, i.source, i.page) for i in prepared.images] == [
            ("img_1", "foto.png", None), ("img_2", "doc.pdf", 1), ("img_3", "doc.pdf", 2),
        ]
        assert all(max(_size(i.data)) <= MAX_IMAGE_SIDE for i in prepared.images)
        assert prepared.text == ""
        assert [m["sent_as"] for m in prepared.manifest] == ["image", "pages"]

    def test_native_mode_refuses_other_documents(self):
        with pytest.raises(IAToolkitException) as exc:
            _prepare([_file("notas.txt", b"hola")], "native_only")
        assert "neither an image nor a PDF" in str(exc.value)

    def test_both_sends_text_and_pages(self):
        prepared = _prepare([_file("factura.pdf", _pdf())], "native_plus_extracted")
        assert len(prepared.images) == 1 and "1.250.000" in prepared.text
        assert prepared.manifest[0]["sent_as"] == "text+pages"

    def test_too_many_images_is_refused_rather_than_cut(self):
        with pytest.raises(IAToolkitException) as exc:
            _prepare([_file("largo.pdf", _pdf(pages=3))], "native_only", max_images=2)
        assert "at most 2" in str(exc.value)

    def test_other_documents_go_as_text(self):
        prepared = _prepare([_file("notas.txt", b"cliente pide prorroga")], "extracted_only")
        assert prepared.text == "Documento adjunto 'notas.txt':\ncliente pide prorroga"
