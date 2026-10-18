"""Memoria's audiences (BL-010, Fase 3), end to end: what RRHH teaches stays with RRHH."""

import pytest

from iatoolkit.common.access import Access
from iatoolkit.repositories.models import MemoryCapture
from tests.services.memory_test_support import MemoryStack

RRHH = "group:rrhh"


def create_output(title, markdown):
    return {"action": "create", "target_page_id": None, "title": title, "summary": f"Resumen de {title}",
            "markdown": markdown, "change_summary": "Nueva página"}


class RrhhDecider:
    """Ana is in RRHH, Luis is not, the admin reads everything."""

    def can(self, *args, **kwargs):
        return True

    def is_owner(self, company, user):
        return False

    def effective_role(self, company, user):
        return "user"

    def visible_audiences(self, company, user):
        return None if user == "admin@acme.cl" else ([RRHH] if user == "ana@acme.cl" else [])

    def audience_visible(self, company, user, key):
        return user == "admin@acme.cl" or (key == RRHH and user == "ana@acme.cl")

    def audience_label(self, company, key):
        return {RRHH: "RRHH"}.get(key)

    def audience_for_folder(self, company, folder_id):
        return "memory_folder:3" if folder_id == 3 else None


@pytest.fixture
def stack():
    Access.register(RrhhDecider())
    stack = MemoryStack()
    stack.memory_service.save_capture(company_short_name="acme", user_identifier="luis@acme.cl",
                                      capture_text="Pagos a 30 días.", title="Pagos",
                                      new_items=[{"item_type": "note", "content_text": "Pagos a 30 días."}])
    stack.llm_returns(create_output("Pagos", "# Pagos\n\nA 30 días."))
    stack.compiler.compile_pending_for_company("acme")
    stack.memory_service.save_capture(company_short_name="acme", user_identifier="ana@acme.cl",
                                      capture_text="Bono de fin de año: un sueldo.", title="Bonos",
                                      new_items=[{"item_type": "note", "content_text": "Bono de fin de año: un sueldo."}],
                                      audience_key=RRHH)
    stack.llm_returns(create_output("Bonos", "# Bonos\n\nUn sueldo a fin de año."))
    stack.compiler.compile_pending_for_company("acme")
    yield stack
    Access.clear()


def titles(pages):
    return sorted(page["title"] for page in pages)


def test_the_page_takes_the_captures_audience_and_its_folder(stack):
    bonos = next(page for page in stack.pages() if page["title"] == "Bonos")
    pagos = next(page for page in stack.pages() if page["title"] == "Pagos")
    assert bonos["audience_key"] == RRHH and bonos["path"].startswith("rrhh/")
    assert pagos["audience_key"] is None and "/" not in pagos["path"]


def test_the_compiler_never_shows_a_capture_pages_of_another_audience(stack):
    inputs = stack.agent_calls("memory_compiler")[-1]
    assert "Pagos" not in str(inputs.get("page_index")) and "Pagos" not in str(inputs.get("candidate_pages"))


def test_each_person_reads_the_company_and_their_audiences(stack):
    service = stack.memory_service
    assert titles(service.list_pages("acme", user_identifier="ana@acme.cl")) == ["Bonos", "Pagos"]
    assert titles(service.list_pages("acme", user_identifier="luis@acme.cl")) == ["Pagos"]
    assert titles(service.list_pages("acme", user_identifier="admin@acme.cl")) == ["Bonos", "Pagos"]
    assert titles(service.get_memory_dashboard("acme", "luis@acme.cl")["pages"]) == ["Pagos"]


def test_search_and_get_page_follow_the_audience(stack):
    service = stack.memory_service
    bonos = next(page for page in stack.pages() if page["title"] == "Bonos")
    assert "Bonos" in str(service.search_pages("acme", "ana@acme.cl", "Bonos"))
    assert "Bonos" not in str(service.search_pages("acme", "luis@acme.cl", "Bonos"))
    assert service.get_page("acme", "luis@acme.cl", bonos["id"]).get("status") != "success"
    assert service.get_page("acme", "ana@acme.cl", bonos["id"]).get("status") == "success"


def test_restricting_moves_company_pages_and_a_gone_audience_takes_its_pages(stack):
    service = stack.memory_service
    pagos = next(page for page in stack.pages() if page["title"] == "Pagos")
    company = stack.profile_repo.get_company_by_short_name("acme")
    stack.memory_repo.add_page_document(company.id, pagos["id"], 501, "contrato.pdf")

    assert service.restrict_document_pages("acme", [501], RRHH) == 1
    assert titles(service.list_pages("acme", user_identifier="luis@acme.cl")) == []
    assert service.restrict_document_pages("acme", [501], RRHH) == 0  # already restricted

    assert service.delete_audience_pages("acme", RRHH) == 2
    assert stack.pages() == []


def test_a_document_of_a_restricted_folder_is_captured_for_that_folder(stack):
    service = stack.memory_service
    restricted = service.save_document_capture("acme", document_id=77, label="Sueldos.pdf",
                                               source_meta={"folder_id": 3})
    open_one = service.save_document_capture("acme", document_id=78, label="Precios.pdf",
                                             source_meta={"folder_id": 4})
    captures = {c.id: c for c in stack.memory_repo.session.query(MemoryCapture).all()}
    assert captures[restricted["capture"]["capture_id"]].audience_key == "memory_folder:3"
    assert captures[open_one["capture"]["capture_id"]].audience_key is None
