from types import SimpleNamespace
from unittest.mock import MagicMock

from iatoolkit.services.memory_compiler_service import MemoryCompilerService
from iatoolkit.repositories.models import MemoryItemType


class TestMemoryCompilerService:
    def setup_method(self):
        self.profile_repo = MagicMock()
        self.memory_repo = MagicMock()
        self.memory_wiki_service = MagicMock()
        self.llm_client = MagicMock()
        self.configuration_service = MagicMock()
        self.storage_service = MagicMock()

        self.service = MemoryCompilerService(
            profile_repo=self.profile_repo,
            memory_repo=self.memory_repo,
            memory_wiki_service=self.memory_wiki_service,
            llm_client=self.llm_client,
            configuration_service=self.configuration_service,
            storage_service=self.storage_service,
        )

    def test_compile_single_capture_prefers_existing_page_linked_in_capture_meta(self):
        company = SimpleNamespace(id=1, short_name="acme")
        capture = SimpleNamespace(
            id=10,
            title="Memoria semanal",
            user_identifier="user@example.com",
            meta={"page_id": 41},
            status=None,
            compile_error=None,
            last_compiled_at=None,
        )
        item = SimpleNamespace(
            id=101,
            item_type="note",
            title="Memoria semanal",
            content_text="Esta semana trabajo en memoria",
            source_url=None,
            filename=None,
            mime_type=None,
            source_meta={},
            status=None,
            compile_error=None,
        )
        preferred_page = SimpleNamespace(id=41, title="Pagina existente", summary="Resumen previo")
        competing_page = SimpleNamespace(id=99, title="Otra pagina", summary="Resumen alternativo")
        updated_page = SimpleNamespace(id=41, title="Pagina existente", summary="Resumen nuevo", wiki_path="wiki/existente.md")

        self.memory_repo.get_page.return_value = preferred_page
        self.memory_repo.list_pages_for_items.return_value = []
        self.memory_repo.search_pages.return_value = [competing_page]
        self.configuration_service.get_llm_configuration.return_value = ("gpt-5-mini", {})
        self.memory_wiki_service.read_page.return_value = {"summary": "Resumen previo", "key_points": [], "decisions": []}
        self.llm_client.invoke.return_value = {
            "structured_output": {
                "action": "update",
                "target_page_id": None,
                "title": "Pagina existente",
                "summary": "Resumen nuevo",
                "key_points": [],
                "decisions": [],
                "open_questions": [],
                "next_steps": [],
                "related_pages": [],
                "sources": [],
            }
        }
        self.memory_wiki_service.slugify.return_value = "pagina-existente"
        self.memory_wiki_service.build_page_storage_key.return_value = "companies/acme/users/user/memory/wiki/pagina-existente.md"
        self.memory_repo.create_or_update_page.return_value = updated_page
        self.memory_repo.list_page_sources.return_value = []

        compiled = self.service._compile_single_capture(company, capture, [item])

        assert compiled is True
        self.memory_repo.create_or_update_page.assert_called_once()
        assert self.memory_repo.create_or_update_page.call_args.kwargs["page_id"] == 41
        assert capture.meta["page_id"] == 41

    def test_compile_with_llm_attaches_pdf_files_from_capture(self):
        company = SimpleNamespace(short_name="acme")
        capture = SimpleNamespace(id=10, title="Quarterly report", user_identifier="user@example.com")
        pdf_item = SimpleNamespace(
            id=101,
            item_type=MemoryItemType.FILE,
            title="Quarterly report",
            content_text=None,
            source_url=None,
            filename="report.pdf",
            mime_type="application/pdf",
            source_meta={},
            storage_key="companies/acme/users/user/memory/raw/abc/report.pdf",
        )
        self.configuration_service.get_llm_configuration.return_value = ("gpt-5-mini", {})
        self.memory_wiki_service.read_schema.return_value = "# schema"
        self.memory_wiki_service.read_index.return_value = {"entries": []}
        self.storage_service.get_document_content.return_value = b"%PDF-1.4 sample"
        self.llm_client.invoke.return_value = {
            "structured_output": {
                "action": "create",
                "target_page_id": None,
                "title": "Quarterly report",
                "summary": "Important PDF",
                "key_points": [],
                "decisions": [],
                "open_questions": [],
                "next_steps": [],
                "related_pages": [],
                "sources": [],
            }
        }

        result = self.service._compile_with_llm(company, capture, [pdf_item], [])

        assert result["title"] == "Quarterly report"
        invoke_kwargs = self.llm_client.invoke.call_args.kwargs
        assert len(invoke_kwargs["attachments"]) == 1
        assert invoke_kwargs["attachments"][0]["name"] == "report.pdf"
        assert invoke_kwargs["attachments"][0]["mime_type"] == "application/pdf"
        assert invoke_kwargs["attachments"][0]["base64"]

    def test_compile_with_llm_skips_non_pdf_attachments(self):
        company = SimpleNamespace(short_name="acme")
        capture = SimpleNamespace(id=10, title="Text notes", user_identifier="user@example.com")
        file_item = SimpleNamespace(
            id=101,
            item_type=MemoryItemType.FILE,
            title="notes.txt",
            content_text=None,
            source_url=None,
            filename="notes.txt",
            mime_type="text/plain",
            source_meta={},
            storage_key="companies/acme/users/user/memory/raw/abc/notes.txt",
        )
        self.configuration_service.get_llm_configuration.return_value = ("gpt-5-mini", {})
        self.memory_wiki_service.read_schema.return_value = "# schema"
        self.memory_wiki_service.read_index.return_value = {"entries": []}
        self.llm_client.invoke.return_value = {
            "structured_output": {
                "action": "create",
                "target_page_id": None,
                "title": "Text notes",
                "summary": "Plain file",
                "key_points": [],
                "decisions": [],
                "open_questions": [],
                "next_steps": [],
                "related_pages": [],
                "sources": [],
            }
        }

        self.service._compile_with_llm(company, capture, [file_item], [])

        invoke_kwargs = self.llm_client.invoke.call_args.kwargs
        assert invoke_kwargs["attachments"] == []
