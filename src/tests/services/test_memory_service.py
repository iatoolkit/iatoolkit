import base64

from tests.services.memory_test_support import MemoryStack


def create_output(title, markdown, summary=""):
    return {
        "action": "create",
        "target_page_id": None,
        "title": title,
        "summary": summary,
        "markdown": markdown,
        "change_summary": "Nueva página",
    }


class TestMemoryService:
    def setup_method(self):
        self.stack = MemoryStack()
        self.service = self.stack.memory_service

    def compile(self):
        self.stack.compiler.compile_pending_for_company("acme")

    def page_from(self, author, text, title, markdown):
        capture = self.stack.save_note(author, text, title=title)
        self.stack.llm_returns(create_output(title, markdown, summary=f"Resumen de {title}"))
        self.compile()
        return capture

    def test_save_capture_requires_an_author(self):
        response = self.service.save_capture(
            company_short_name="acme",
            user_identifier="",
            new_items=[{"item_type": "note", "content_text": "algo"}],
        )

        assert response["status"] == "error"

    def test_save_capture_triggers_compilation_and_records_the_author(self):
        capture = self.stack.save_note("carmen@acme.cl", "Nota")

        assert capture["author"] == "carmen@acme.cl"
        assert capture["items"][0]["author"] == "carmen@acme.cl"
        self.stack.trigger.trigger.assert_called_once()

    def test_files_are_stored_under_the_company_not_under_a_user(self):
        self.stack.memory_service.util.normalize_base64_payload = base64.b64decode
        response = self.service.save_capture(
            company_short_name="acme",
            user_identifier="carmen@acme.cl",
            new_items=[{"item_type": "file", "filename": "manual.pdf", "mime_type": "application/pdf",
                        "file_base64": base64.b64encode(b"%PDF").decode("ascii")}],
        )

        [storage_key] = list(self.stack.storage)
        assert storage_key.startswith("companies/acme/memory/raw/")
        assert storage_key.endswith("/manual.pdf")
        assert "/users/" not in storage_key
        assert response["capture"]["items"][0]["access_url"] == f"https://files/{storage_key}"

    def test_dashboard_shows_my_captures_and_every_company_page(self):
        self.page_from("carmen@acme.cl", "Despachos", "Despachos", "# Despachos\n\nNo los viernes.")
        self.page_from("juan@acme.cl", "Pagos", "Pagos", "# Pagos\n\n45 días.")

        dashboard = self.service.get_memory_dashboard("acme", "carmen@acme.cl")

        assert [capture["title"] for capture in dashboard["captures"]] == ["Despachos"]
        assert sorted(page["title"] for page in dashboard["pages"]) == ["Despachos", "Pagos"]

    def test_dashboard_compiles_on_demand_when_compilation_is_not_async(self):
        self.stack.trigger.is_async_enabled.return_value = False
        self.stack.save_note("carmen@acme.cl", "Bodega abre a las 8.", title="Bodega")
        self.stack.llm_returns(create_output("Bodega", "# Bodega\n\nA las 8."))

        dashboard = self.service.get_memory_dashboard("acme", "juan@acme.cl")

        assert [page["title"] for page in dashboard["pages"]] == ["Bodega"]

    def test_search_finds_pages_written_by_anyone_in_the_company(self):
        self.page_from("carmen@acme.cl", "Notas de crédito", "Notas de crédito",
                       "# Notas de crédito\n\nLas aprueba Andrea Rojas. (Carmen Rojas, 2026-10-06)")

        response = self.service.search_pages("acme", "juan@acme.cl", query="quién aprueba notas de crédito", limit=5)

        assert response["status"] == "success"
        [result] = response["results"]
        assert result["title"] == "Notas de crédito"
        assert result["sources"] == ["Notas de crédito"]
        assert result["has_native_files"] is False

    def test_search_marks_pages_whose_sources_include_files(self):
        self.stack.memory_service.util.normalize_base64_payload = base64.b64decode
        self.service.save_capture(
            company_short_name="acme",
            user_identifier="carmen@acme.cl",
            capture_text="Manual de bodega",
            title="Manual de bodega",
            new_items=[{"item_type": "file", "filename": "manual.pdf", "mime_type": "application/pdf",
                        "file_base64": base64.b64encode(b"%PDF-1.4").decode("ascii")}],
        )
        self.stack.llm_returns(create_output("Manual de bodega", "# Manual de bodega\n\nVer manual."))
        self.compile()

        response = self.service.search_pages("acme", "juan@acme.cl", query="manual de bodega", limit=5,
                                             include_native_attachments=True)

        assert response["results"][0]["has_native_files"] is True
        assert response["results"][0]["native_filenames"] == ["manual.pdf"]
        assert [attachment["name"] for attachment in response[self.service.TOOL_NATIVE_ATTACHMENTS_KEY]] == ["manual.pdf"]

    def test_search_also_returns_raw_captures_not_yet_compiled(self):
        self.stack.save_note("carmen@acme.cl", "El casino cierra a las 15 horas.")

        response = self.service.search_pages("acme", "juan@acme.cl", query="casino", limit=5)

        assert response["results"] == []
        assert response["raw_items"][0]["content_text"] == "El casino cierra a las 15 horas."

    def test_get_page_returns_markdown_sanitized_html_and_sources(self):
        self.page_from("carmen@acme.cl", "Pagos", "Pagos",
                       "# Pagos\n\n45 días en la práctica.\n\n<script>alert(1)</script>")
        page_id = self.stack.pages()[0]["id"]

        response = self.service.get_page("acme", "juan@acme.cl", page_id)

        page = response["page"]
        assert page["page_id"] == page_id
        assert "45 días en la práctica." in page["markdown"]
        assert "<h1>" not in page["html"]
        assert "45 días en la práctica." in page["html"]
        assert "<script>" not in page["html"]
        assert page["source_items"][0]["author"] == "carmen@acme.cl"

    def test_get_page_of_an_unknown_page_is_not_found(self):
        assert self.service.get_page("acme", "juan@acme.cl", 999)["status"] == "error"

    def test_deleting_my_capture_unlinks_it_and_keeps_the_page(self):
        capture = self.page_from("carmen@acme.cl", "Despachos", "Despachos", "# Despachos\n\nNo los viernes.")
        page_id = self.stack.pages()[0]["id"]

        response = self.service.delete_capture("acme", "carmen@acme.cl", capture["capture_id"])

        assert response["status"] == "success"
        assert self.stack.page(page_id)["markdown"].strip().endswith("No los viernes.")
        assert self.stack.memory_repo.list_page_source_item_ids(page_id) == []

    def test_nobody_deletes_someone_elses_capture(self):
        capture = self.stack.save_note("carmen@acme.cl", "Nota de Carmen")

        response = self.service.delete_capture("acme", "juan@acme.cl", capture["capture_id"])

        assert response["status"] == "error"
        assert self.stack.memory_repo.get_capture(self.stack.company.id, capture["capture_id"]) is not None

    def test_deleting_a_file_item_removes_the_stored_file(self):
        self.stack.memory_service.util.normalize_base64_payload = base64.b64decode
        response = self.service.save_capture(
            company_short_name="acme",
            user_identifier="carmen@acme.cl",
            new_items=[{"item_type": "file", "filename": "a.pdf", "mime_type": "application/pdf",
                        "file_base64": base64.b64encode(b"%PDF").decode("ascii")}],
        )
        item_id = response["capture"]["items"][0]["id"]

        result = self.service.delete_item("acme", "carmen@acme.cl", item_id)

        assert result["status"] == "success"
        assert self.stack.storage == {}

    def test_update_capture_is_limited_to_its_author(self):
        capture = self.stack.save_note("carmen@acme.cl", "Original")

        response = self.service.update_capture("acme", "juan@acme.cl", capture["capture_id"], capture_text="Cambio")

        assert response["status"] == "error"
