import base64

from iatoolkit.repositories.models import MemoryCaptureStatus, MemoryItemStatus
from tests.services.memory_test_support import MemoryStack


def create_output(title, markdown, summary="", change_summary="Nueva página"):
    return {
        "action": "create",
        "target_page_id": None,
        "title": title,
        "summary": summary,
        "markdown": markdown,
        "change_summary": change_summary,
    }


def update_output(page_id, title, markdown, summary="", change_summary="Actualizada"):
    return {
        "action": "update",
        "target_page_id": page_id,
        "title": title,
        "summary": summary,
        "markdown": markdown,
        "change_summary": change_summary,
    }


class TestMemoryCompilerService:
    def setup_method(self):
        self.stack = MemoryStack()

    def compile(self):
        return self.stack.compiler.compile_pending_for_company("acme")

    def test_a_capture_becomes_a_page_of_the_company_wiki_attributed_to_its_author(self):
        capture = self.stack.save_note("carmen@acme.cl", "Al cliente Transportes Sur no se le despacha los viernes.")
        self.stack.llm_returns(create_output(
            "Despachos",
            "# Despachos\n\nA Transportes Sur no se despacha los viernes. (Carmen Rojas, 2026-10-13)",
            summary="Reglas de despacho",
        ))

        result = self.compile()

        assert result["compiled_count"] == 1
        [page_entry] = self.stack.pages()
        page = self.stack.page(page_entry["id"])
        assert page["title"] == "Despachos"
        assert "(Carmen Rojas, 2026-10-13)" in page["markdown"]
        revisions = self.stack.memory_wiki_service.list_revisions("acme", path=page["path"])
        assert revisions[0]["edited_by"] == "carmen@acme.cl"
        assert revisions[0]["metadata"]["source"] == "memory_compiler"
        assert revisions[0]["metadata"]["capture_id"] == capture["capture_id"]
        assert revisions[0]["change_summary"] == "Nueva página"
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.COMPILED
        assert stored.meta["wiki_page_id"] == page["id"]
        assert self.stack.memory_repo.list_page_source_item_ids(page["id"]) == [capture["items"][0]["id"]]

    def test_the_prompt_names_the_author_and_carries_the_candidate_pages_in_full(self):
        self.stack.save_note("carmen@acme.cl", "Las notas de crédito las aprueba Andrea.", title="Notas de crédito")
        self.stack.llm_returns(create_output(
            "Notas de crédito",
            "# Notas de crédito\n\nLas aprueba Andrea. (Carmen Rojas, 2026-10-01)\n\nSobre $2 millones, segunda firma. (Carmen Rojas, 2026-10-01)",
        ))
        self.compile()
        self.stack.save_note("juan@acme.cl", "Si Andrea no está, aprueba la gerencia.", title="Notas de crédito")
        page_id = self.stack.pages()[0]["id"]
        self.stack.llm_returns(update_output(page_id, "Notas de crédito", "# Notas de crédito\n\nNuevo."))

        self.compile()

        prompt = self.stack.llm_client.invoke.call_args.kwargs["context"]
        assert '"author": "Juan Pérez"' in prompt
        assert "Sobre $2 millones, segunda firma." in prompt
        assert "COMPLETE new markdown" in prompt

    def test_an_update_replaces_the_page_and_keeps_its_history(self):
        self.stack.save_note("carmen@acme.cl", "Plazo de pago: 30 días.", title="Pagos")
        self.stack.llm_returns(create_output("Pagos", "# Pagos\n\n30 días. (Carmen Rojas, 2026-10-01)"))
        self.compile()
        page_id = self.stack.pages()[0]["id"]
        self.stack.save_note("juan@acme.cl", "En la práctica son 45 días.", title="Pagos")
        self.stack.llm_returns(update_output(
            page_id, "Pagos",
            "# Pagos\n\n30 días según el manual. (Carmen Rojas, 2026-10-01)\n\nEn la práctica, 45. (Juan Pérez, 2026-10-13)",
        ))

        self.compile()

        assert len(self.stack.pages()) == 1
        page = self.stack.page(page_id)
        assert "En la práctica, 45." in page["markdown"]
        assert "30 días según el manual." in page["markdown"]
        revisions = self.stack.memory_wiki_service.list_revisions("acme", path=page["path"])
        assert [revision["action"] for revision in revisions] == ["update", "create"]
        assert len(self.stack.memory_repo.list_page_source_item_ids(page_id)) == 2

    def test_a_page_edited_by_someone_while_compiling_is_reread_instead_of_overwritten(self):
        self.stack.save_note("carmen@acme.cl", "Bodega abre a las 8.", title="Bodega")
        self.stack.llm_returns(create_output("Bodega", "# Bodega\n\nAbre a las 8. (Carmen Rojas, 2026-10-01)"))
        self.compile()
        page = self.stack.page(self.stack.pages()[0]["id"])
        self.stack.save_note("juan@acme.cl", "En diciembre abre a las 9.", title="Bodega")
        prompts = []

        def model(**kwargs):
            prompts.append(kwargs["context"])
            if len(prompts) == 1:
                # A person corrects the page by hand while the model is working.
                self.stack.tenant_wiki_service.save_page(
                    "acme", wiki_key="iatoolkit-memory", path=page["path"],
                    markdown="---\ntitle: Bodega\n---\n# Bodega\n\nAbre a las 8:30. (Andrea, a mano)\n",
                    edited_by="andrea@acme.cl",
                )
            body = "# Bodega\n\nAbre a las 8:30. (Andrea, a mano)\n\nEn diciembre, a las 9. (Juan Pérez, 2026-10-13)"
            return {"structured_output": update_output(page["id"], "Bodega", body)}

        self.stack.llm_client.invoke.side_effect = model

        result = self.compile()

        assert result["compiled_count"] == 1
        assert len(prompts) == 2
        assert "Abre a las 8:30. (Andrea, a mano)" in prompts[1]
        saved = self.stack.page(page["id"])
        assert "En diciembre, a las 9." in saved["markdown"]
        editors = [revision["edited_by"] for revision in self.stack.memory_wiki_service.list_revisions("acme", path=page["path"])]
        assert editors == ["juan@acme.cl", "andrea@acme.cl", "carmen@acme.cl"]

    def test_a_capture_with_nothing_durable_is_skipped_without_creating_pages(self):
        capture = self.stack.save_note("carmen@acme.cl", "jaja ok")
        self.stack.llm_returns({
            "action": "skip", "target_page_id": None, "title": "", "summary": "", "markdown": "", "change_summary": "",
        })

        result = self.compile()

        assert result["compiled_count"] == 0
        assert self.stack.pages() == []
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.COMPILED

    def test_without_a_model_the_fact_is_kept_attributed(self):
        self.stack.configuration_service.get_llm_configuration.return_value = (None, {})
        self.stack.save_note("carmen@acme.cl", "Las facturas se emiten el día 25.", title="Facturación")

        self.compile()

        [entry] = self.stack.pages()
        page = self.stack.page(entry["id"])
        assert page["title"] == "Facturación"
        assert "Las facturas se emiten el día 25. (Carmen Rojas," in page["markdown"]

    def test_a_page_nested_by_the_model_is_still_accepted(self):
        self.stack.save_note("carmen@acme.cl", "No hay despachos a Chile registrados.", title="Despachos a Chile")
        self.stack.llm_returns({
            "action": "create",
            "target_page_id": None,
            "page": {
                "title": "Despachos a Chile",
                "summary": "Estado de los despachos a Chile",
                "content_markdown": "# Despachos a Chile\n\nSin procedimiento cargado. (Carmen Rojas, 2026-10-13)",
            },
        })

        self.compile()

        page = self.stack.page(self.stack.pages()[0]["id"])
        assert page["title"] == "Despachos a Chile"
        assert "Sin procedimiento cargado." in page["markdown"]

    def test_a_near_miss_the_schema_rejected_is_repaired_from_the_parsed_output(self):
        self.stack.save_note("carmen@acme.cl", "A Argentina se despacha por Continental Freight.", title="Argentina")
        self.stack.llm_client.invoke.side_effect = [{
            "structured_output": None,
            "parsed_output": {
                "decision": "create",
                "target_page_id": None,
                "title": "Despachos internacionales",
                "markdown": "# Despachos internacionales\n\nArgentina: Continental Freight. (Carmen Rojas, 2026-10-13)",
            },
        }]

        self.compile()

        page = self.stack.page(self.stack.pages()[0]["id"])
        assert page["title"] == "Despachos internacionales"
        assert "Continental Freight. (Carmen Rojas, 2026-10-13)" in page["markdown"]
        revision = self.stack.memory_wiki_service.list_revisions("acme", path=page["path"])[0]
        assert revision["change_summary"] != "Creada sin modelo de lenguaje."

    def test_an_invalid_model_answer_falls_back_instead_of_writing_an_empty_page(self):
        self.stack.save_note("carmen@acme.cl", "El casino cierra a las 15.", title="Casino")
        self.stack.llm_returns(create_output("Casino", "   "))

        self.compile()

        page = self.stack.page(self.stack.pages()[0]["id"])
        assert "El casino cierra a las 15." in page["markdown"]

    def test_the_company_compiles_captures_from_every_author(self):
        self.stack.save_note("carmen@acme.cl", "Uno.", title="Uno")
        self.stack.save_note("juan@acme.cl", "Dos.", title="Dos")
        self.stack.llm_returns(
            create_output("Uno", "# Uno\n\nUno. (Carmen Rojas, 2026-10-13)"),
            create_output("Dos", "# Dos\n\nDos. (Juan Pérez, 2026-10-13)"),
        )

        result = self.stack.compiler.compile_pending_for_user("acme", "carmen@acme.cl")

        assert result["compiled_count"] == 2
        assert sorted(page["title"] for page in self.stack.pages()) == ["Dos", "Uno"]

    def test_a_failing_capture_is_marked_failed_and_the_rest_still_compile(self):
        self.stack.save_note("carmen@acme.cl", "Primera.", title="Primera")
        self.stack.save_note("juan@acme.cl", "Segunda.", title="Segunda")
        self.stack.memory_wiki_service.create_page = _fail_once(self.stack.memory_wiki_service.create_page)
        self.stack.llm_returns(
            create_output("Primera", "# Primera\n\nPrimera."),
            create_output("Segunda", "# Segunda\n\nSegunda."),
        )

        result = self.compile()

        assert result["compiled_count"] == 1
        failed = [capture for capture in self.stack.memory_repo.list_recent_captures(self.stack.company.id)
                  if capture.status == MemoryCaptureStatus.FAILED]
        assert len(failed) == 1
        items = self.stack.memory_repo.list_capture_items(failed[0].id)
        assert all(item.status == MemoryItemStatus.FAILED for item in items)

    def test_pdf_captures_reach_the_model_as_native_attachments(self):
        pdf_bytes = b"%PDF-1.4 manual"
        self.stack.memory_service.util.normalize_base64_payload = base64.b64decode
        self.stack.memory_service.save_capture(
            company_short_name="acme",
            user_identifier="carmen@acme.cl",
            capture_text="Manual de bodega",
            new_items=[
                {"item_type": "file", "filename": "manual.pdf", "mime_type": "application/pdf",
                 "file_base64": base64.b64encode(pdf_bytes).decode("ascii")},
                {"item_type": "file", "filename": "foto.png", "mime_type": "image/png",
                 "file_base64": base64.b64encode(b"png").decode("ascii")},
            ],
        )
        self.stack.llm_returns(create_output("Bodega", "# Bodega\n\nManual."))

        self.compile()

        attachments = self.stack.llm_client.invoke.call_args.kwargs["attachments"]
        assert [attachment["name"] for attachment in attachments] == ["manual.pdf"]


