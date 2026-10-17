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

        inputs = self.stack.agent_calls("memory_compiler")[-1]
        assert inputs["author"] == "Juan Pérez"
        assert inputs["capture"]["items"][0]["content_text"] == "Si Andrea no está, aprueba la gerencia."
        [candidate] = inputs["candidate_pages"]
        assert "Sobre $2 millones, segunda firma." in candidate["markdown"]
        invoke = self.stack.llm_client.invoke.call_args.kwargs
        assert invoke["execution_trace"] == {"prompt_name": "system_agent:memory_compiler"}
        assert invoke["response_contract"]["schema"]["required"] == ["action", "target_page_id", "title", "markdown"]

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
        calls = []

        def model(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
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
        assert len(calls) == 2
        second = self.stack.agent_calls("memory_compiler")[-1]
        assert "Abre a las 8:30. (Andrea, a mano)" in second["candidate_pages"][0]["markdown"]
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
        inputs = self.stack.agent_calls("memory_correction")[-1]
        assert inputs["request"] == "El plazo real es 45 días."
        assert inputs["author"] == "Juan Pérez"
        assert inputs["page"]["id"] == self.page_id
        assert "30 días" in inputs["page"]["markdown"]
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


class TestMemoryCompilerWithTheAgentOff:
    def setup_method(self):
        from iatoolkit.services.system_agent_runner import PlatformAgentSettings, SystemAgentRunner

        self.stack = MemoryStack()
        self.off = {"memory_compiler": PlatformAgentSettings(enabled=False)}
        SystemAgentRunner.register_platform_settings_provider(lambda key: self.off.get(key))

    def teardown_method(self):
        from iatoolkit.services.system_agent_runner import SystemAgentRunner

        SystemAgentRunner.register_platform_settings_provider(None)

    def test_captures_stay_pending_and_compile_once_it_is_on_again(self):
        capture = self.stack.save_note("carmen@acme.cl", "Bodega abre a las 8.", title="Bodega")

        result = self.stack.compiler.compile_pending_for_company("acme")

        assert (result["compiled_count"], result["waiting_count"]) == (0, 1)
        self.stack.llm_client.invoke.assert_not_called()
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.PENDING
        assert self.stack.pages() == []

        self.off.clear()
        self.stack.llm_returns(create_output("Bodega", "# Bodega\n\nAbre a las 8. (Carmen Rojas, 2026-10-15)"))
        assert self.stack.compiler.compile_pending_for_company("acme")["compiled_count"] == 1
        assert [page["title"] for page in self.stack.pages()] == ["Bodega"]



class _DocumentFixture:
    """A RAG document with two fragments, and a way to queue it for the wiki."""

    def setup_method(self):
        from iatoolkit.repositories.models import Document, DocumentStatus, VSDoc

        self.stack = MemoryStack()
        self.stack.compiler.DOCUMENT_PART_CHARS = 40
        document = Document(company_id=self.stack.company.id, filename="politica-credito.pdf",
                            status=DocumentStatus.ACTIVE, meta={})
        self.stack.session.add(document)
        self.stack.session.commit()
        for text in ("El plazo de pago a clientes es 30 días.", "Sobre $2 millones aprueba gerencia."):
            self.stack.session.add(VSDoc(company_id=self.stack.company.id, document_id=document.id,
                                         text=text, embedding=[0.1, 0.2]))
        self.stack.session.commit()
        self.document = document

    def save_document(self, document_id=None):
        response = self.stack.memory_service.save_document_capture(
            "acme", document_id=document_id or self.document.id, label="Política de crédito v3",
            card={"title": "Política de crédito v3", "summary": "Plazos y aprobaciones", "type": "política"},
            path="Comercial",
        )
        assert response["status"] == "success", response
        return response["capture"]


class TestMemoryCompilerWithDocuments(_DocumentFixture):
    """BL-014: a RAG document feeds the wiki, read whole, part by part."""

    def test_each_part_is_read_and_the_pages_cite_the_document(self):
        capture = self.save_document()
        body = "# Créditos\n\nPlazo: 30 días. (Política de crédito v3, 2026-10-16)"
        page_ids = []

        def model(**kwargs):
            # Part 1 creates the page; part 2 updates the page part 1 wrote.
            existing = self.stack.pages()
            if not existing:
                return {"structured_output": {"pages": [create_output("Créditos", body)]}}
            page_ids.append(existing[0]["id"])
            return {"structured_output": {"pages": [update_output(
                existing[0]["id"], "Créditos",
                body + "\n\nSobre $2 millones, gerencia. (Política de crédito v3, 2026-10-16)")]}}

        self.stack.llm_client.invoke.side_effect = model

        result = self.stack.compiler.compile_pending_for_company("acme")

        assert result["compiled_count"] == 1
        calls = self.stack.agent_calls("memory_document_ingest")
        assert [call["part"]["index"] for call in calls] == [1, 2]
        assert calls[0]["part"]["total"] == 2
        assert calls[0]["source"]["label"] == "Política de crédito v3"
        # The second part sees the page the first one wrote.
        assert [page["page_id"] for page in calls[1]["candidate_pages"]][:1] == page_ids
        assert self.stack.llm_client.invoke.call_args.kwargs["execution_trace"] == {
            "prompt_name": "system_agent:memory_document_ingest"}
        [page_entry] = self.stack.pages()
        page = self.stack.page(page_entry["id"])
        assert "Sobre $2 millones, gerencia." in page["markdown"]
        assert self.stack.memory_repo.list_page_ids_for_document(self.stack.company.id, self.document.id) == [page["id"]]
        [link] = self.stack.memory_repo.list_page_documents(page["id"])
        assert link.label == "Política de crédito v3"
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.COMPILED
        assert stored.meta["wiki_page_ids"] == [page["id"]] and stored.meta["parts"] == 2
        revision = self.stack.memory_wiki_service.list_revisions("acme", path=page["path"])[0]
        assert revision["metadata"]["mode"] == "document"
        assert revision["metadata"]["document_id"] == self.document.id

    def test_a_meeting_transcript_is_read_by_the_meeting_reader(self):
        response = self.stack.memory_service.save_document_capture(
            "acme", document_id=self.document.id, label="Comité comercial 14-10", card={}, path="Reuniones",
            kind="meeting")
        assert response["status"] == "success", response
        self.stack.llm_client.invoke.return_value = {"structured_output": {"pages": []}}

        self.stack.compiler.compile_pending_for_company("acme")

        calls = self.stack.agent_calls("memory_meeting_ingest")
        assert calls and calls[0]["source"]["kind"] == "meeting"
        assert self.stack.agent_calls("memory_document_ingest") == []
        assert self.stack.llm_client.invoke.call_args.kwargs["execution_trace"] == {
            "prompt_name": "system_agent:memory_meeting_ingest"}

    def test_the_capture_points_at_the_document_without_copying_it(self):
        capture = self.save_document()

        [item] = capture["items"]
        stored = self.stack.memory_repo.list_capture_items(capture["capture_id"])[0]
        assert stored.storage_key is None and stored.content_text is None
        assert stored.source_meta["rag_document_id"] == self.document.id
        assert stored.user_identifier == "service:memory-documents"
        assert self.stack.trigger.trigger.called

    def test_a_part_with_nothing_to_keep_writes_no_page(self):
        capture = self.save_document()
        self.stack.llm_returns({"pages": []}, {"pages": []})

        assert self.stack.compiler.compile_pending_for_company("acme")["compiled_count"] == 0
        assert self.stack.pages() == []
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.COMPILED

    def test_a_document_without_text_is_closed_without_calling_the_model(self):
        capture = self.save_document(document_id=999)

        self.stack.compiler.compile_pending_for_company("acme")

        self.stack.llm_client.invoke.assert_not_called()
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.COMPILED and stored.meta["result"] == "empty"

    def test_with_the_reader_off_the_document_waits(self):
        from iatoolkit.services.system_agent_runner import PlatformAgentSettings, SystemAgentRunner

        capture = self.save_document()
        SystemAgentRunner.register_platform_settings_provider(
            lambda key: PlatformAgentSettings(enabled=False) if key == "memory_document_ingest" else None)
        try:
            result = self.stack.compiler.compile_pending_for_company("acme")
        finally:
            SystemAgentRunner.register_platform_settings_provider(None)

        assert result["waiting_count"] == 1
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"])
        assert stored.status == MemoryCaptureStatus.PENDING


class TestMemoryCompilerWithARemovedDocument(_DocumentFixture):
    """BL-014: a deleted document's facts are marked as obsolete, never erased."""

    def load_page_from_document(self):
        self.save_document()
        body = ("# Créditos\n\nPlazo: 30 días. (Política de crédito v3, 2026-10-16)\n\n"
                "En la práctica son 45. (Juan Pérez, 2026-10-13)")
        self.stack.llm_returns({"pages": [create_output("Créditos", body)]}, {"pages": []})
        self.stack.compiler.compile_pending_for_company("acme")
        return self.stack.pages()[0]["id"]

    def test_the_lines_from_the_deleted_document_are_marked_and_the_rest_kept(self):
        page_id = self.load_page_from_document()
        self.stack.llm_client.invoke.reset_mock()

        removal = self.stack.memory_service.save_document_removal_capture(
            "acme", document_id=self.document.id, label="Política de crédito v3", removed_by="ana@acme.cl")
        self.stack.compiler.compile_pending_for_company("acme")

        self.stack.llm_client.invoke.assert_not_called()
        markdown = self.stack.page(page_id)["markdown"]
        assert "Plazo: 30 días. (Política de crédito v3, 2026-10-16) **[obsoleto: se eliminó el documento," in markdown
        assert "En la práctica son 45. (Juan Pérez, 2026-10-13)\n" in markdown + "\n"
        assert "45. (Juan Pérez, 2026-10-13) **[" not in markdown
        [link] = self.stack.memory_repo.list_obsolete_page_documents(self.stack.company.id)
        assert link.wiki_page_id == page_id and link.removed_at is not None
        stored = self.stack.memory_repo.get_capture(self.stack.company.id, removal["capture"]["capture_id"])
        assert stored.meta["result"] == "obsolete_marked" and stored.meta["wiki_page_ids"] == [page_id]

    def test_marking_twice_does_not_mark_again(self):
        page_id = self.load_page_from_document()
        for _ in range(2):
            self.stack.memory_service.save_document_removal_capture(
                "acme", document_id=self.document.id, label="Política de crédito v3")
            self.stack.compiler.compile_pending_for_company("acme")

        assert self.stack.page(page_id)["markdown"].count("obsoleto: se eliminó el documento") == 1

    def test_a_document_no_page_cites_queues_nothing(self):
        result = self.stack.memory_service.save_document_removal_capture(
            "acme", document_id=self.document.id, label="Política de crédito v3")

        assert result["status"] == "skipped"


class TestMemoryConflicts(_DocumentFixture):
    """BL-014: contradictions between sources wait in "Necesita atención"."""

    def test_a_capture_that_contradicts_the_page_records_the_conflict(self):
        self.stack.save_note("carmen@acme.cl", "Plazo de pago: 30 días.", title="Pagos")
        self.stack.llm_returns(create_output("Pagos", "# Pagos\n\n30 días. (Carmen Rojas, 2026-10-01)"))
        self.stack.compiler.compile_pending_for_company("acme")
        page_id = self.stack.pages()[0]["id"]
        self.stack.save_note("juan@acme.cl", "En la práctica son 45 días.", title="Pagos")
        output = update_output(page_id, "Pagos", "# Pagos\n\n30 días. (Carmen Rojas, 2026-10-01)\n\n45. (Juan Pérez, 2026-10-13)")
        output["conflicts"] = [{"existing_statement": "30 días", "existing_source": "Carmen Rojas, 2026-10-01",
                                "new_statement": "45 días", "new_source": "Juan Pérez, 2026-10-13"}]
        self.stack.llm_returns(output)

        self.stack.compiler.compile_pending_for_company("acme")

        [conflict] = self.stack.memory_repo.list_open_conflicts(self.stack.company.id)
        assert (conflict.wiki_page_id, conflict.existing_statement, conflict.new_statement) == (page_id, "30 días", "45 días")
        assert conflict.new_source == "Juan Pérez, 2026-10-13"
        schema = self.stack.llm_client.invoke.call_args.kwargs["response_contract"]["schema"]
        assert "conflicts" in schema["properties"]

    def test_a_document_part_places_each_conflict_on_the_page_it_names(self):
        self.save_document()
        page = create_output("Créditos", "# Créditos\n\nPlazo 30. (Política de crédito v3, 2026-10-16)")
        self.stack.llm_returns(
            {"pages": [page], "conflicts": [{"page_title": "Créditos", "existing_statement": "45 días",
                                             "new_statement": "30 días"}]},
            {"pages": [], "conflicts": [{"page_title": "Otra", "existing_statement": "x", "new_statement": "y"}]},
        )

        self.stack.compiler.compile_pending_for_company("acme")

        [conflict] = self.stack.memory_repo.list_open_conflicts(self.stack.company.id)
        assert conflict.wiki_page_id == self.stack.pages()[0]["id"]
        assert conflict.existing_statement == "45 días"


class TestMemoryCompilerWithImages:
    """BL-014: images feed the wiki, looked at by a model with vision."""

    def setup_method(self):
        from iatoolkit.repositories.models import Document, DocumentImage, DocumentStatus

        self.stack = MemoryStack()
        self.stack.storage["companies/acme/images/pizarra.png"] = b"\x89PNG fake"
        document = Document(company_id=self.stack.company.id, filename="pizarra.png", status=DocumentStatus.ACTIVE, meta={})
        self.stack.session.add(document)
        self.stack.session.commit()
        self.stack.session.add(DocumentImage(document_id=document.id, storage_key="companies/acme/images/pizarra.png"))
        self.stack.session.commit()
        self.document = document
        # Whatever model the stack resolves reads images.
        self.stack.system_agent_runner._mock_wraps.supports_images = lambda company, model: True

    def test_an_image_loaded_as_a_document_is_looked_at_by_the_image_reader(self):
        self.stack.memory_service.save_document_capture("acme", document_id=self.document.id, label="Pizarra de despachos")
        self.stack.llm_returns({"pages": [create_output("Despachos", "# Despachos\n\nRegiones los martes. (Pizarra de despachos, 2026-10-16)")]})

        result = self.stack.compiler.compile_pending_for_company("acme")

        assert result["compiled_count"] == 1
        [call] = self.stack.agent_calls("memory_image_ingest")
        assert call["source"]["label"] == "Pizarra de despachos"
        [image] = self.stack.llm_client.invoke.call_args.kwargs["images"]
        assert image["name"] == "pizarra.png" and image["mime_type"] == "image/png" and image["base64"]
        assert self.stack.memory_repo.list_page_ids_for_document(self.stack.company.id, self.document.id)

    def test_images_attached_to_a_capture_reach_the_compiler(self):
        import base64

        response = self.stack.memory_service.save_capture(
            company_short_name="acme", user_identifier="carmen@acme.cl", capture_text="El flujo de aprobación",
            new_items=[{"item_type": "image", "filename": "flujo.png", "mime_type": "image/png",
                        "file_base64": base64.b64encode(b"\x89PNG flujo").decode()}],
        )
        assert response["status"] == "success"
        self.stack.llm_returns(create_output("Aprobaciones", "# Aprobaciones\n\nFlujo. (Carmen Rojas, 2026-10-16)"))

        self.stack.compiler.compile_pending_for_company("acme")

        [image] = self.stack.llm_client.invoke.call_args.kwargs["images"]
        assert image["name"] == "flujo.png"


class TestSavedLinksAreFetchedSafely:
    """Fase 0 (R2): a link a person saved is never fetched from a private or metadata address."""

    def setup_method(self):
        self.stack = MemoryStack()

    def link_item(self, url):
        from iatoolkit.repositories.models import MemoryItem, MemoryItemType
        return MemoryItem(company_id=self.stack.company.id, user_identifier="carmen@acme.cl",
                          item_type=MemoryItemType.LINK, source_url=url)

    def test_a_metadata_address_is_never_requested(self, monkeypatch):
        import iatoolkit.common.url_safety as url_safety

        calls = []
        monkeypatch.setattr(url_safety.requests, "get", lambda *a, **k: calls.append(a) or None)
        item = self.link_item("http://169.254.169.254/latest/meta-data/")

        self.stack.compiler._enrich_item("acme", item)

        assert calls == [] and item.content_text is None

    def test_a_public_page_gives_its_title_and_start(self, monkeypatch):
        import iatoolkit.common.url_safety as url_safety

        class Raw:
            def read(self, size, decode_content=True):
                return b"<html><title>Despachos</title><body>Los viernes no se despacha.</body></html>"

        class Response:
            status_code, headers, encoding, raw = 200, {}, "utf-8", Raw()
            def raise_for_status(self): pass
            def close(self): pass

        monkeypatch.setattr(url_safety, "assert_public_http_url", lambda url, **kwargs: None)
        monkeypatch.setattr(url_safety.requests, "get", lambda *a, **k: Response())
        item = self.link_item("https://example.com/despachos")
        self.stack.memory_repo.save_item = lambda item: None

        self.stack.compiler._enrich_item("acme", item)

        assert item.content_text.startswith("Despachos") and "no se despacha" in item.content_text
