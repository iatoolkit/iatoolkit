from unittest.mock import MagicMock, patch

from iatoolkit.services.parsers.pdf_ocr_detection import PdfOcrDecision, analyze_pdf_ocr_need
from iatoolkit.services.parsers.providers.basic_provider import BasicParsingProvider
from iatoolkit.services.parsers.providers.docling_provider import DoclingParsingProvider


class FakePage:
    def __init__(self, text: str, images: int):
        self._text = text
        self._images = images

    def get_text(self):
        return self._text

    def get_images(self, full=True):
        return [object() for _ in range(self._images)]


class FakeDoc:
    def __init__(self, pages):
        self._pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __len__(self):
        return len(self._pages)

    def __iter__(self):
        return iter(self._pages)


def test_analyze_pdf_ocr_need_detects_sparse_overlay_text_on_image_first_pdf():
    sparse_pages = [FakePage("Codigo de Verificacion: 20220125141321CZV", 1) for _ in range(30)]
    signature_text = (
        "JUAN RICARDO ENRIQUE SAN MARTIN URREJOLA Santiago 25-01-2022 "
        "ES TESTIMONIO FIEL DEL ORIGINAL Documento emitido con Firma Electronica Avanzada"
    )
    pages = sparse_pages + [FakePage(signature_text, 2), FakePage(signature_text, 2)]

    with patch("iatoolkit.services.parsers.pdf_ocr_detection.fitz.open", return_value=FakeDoc(pages)):
        decision = analyze_pdf_ocr_need(b"%PDF-1.7")

    assert decision.needs_ocr is True
    assert decision.reason == "majority_pages_image_first_with_sparse_text"
    assert decision.page_count == 32
    assert decision.meaningful_text_page_count == 2
    assert decision.sparse_text_image_page_count == 30


def test_analyze_pdf_ocr_need_skips_ocr_when_pages_have_meaningful_text():
    meaningful_text = (
        "Constitucion de sociedad por acciones comparecen los socios y acuerdan "
        "las siguientes clausulas con domicilio en Santiago de Chile."
    )
    pages = [FakePage(meaningful_text, 1) for _ in range(4)]

    with patch("iatoolkit.services.parsers.pdf_ocr_detection.fitz.open", return_value=FakeDoc(pages)):
        decision = analyze_pdf_ocr_need(b"%PDF-1.7")

    assert decision.needs_ocr is False
    assert decision.reason == "meaningful_text_detected"
    assert decision.meaningful_text_page_count == 4


def test_analyze_pdf_ocr_need_detects_mixed_pdf_as_ocr_candidate():
    meaningful_text = (
        "Constitucion de sociedad por acciones comparecen los socios y acuerdan "
        "las siguientes clausulas con domicilio en Santiago de Chile."
    )
    pages = [
        FakePage(meaningful_text, 1),
        FakePage("", 1),
        FakePage("INUTILIZADO CONFORME ART. 404 INC. C.O.T.", 1),
        FakePage(meaningful_text, 1),
    ]

    with patch("iatoolkit.services.parsers.pdf_ocr_detection.fitz.open", return_value=FakeDoc(pages)):
        decision = analyze_pdf_ocr_need(b"%PDF-1.7")

    assert decision.needs_ocr is False
    assert decision.reason == "substantial_embedded_text_detected"
    assert decision.meaningful_text_page_count == 2
    assert decision.sparse_text_image_page_count == 2


def test_analyze_pdf_ocr_need_keeps_scientific_paper_with_figures_as_digital():
    meaningful_text = (
        "This scientific paper presents a reproducible methodology, experimental setup, "
        "quantitative evaluation, related work, and discussion of the observed results."
    )
    pages = [FakePage(meaningful_text, 2) for _ in range(8)] + [FakePage("", 3), FakePage("", 2)]

    with patch("iatoolkit.services.parsers.pdf_ocr_detection.fitz.open", return_value=FakeDoc(pages)):
        decision = analyze_pdf_ocr_need(b"%PDF-1.7")

    assert decision.needs_ocr is False
    assert decision.reason == "substantial_embedded_text_detected"
    assert decision.meaningful_text_page_count == 8
    assert decision.sparse_text_image_page_count == 2


def test_analyze_pdf_ocr_need_detects_low_text_mixed_pdf_as_ocr_candidate():
    meaningful_text = (
        "Constitucion de sociedad por acciones comparecen los socios y acuerdan "
        "las siguientes clausulas con domicilio en Santiago de Chile."
    )
    pages = [
        FakePage(meaningful_text, 1),
        FakePage("", 1),
    ]

    with patch("iatoolkit.services.parsers.pdf_ocr_detection.fitz.open", return_value=FakeDoc(pages)):
        decision = analyze_pdf_ocr_need(b"%PDF-1.7")

    assert decision.needs_ocr is True
    assert decision.reason == "mixed_meaningful_and_sparse_image_pages"
    assert decision.meaningful_text_page_count == 1
    assert decision.sparse_text_image_page_count == 1


def test_basic_provider_is_scanned_pdf_uses_shared_pdf_ocr_decision():
    provider = BasicParsingProvider(excel_service=MagicMock(), i18n_service=MagicMock())
    decision = PdfOcrDecision(
        needs_ocr=True,
        page_count=3,
        image_page_count=3,
        meaningful_text_page_count=0,
        sparse_text_image_page_count=3,
        total_text_char_count=20,
        reason="no_meaningful_text_and_has_images",
    )

    with patch(
        "iatoolkit.services.parsers.providers.basic_provider.analyze_pdf_ocr_need",
        return_value=decision,
    ):
        assert provider.is_scanned_pdf(b"%PDF-1.7") is True


def test_docling_provider_pdf_needs_ocr_uses_shared_pdf_ocr_decision():
    provider = DoclingParsingProvider(i18n_service=MagicMock(), config_service=MagicMock())
    decision = PdfOcrDecision(
        needs_ocr=False,
        page_count=3,
        image_page_count=1,
        meaningful_text_page_count=3,
        sparse_text_image_page_count=0,
        total_text_char_count=900,
        reason="meaningful_text_detected",
    )

    with patch(
        "iatoolkit.services.parsers.providers.docling_provider.analyze_pdf_ocr_need",
        return_value=decision,
    ):
        assert provider._pdf_needs_ocr(b"%PDF-1.7") is False
