from types import SimpleNamespace
from unittest.mock import MagicMock

from iatoolkit.repositories.models import Company, MemoryItemType
from iatoolkit.services.memory_service import MemoryService


class TestMemoryService:
    def setup_method(self):
        self.profile_repo = MagicMock()
        self.memory_repo = MagicMock()
        self.memory_wiki_service = MagicMock()
        self.memory_compiler_service = MagicMock()
        self.memory_lint_service = MagicMock()
        self.memory_compilation_trigger = MagicMock()
        self.memory_compilation_trigger.is_async_enabled.return_value = False
        self.memory_lint_trigger = MagicMock()
        self.memory_lint_trigger.is_async_enabled.return_value = False
        self.memory_lint_trigger.trigger.return_value = MagicMock(triggered=False)
        self.storage_service = MagicMock()
        self.util = MagicMock()

        self.service = MemoryService(
            profile_repo=self.profile_repo,
            memory_repo=self.memory_repo,
            memory_wiki_service=self.memory_wiki_service,
            memory_compiler_service=self.memory_compiler_service,
            memory_lint_service=self.memory_lint_service,
            memory_compilation_trigger=self.memory_compilation_trigger,
            memory_lint_trigger=self.memory_lint_trigger,
            storage_service=self.storage_service,
            util=self.util,
        )

        self.company = Company(id=1, short_name="acme", name="Acme")
        self.profile_repo.get_company_by_short_name.return_value = self.company

    def test_save_note_creates_pending_item(self):
        captured = {}

        def _capture(item):
            item.id = 99
            captured["item"] = item
            return item

        self.memory_repo.create_item.side_effect = _capture

        result = self.service.save_item(
            company_short_name="acme",
            user_identifier="user@example.com",
            item_type="note",
            content_text="Idea importante",
            title="Idea importante",
        )

        assert result["status"] == "success"
        assert captured["item"].item_type == MemoryItemType.NOTE
        assert captured["item"].content_text == "Idea importante"
        self.memory_compilation_trigger.trigger.assert_called_once_with(
            company_short_name="acme",
            user_identifier="user@example.com",
            trigger_item_id=99,
            reason="capture",
        )

    def test_save_file_uploads_bytes(self):
        self.util.normalize_base64_payload.return_value = b"hello world"

        self.service.save_item(
            company_short_name="acme",
            user_identifier="user@example.com",
            item_type="file",
            filename="memo.txt",
            mime_type="text/plain",
            file_base64="aGVsbG8=",
        )

        self.storage_service.upload_bytes.assert_called_once()

    def test_get_memory_dashboard_triggers_on_demand_compile(self):
        self.memory_repo.list_recent_captures.return_value = []
        self.memory_repo.list_pages.return_value = []
        self.memory_lint_service.get_last_lint_result.return_value = {}

        result = self.service.get_memory_dashboard("acme", "user@example.com")

        assert result["status"] == "success"
        self.memory_compiler_service.compile_pending_for_user.assert_called_once_with("acme", "user@example.com")

    def test_get_memory_dashboard_skips_on_demand_when_async_trigger_enabled(self):
        self.memory_compilation_trigger.is_async_enabled.return_value = True
        self.memory_repo.list_recent_captures.return_value = []
        self.memory_repo.list_pages.return_value = []
        self.memory_lint_service.get_last_lint_result.return_value = {}

        result = self.service.get_memory_dashboard("acme", "user@example.com")

        assert result["status"] == "success"
        self.memory_compiler_service.compile_pending_for_user.assert_not_called()

    def test_get_memory_dashboard_includes_last_lint_summary(self):
        self.memory_repo.list_recent_captures.return_value = []
        self.memory_repo.list_pages.return_value = []
        self.memory_lint_service.get_last_lint_result.return_value = {
            "title": "Memory wiki health check",
            "timestamp": "2026-04-08T14:00:00+00:00",
            "checked_pages": 2,
            "actions_applied": 1,
            "duplicate_candidates": 0,
            "orphan_pages": 1,
            "details": ["Checked 2 pages."],
        }

        result = self.service.get_memory_dashboard("acme", "user@example.com")

        assert result["status"] == "success"
        assert result["last_lint"]["checked_pages"] == 2
        assert result["last_lint"]["actions_applied"] == 1

    def test_lint_memory_wiki_returns_summary_and_logs_result(self):
        self.memory_lint_service.run_memory_lint.return_value = {
            "status": "success",
            "mode": "inline",
            "lint": {
                "checked_pages": 1,
                "actions_applied": 1,
            },
        }

        result = self.service.lint_memory_wiki("acme", "user@example.com")

        assert result["status"] == "success"
        assert result["mode"] == "inline"
        assert result["lint"]["checked_pages"] == 1
        assert result["lint"]["actions_applied"] == 1
        self.memory_lint_service.run_memory_lint.assert_called_once_with("acme", "user@example.com")

    def test_lint_memory_wiki_returns_async_task_response_when_triggered(self):
        self.memory_lint_trigger.trigger.return_value = MagicMock(
            triggered=True,
            mode="async_task",
            metadata={"task_id": 77, "task_status": "pending"},
        )

        result = self.service.lint_memory_wiki("acme", "user@example.com")

        assert result["status"] == "success"
        assert result["mode"] == "async_task"
        assert result["lint"] is None
        assert result["task"]["task_id"] == 77
        self.memory_wiki_service.append_log_entry.assert_not_called()

    def test_search_pages_returns_serialized_results(self):
        page = MagicMock()
        page.id = 12
        page.title = "Producto"
        page.summary = "Resumen"
        page.slug = "producto"
        page.wiki_path = "companies/acme/users/x/memory/wiki/producto.md"
        page.updated_at = None
        self.memory_repo.list_pages.return_value = [page]
        self.memory_wiki_service.read_page.return_value = {
            "summary": "Resumen",
            "key_points": [],
            "decisions": [],
            "open_questions": [],
            "next_steps": [],
            "sources": [],
            "related_pages": [],
        }

        result = self.service.search_pages("acme", "user@example.com", query="producto", limit=3)

        assert result["status"] == "success"
        assert result["results"][0]["page_id"] == 12

    def test_search_pages_matches_tokenized_compiled_memory_content(self):
        page = MagicMock()
        page.id = 22
        page.title = "Roadmap semanal"
        page.summary = "Implementacion"
        page.slug = "roadmap-semanal"
        page.wiki_path = "companies/acme/users/x/memory/wiki/roadmap-semanal.md"
        page.updated_at = None
        self.memory_repo.list_pages.return_value = [page]
        self.memory_wiki_service.read_page.return_value = {
            "summary": "Esta semana en iatoolkit quiero implementar agentes, tareas y memorias",
            "key_points": ["Implementar agentes", "Implementar tareas", "Implementar memorias"],
            "decisions": [],
            "open_questions": [],
            "next_steps": [],
            "sources": [],
            "related_pages": [],
        }

        result = self.service.search_pages(
            "acme",
            "user@example.com",
            query="plan esta semana iatoolkit agenda to do",
            limit=5,
        )

        assert result["status"] == "success"
        assert len(result["results"]) == 1
        assert result["results"][0]["page_id"] == 22
        assert result["results"][0]["score"] > 0

    def test_search_pages_matches_singular_plural_variants(self):
        page = MagicMock()
        page.id = 24
        page.title = "Futuro proyecto"
        page.summary = "Bandeja de entrada personal"
        page.slug = "futuro-proyecto"
        page.wiki_path = "companies/acme/users/x/memory/wiki/futuro-proyecto.md"
        page.updated_at = None
        self.memory_repo.list_pages.return_value = [page]
        self.memory_wiki_service.read_page.return_value = {
            "summary": "Futuro proyecto: bandeja de entrada personal",
            "key_points": ["Bandeja de entrada personal"],
            "decisions": [],
            "open_questions": [],
            "next_steps": [],
            "sources": [],
            "related_pages": [],
        }

        result = self.service.search_pages(
            "acme",
            "user@example.com",
            query="proyectos futuros",
            limit=5,
        )

        assert result["status"] == "success"
        assert len(result["results"]) == 1
        assert result["results"][0]["page_id"] == 24
        assert result["results"][0]["score"] > 0

    def test_search_pages_matches_link_source_items_and_returns_url(self):
        page = MagicMock()
        page.id = 33
        page.title = "AI assistant article"
        page.summary = "Article"
        page.slug = "ai-assistant-article"
        page.wiki_path = "companies/acme/users/x/memory/wiki/ai-assistant-article.md"
        page.updated_at = None

        source_item = SimpleNamespace(
            id=77,
            title="Build Your Personal AI Assistant with Claude Code | Ron Forbes",
            content_text="Build Your Personal AI Assistant with Claude Code | Ron Forbes",
            source_url="https://ronforbes.com/build-your-personal-ai-assistant",
            filename=None,
        )

        self.memory_repo.list_pages.return_value = [page]
        self.memory_wiki_service.read_page.return_value = {
            "summary": "Article about building a personal AI assistant",
            "key_points": [],
            "decisions": [],
            "open_questions": [],
            "next_steps": [],
            "sources": [],
            "related_pages": [],
            "source_item_ids": [77],
        }
        self.memory_repo.list_items_by_ids.return_value = [source_item]

        result = self.service.search_pages(
            "acme",
            "user@example.com",
            query="forbes link",
            limit=5,
        )

        assert result["status"] == "success"
        assert len(result["results"]) == 1
        assert result["results"][0]["page_id"] == 33
        assert result["results"][0]["source_urls"] == ["https://ronforbes.com/build-your-personal-ai-assistant"]
        assert result["results"][0]["score"] > 0

    def test_search_pages_returns_raw_item_matches_when_page_match_is_missing(self):
        source_item = SimpleNamespace(
            id=88,
            item_type=MemoryItemType.LINK,
            status="compiled",
            title="Build Your Personal AI Assistant with Claude Code | Ron Forbes",
            content_text="Build Your Personal AI Assistant with Claude Code | Ron Forbes",
            source_url="https://ronforbes.com/build-your-personal-ai-assistant",
            filename=None,
            mime_type=None,
            storage_key=None,
            created_at=None,
        )

        self.memory_repo.list_pages.return_value = []
        self.memory_repo.list_recent_items.return_value = [source_item]

        result = self.service.search_pages(
            "acme",
            "user@example.com",
            query="forbes link",
            limit=5,
        )

        assert result["status"] == "success"
        assert result["results"] == []
        assert len(result["raw_items"]) == 1
        assert result["raw_items"][0]["source_url"] == "https://ronforbes.com/build-your-personal-ai-assistant"
        assert result["raw_items"][0]["score"] > 0

    def test_delete_item_removes_file_and_repairs_pages(self):
        item = SimpleNamespace(id=7, storage_key="companies/acme/users/u/memory/raw/file.txt")
        page = SimpleNamespace(id=3)
        self.memory_repo.get_item.return_value = item
        self.memory_repo.list_pages_for_item.return_value = [page]
        self.service._repair_page_after_item_delete = MagicMock()

        result = self.service.delete_item("acme", "user@example.com", 7)

        assert result["status"] == "success"
        self.memory_repo.delete_item.assert_called_once_with(item)
        self.storage_service.delete_file.assert_called_once_with("acme", item.storage_key)
        self.service._repair_page_after_item_delete.assert_called_once_with(
            company_short_name="acme",
            company_id=1,
            user_identifier="user@example.com",
            page_id=3,
        )

    def test_get_page_includes_source_items_with_access_urls(self):
        page = SimpleNamespace(
            id=14,
            title="469204.pdf",
            summary="Saved file: 469204.pdf",
            slug="469204-pdf",
            wiki_path="companies/acme/users/x/memory/wiki/469204-pdf.md",
            updated_at=None,
        )
        item = SimpleNamespace(
            id=91,
            item_type=MemoryItemType.FILE,
            status="compiled",
            title="469204.pdf",
            content_text="Saved file: 469204.pdf",
            source_url=None,
            filename="469204.pdf",
            mime_type="application/pdf",
            storage_key="companies/acme/users/x/memory/raw/469204.pdf",
            created_at=None,
        )
        self.memory_repo.get_page.return_value = page
        self.memory_wiki_service.read_page.return_value = {
            "title": "469204.pdf",
            "summary": "Saved file: 469204.pdf",
            "sources": ["469204.pdf"],
            "source_item_ids": [91],
        }
        self.memory_repo.list_items_by_ids.return_value = [item]
        self.storage_service.generate_presigned_url.return_value = "https://cdn.example.com/469204.pdf"

        result = self.service.get_page("acme", "user@example.com", 14)

        assert result["status"] == "success"
        assert result["page"]["source_items"][0]["filename"] == "469204.pdf"
        assert result["page"]["source_items"][0]["access_url"] == "https://cdn.example.com/469204.pdf"

    def test_serialize_item_includes_capture_group_id(self):
        item = SimpleNamespace(
            id=5,
            item_type=MemoryItemType.NOTE,
            status="compiled",
            title="Nota",
            content_text="Idea",
            source_url=None,
            filename=None,
            mime_type=None,
            storage_key=None,
            source_meta={"capture_group_id": "capture-123"},
            created_at=None,
        )

        payload = self.service.serialize_item(item)

        assert payload["capture_group_id"] == "capture-123"
