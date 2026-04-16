from __future__ import annotations

import io
import logging
import math
import re
from dataclasses import dataclass

import fitz


_MEANINGFUL_TEXT_MIN_CHARS = 80
_MEANINGFUL_TEXT_MIN_WORDS = 12
_SCANNED_PAGE_RATIO_THRESHOLD = 0.6
_DIGITAL_PAGE_RATIO_THRESHOLD = 0.4
_SUBSTANTIAL_TEXT_PAGE_RATIO_THRESHOLD = 0.5
_SUBSTANTIAL_TEXT_MIN_TOTAL_CHARS = 400
_SUBSTANTIAL_TEXT_AVG_CHARS_PER_PAGE = 120


@dataclass(frozen=True)
class PdfOcrDecision:
    needs_ocr: bool
    page_count: int
    image_page_count: int
    meaningful_text_page_count: int
    sparse_text_image_page_count: int
    total_text_char_count: int
    reason: str


def analyze_pdf_ocr_need(content: bytes) -> PdfOcrDecision:
    if not content:
        return PdfOcrDecision(
            needs_ocr=False,
            page_count=0,
            image_page_count=0,
            meaningful_text_page_count=0,
            sparse_text_image_page_count=0,
            total_text_char_count=0,
            reason="empty_content",
        )

    try:
        with fitz.open(stream=io.BytesIO(content), filetype="pdf") as doc:
            page_count = len(doc)
            if page_count == 0:
                return PdfOcrDecision(
                    needs_ocr=False,
                    page_count=0,
                    image_page_count=0,
                    meaningful_text_page_count=0,
                    sparse_text_image_page_count=0,
                    total_text_char_count=0,
                    reason="empty_document",
                )

            image_page_count = 0
            meaningful_text_page_count = 0
            sparse_text_image_page_count = 0
            total_text_char_count = 0

            for page in doc:
                normalized_text = _normalize_text(page.get_text() or "")
                text_char_count = len(normalized_text)
                total_text_char_count += text_char_count

                has_images = bool(page.get_images(full=True))
                if has_images:
                    image_page_count += 1

                if _has_meaningful_text(normalized_text):
                    meaningful_text_page_count += 1
                elif has_images:
                    sparse_text_image_page_count += 1

            scanned_page_threshold = max(1, math.ceil(page_count * _SCANNED_PAGE_RATIO_THRESHOLD))
            digital_page_threshold = math.floor(page_count * _DIGITAL_PAGE_RATIO_THRESHOLD)

            if meaningful_text_page_count == 0 and image_page_count > 0:
                return PdfOcrDecision(
                    needs_ocr=True,
                    page_count=page_count,
                    image_page_count=image_page_count,
                    meaningful_text_page_count=meaningful_text_page_count,
                    sparse_text_image_page_count=sparse_text_image_page_count,
                    total_text_char_count=total_text_char_count,
                    reason="no_meaningful_text_and_has_images",
                )

            if (
                sparse_text_image_page_count >= scanned_page_threshold
                and meaningful_text_page_count <= digital_page_threshold
            ):
                return PdfOcrDecision(
                    needs_ocr=True,
                    page_count=page_count,
                    image_page_count=image_page_count,
                    meaningful_text_page_count=meaningful_text_page_count,
                    sparse_text_image_page_count=sparse_text_image_page_count,
                    total_text_char_count=total_text_char_count,
                    reason="majority_pages_image_first_with_sparse_text",
                )

            if (
                sparse_text_image_page_count > 0
                and _has_substantial_embedded_text(
                    page_count=page_count,
                    meaningful_text_page_count=meaningful_text_page_count,
                    total_text_char_count=total_text_char_count,
                )
            ):
                return PdfOcrDecision(
                    needs_ocr=False,
                    page_count=page_count,
                    image_page_count=image_page_count,
                    meaningful_text_page_count=meaningful_text_page_count,
                    sparse_text_image_page_count=sparse_text_image_page_count,
                    total_text_char_count=total_text_char_count,
                    reason="substantial_embedded_text_detected",
                )

            if sparse_text_image_page_count > 0 and meaningful_text_page_count > 0:
                return PdfOcrDecision(
                    needs_ocr=True,
                    page_count=page_count,
                    image_page_count=image_page_count,
                    meaningful_text_page_count=meaningful_text_page_count,
                    sparse_text_image_page_count=sparse_text_image_page_count,
                    total_text_char_count=total_text_char_count,
                    reason="mixed_meaningful_and_sparse_image_pages",
                )

            return PdfOcrDecision(
                needs_ocr=False,
                page_count=page_count,
                image_page_count=image_page_count,
                meaningful_text_page_count=meaningful_text_page_count,
                sparse_text_image_page_count=sparse_text_image_page_count,
                total_text_char_count=total_text_char_count,
                reason="meaningful_text_detected",
            )
    except Exception as exc:
        logging.warning("Could not determine whether PDF needs OCR: %s", exc)
        return PdfOcrDecision(
            needs_ocr=False,
            page_count=0,
            image_page_count=0,
            meaningful_text_page_count=0,
            sparse_text_image_page_count=0,
            total_text_char_count=0,
            reason="inspection_error",
        )


def pdf_needs_ocr(content: bytes) -> bool:
    return analyze_pdf_ocr_need(content).needs_ocr


def _has_meaningful_text(text: str) -> bool:
    if not text:
        return False

    if len(text) >= _MEANINGFUL_TEXT_MIN_CHARS:
        return True

    word_count = len(re.findall(r"\w+", text, flags=re.UNICODE))
    return word_count >= _MEANINGFUL_TEXT_MIN_WORDS


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _has_substantial_embedded_text(
    *,
    page_count: int,
    meaningful_text_page_count: int,
    total_text_char_count: int,
) -> bool:
    if page_count <= 0 or meaningful_text_page_count <= 0 or total_text_char_count <= 0:
        return False

    substantial_page_threshold = max(
        2,
        math.ceil(page_count * _SUBSTANTIAL_TEXT_PAGE_RATIO_THRESHOLD),
    )
    if meaningful_text_page_count >= substantial_page_threshold:
        return True

    substantial_char_threshold = max(
        _SUBSTANTIAL_TEXT_MIN_TOTAL_CHARS,
        page_count * _SUBSTANTIAL_TEXT_AVG_CHARS_PER_PAGE,
    )
    return total_text_char_count >= substantial_char_threshold
