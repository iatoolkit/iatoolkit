from tests.services.memory_test_support import MemoryStack


class TestMemoryWikiService:
    def setup_method(self):
        self.stack = MemoryStack()
        self.service = self.stack.memory_wiki_service

    def test_the_company_memory_lives_in_a_system_wiki_hidden_from_the_wiki_module(self):
        result = self.service.ensure_wiki("acme")

        assert result["status"] == "success"
        assert result["wiki"]["system_owner"] == "memory"
        assert self.stack.tenant_wiki_service.list_wikis("acme")["wikis"] == []

    def test_create_page_never_overwrites_a_page_with_the_same_title(self):
        self.service.ensure_wiki("acme")

        first = self.service.create_page("acme", title="Pagos", body="# Pagos\n\nUno.")
        second = self.service.create_page("acme", title="Pagos", body="# Pagos\n\nDos.")

        assert first["page"]["path"] == "pagos.md"
        assert second["page"]["path"] == "pagos-2.md"

    def test_update_page_keeps_frontmatter_and_refuses_a_stale_read(self):
        self.service.ensure_wiki("acme")
        created = self.service.create_page("acme", title="Pagos", body="# Pagos\n\nUno.", summary="Plazos")
        page = self.service.get_page("acme", created["page"]["id"])
        self.service.update_page("acme", page=page, title="Pagos", body="# Pagos\n\nDos.", summary="Plazos")

        stale = self.service.update_page("acme", page=page, title="Pagos", body="# Pagos\n\nTres.")

        assert stale["error_code"] == "page_changed"
        current = self.service.get_page("acme", created["page"]["id"])
        assert self.service.page_body(current) == "# Pagos\n\nDos."
        assert current["frontmatter"]["summary"] == "Plazos"
        assert current["frontmatter"]["status"] == "published"

    def test_the_compiler_schema_is_the_company_memory_schema(self):
        schema = self.service.read_schema()

        assert "Company Memory Wiki Schema" in schema
        assert "attribute every fact you add" in schema

    def test_activity_lists_changes_across_pages_and_a_revision_can_be_read_back(self):
        self.service.ensure_wiki("acme")
        first = self.service.create_page("acme", title="Pagos", body="# Pagos\n\nUno.", edited_by="carmen@acme.cl")
        self.service.create_page("acme", title="Bodega", body="# Bodega\n\nDos.", edited_by="juan@acme.cl")

        activity = self.service.list_activity("acme")
        revision = self.service.get_revision("acme", activity[-1]["id"])

        assert [entry["edited_by"] for entry in activity] == ["juan@acme.cl", "carmen@acme.cl"]
        assert revision["path"] == first["page"]["path"]
        assert "Uno." in revision["markdown"]

    def test_the_memory_wiki_cannot_be_deleted_from_the_wiki_module(self):
        self.service.ensure_wiki("acme")

        result = self.stack.tenant_wiki_service.delete_wiki("acme", wiki_key="iatoolkit-memory")

        assert result["status"] == "error"
        assert self.service.ensure_wiki("acme")["status"] == "success"