def _fail_once(function):
    state = {"failed": False}

    def wrapper(*args, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("storage unavailable")
        return function(*args, **kwargs)

    return wrapper


class TestPageCorrection:
    def setup_method(self):
        self.stack = MemoryStack()
        self.stack.save_note("carmen@acme.cl", "Plazo de pago: 30 días.", title="Pagos")
        self.stack.llm_returns(create_output(
            "Pagos", "# Pagos\n\nPlazo: 30 días. (Carmen Rojas, 2026-10-01)\n\nFacturas el día 25. (Carmen Rojas, 2026-10-01)"))
        self.stack.compiler.compile_pending_for_company("acme")
        self.page_id = self.stack.pages()[0]["id"]

    def correct(self, text, *outputs):
        response = self.stack.memory_service.request_page_correction("acme", "juan@acme.cl", self.page_id, text)
        assert response["status"] == "success"
        self.stack.llm_returns(*outputs)
        self.stack.compiler.compile_pending_for_company("acme")
        return self.stack.memory_service.get_page_correction("acme", response["correction_id"])["correction"]

    def test_an_applied_correction_reports_the_page_before_and_after(self):
        correction = self.correct("El plazo real es 45 días.", update_output(
            self.page_id, "Pagos",
            "# Pagos\n\nPlazo: 45 días. (Juan Pérez, 2026-10-13)\n\nFacturas el día 25. (Carmen Rojas, 2026-10-01)",
            change_summary="Plazo corregido a 45 días."))

        assert correction["state"] == "applied"
        assert correction["reason"] == "Plazo corregido a 45 días."
        assert "30 días" in correction["before"]
        assert "45 días" in correction["after"]
        assert "Facturas el día 25. (Carmen Rojas, 2026-10-01)" in correction["after"]
        prompt = self.stack.llm_client.invoke.call_args.kwargs["context"]
        assert "Apply only that change" in prompt
        assert "El plazo real es 45 días." in prompt
        revision = self.stack.memory_wiki_service.get_revision("acme", correction["revision_after_id"])
        assert revision["edited_by"] == "juan@acme.cl"
        assert revision["metadata"]["mode"] == "correction"

    def test_undo_is_restoring_the_revision_before(self):
        correction = self.correct("El plazo real es 45 días.", update_output(
            self.page_id, "Pagos", "# Pagos\n\nPlazo: 45 días. (Juan Pérez, 2026-10-13)"))
        before = self.stack.memory_wiki_service.get_revision("acme", correction["revision_before_id"])
        page = self.stack.page(self.page_id)

        self.stack.memory_wiki_service.save_markdown("acme", page=page, markdown=before["markdown"])

        assert "Facturas el día 25." in self.stack.page(self.page_id)["markdown"]

    def test_a_correction_the_model_cannot_place_is_not_applied_and_says_why(self):
        correction = self.correct("Cambia el horario de la bodega.", {
            "action": "skip", "target_page_id": self.page_id, "title": "Pagos", "markdown": "",
            "change_summary": "La página no habla de la bodega.",
        })

        assert correction["state"] == "not_applied"
        assert correction["reason"] == "La página no habla de la bodega."
        assert "30 días" in self.stack.page(self.page_id)["markdown"]

    def test_without_a_model_a_correction_fails_instead_of_appending_text(self):
        self.stack.configuration_service.get_llm_configuration.return_value = (None, {})

        correction = self.correct("El plazo real es 45 días.")

        assert correction["state"] == "failed"
        assert "45" not in self.stack.page(self.page_id)["markdown"]

    def test_a_correction_never_creates_another_page(self):
        self.correct("Agrega que el día 25 cae en fin de semana se factura el lunes.", create_output(
            "Facturación", "# Pagos\n\nPlazo: 30 días. (Carmen Rojas, 2026-10-01)\n\nSi el 25 cae en fin de semana, el lunes. (Juan Pérez, 2026-10-13)"))

        assert len(self.stack.pages()) == 1
        assert "el lunes." in self.stack.page(self.page_id)["markdown"]

    def test_a_correction_of_a_missing_page_is_refused(self):
        response = self.stack.memory_service.request_page_correction("acme", "juan@acme.cl", 999, "algo")

        assert response["status"] == "error"
