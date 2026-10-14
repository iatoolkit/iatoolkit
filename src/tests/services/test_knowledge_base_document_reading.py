from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.models import DocumentStatus
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService


def make_service():
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.parsing_service = MagicMock()
    service.document_repo = MagicMock()
    service.storage_service = MagicMock()
    return service


def doc(doc_id, filename, meta=None, collection="comercial", day=1):
    return SimpleNamespace(id=doc_id, filename=filename, meta=meta or {},
                           collection_type=SimpleNamespace(name=collection),
                           created_at=datetime(2026, 10, day), status=DocumentStatus.ACTIVE)


def test_read_returns_a_part_and_where_to_continue():
    service = make_service()
    service.get_document_descriptor = MagicMock(return_value={
        "document_id": 4, "filename": "contrato.pdf", "collection_name": "legal", "content_available": True,
        "mime_type": "application/pdf", "metadata": {"card": {"title": "Contrato Acme"}}})
    service.get_document_content = MagicMock(return_value=(b"bytes", "contrato.pdf"))
    service.parsing_service.extract_text_for_context.return_value = "x" * 25000

    first = service.read_document_text("acme", 4)
    second = service.read_document_text("acme", 4, offset=first["next_offset"])

    assert (first["offset"], first["end_offset"], first["has_more"]) == (0, 20000, True)
    assert first["card"] == {"title": "Contrato Acme"}
    assert (second["end_offset"], second["has_more"], second["next_offset"]) == (25000, False, None)
    assert service.read_document_text("acme", 4, limit=999999)["end_offset"] == 25000


def test_read_without_text_or_content_is_an_error():
    service = make_service()
    service.get_document_descriptor = MagicMock(return_value={"content_available": False})
    with pytest.raises(IAToolkitException):
        service.read_document_text("acme", 4)

    service.get_document_descriptor = MagicMock(return_value={"content_available": True, "filename": "scan.pdf"})
    service.get_document_content = MagicMock(return_value=(b"bytes", "scan.pdf"))
    service.parsing_service.extract_text_for_context.return_value = "  "
    with pytest.raises(IAToolkitException, match="OCR"):
        service.read_document_text("acme", 4)


def test_list_filters_by_card_and_hides_inactive_documents():
    service = make_service()
    service.list_documents = MagicMock(return_value=[
        doc(1, "precios-2026.xlsx", {"card": {"title": "Lista de precios 2026", "type": "lista de precios",
                                              "valid_from": "2026-01-01", "valid_until": "2026-12-31"}}, day=3),
        doc(2, "precios-2025.xlsx", {"card": {"type": "lista de precios", "valid_until": "2025-12-31"},
                                     "lifecycle": "replaced"}, day=2),
        doc(3, "contrato.pdf", {"card": {"type": "contrato", "keywords": ["Acme"]}}, day=1),
    ])

    prices = service.list_documents_with_cards("acme", "comercial", document_type="Lista de precios")
    valid = service.list_documents_with_cards("acme", "comercial", valid_on="2026-10-14")
    with_old = service.list_documents_with_cards("acme", "comercial", include_inactive=True, document_type="lista de precios")
    by_keyword = service.list_documents_with_cards("acme", "comercial", text="acme")

    assert [d["document_id"] for d in prices["documents"]] == [1]
    assert [d["document_id"] for d in valid["documents"]] == [1, 3]
    assert [d["document_id"] for d in with_old["documents"]] == [1, 2]
    assert [d["document_id"] for d in by_keyword["documents"]] == [3]
    assert service.list_documents.call_args.kwargs["status"] == DocumentStatus.ACTIVE


def test_list_pages():
    service = make_service()
    service.list_documents = MagicMock(return_value=[doc(i, f"d{i}.pdf") for i in range(5)])

    page = service.list_documents_with_cards("acme", None, limit=2, offset=2)

    assert [d["document_id"] for d in page["documents"]] == [2, 3]
    assert (page["total"], page["next_offset"]) == (5, 4)
