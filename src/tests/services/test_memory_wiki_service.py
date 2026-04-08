from unittest.mock import MagicMock

from iatoolkit.services.memory_wiki_service import MemoryWikiService
from iatoolkit.services.storage_service import StorageService


class TestMemoryWikiService:
    def setup_method(self):
        self.storage_service = MagicMock(spec=StorageService)
        self.service = MemoryWikiService(storage_service=self.storage_service)

    def test_render_and_parse_page_roundtrip(self):
        payload = {
            "page_id": 7,
            "user_identifier": "user@example.com",
            "title": "Inbox inteligente",
            "slug": "inbox-inteligente",
            "summary": "Resumen vivo",
            "key_points": ["Uno", "Dos"],
            "decisions": ["Usar Memoria"],
            "open_questions": ["Cómo mostrarlo"],
            "next_steps": ["Diseñar frontend"],
            "sources": ["nota inicial", "chat"],
            "related_pages": ["otra-pagina"],
            "source_item_ids": [1, 2],
        }

        markdown = self.service.render_page(payload)
        parsed = self.service.parse_page(markdown)

        assert parsed["page_id"] == 7
        assert parsed["title"] == "Inbox inteligente"
        assert parsed["summary"] == "Resumen vivo"
        assert parsed["key_points"] == ["Uno", "Dos"]
        assert parsed["decisions"] == ["Usar Memoria"]
        assert parsed["open_questions"] == ["Cómo mostrarlo"]
        assert parsed["next_steps"] == ["Diseñar frontend"]
        assert parsed["sources"] == ["nota inicial", "chat"]
        assert parsed["related_pages"] == ["otra-pagina"]
        assert parsed["source_item_ids"] == [1, 2]

    def test_build_page_storage_key_sanitizes_user(self):
        storage_key = self.service.build_page_storage_key("acme", "john+demo@example.com", "my-page")
        assert storage_key == "companies/acme/users/john_demo_example.com/memory/wiki/my-page.md"

    def test_render_and_parse_index_roundtrip(self):
        markdown = self.service.render_index([
            {
                "page_id": 7,
                "title": "Inbox inteligente",
                "summary": "Resumen vivo",
                "slug": "inbox-inteligente",
                "wiki_path": "companies/acme/users/u/memory/wiki/inbox-inteligente.md",
                "source_count": 2,
                "last_updated_at": "2026-04-08T12:00:00+00:00",
            }
        ])

        parsed = self.service.parse_index(markdown)

        assert len(parsed["entries"]) == 1
        assert parsed["entries"][0]["page_id"] == 7
        assert parsed["entries"][0]["title"] == "Inbox inteligente"
        assert parsed["entries"][0]["source_count"] == 2

    def test_render_and_parse_log_roundtrip(self):
        markdown = self.service.render_log([
            {
                "timestamp": "2026-04-08T12:00:00+00:00",
                "entry_type": "ingest",
                "title": "Inbox inteligente",
                "details": ["Capture 5 compiled into memory page 7."],
                "metadata": {"page_id": "7", "capture_id": "5"},
            }
        ])

        parsed = self.service.parse_log(markdown)

        assert len(parsed) == 1
        assert parsed[0]["entry_type"] == "ingest"
        assert parsed[0]["title"] == "Inbox inteligente"
        assert parsed[0]["metadata"]["page_id"] == "7"
