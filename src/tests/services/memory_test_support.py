"""Real Memoria stack over SQLite and an in-memory storage, for the memory tests."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo
from iatoolkit.repositories.memory_repo import MemoryRepo
from iatoolkit.repositories.models import Company
from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.memory_compiler_service import MemoryCompilerService
from iatoolkit.services.memory_service import MemoryService
from iatoolkit.services.memory_wiki_service import MemoryWikiService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.system_agent_runner import SystemAgentRunner
from iatoolkit.services.tenant_wiki_service import TenantWikiService


USERS = {
    "carmen@acme.cl": SimpleNamespace(email="carmen@acme.cl", first_name="Carmen", last_name="Rojas"),
    "juan@acme.cl": SimpleNamespace(email="juan@acme.cl", first_name="Juan", last_name="Pérez"),
}


class MemoryStack:
    def __init__(self):
        self.db_manager = DatabaseManager("sqlite:///:memory:")
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.company = Company(name="Acme", short_name="acme")
        self.session.add(self.company)
        self.session.commit()

        self.profile_repo = MagicMock()
        self.profile_repo.get_company_by_short_name.return_value = self.company
        self.profile_repo.get_user_by_email.side_effect = lambda email: USERS.get(email)

        self.storage = {}
        self.storage_service = MagicMock(spec=StorageService)
        self.storage_service.upload_bytes.side_effect = self._upload_bytes
        self.storage_service.get_document_content.side_effect = self._get_document_content
        self.storage_service.list_files.side_effect = self._list_files
        self.storage_service.delete_file.side_effect = lambda company_short_name, storage_key: self.storage.pop(storage_key, None)
        self.storage_service.generate_presigned_url.side_effect = lambda company_short_name, storage_key: f"https://files/{storage_key}"

        self.markdown_wiki_service = MarkdownWikiService(storage_service=self.storage_service)
        self.wiki_repo = KnowledgeWikiRepo(self.db_manager)
        self.tenant_wiki_service = TenantWikiService(
            profile_repo=self.profile_repo,
            knowledge_wiki_repo=self.wiki_repo,
            markdown_wiki_service=self.markdown_wiki_service,
            storage_service=self.storage_service,
        )
        self.memory_wiki_service = MemoryWikiService(
            tenant_wiki_service=self.tenant_wiki_service,
            markdown_wiki_service=self.markdown_wiki_service,
        )
        self.memory_repo = MemoryRepo(self.db_manager)

        self.llm_client = MagicMock()
        self.configuration_service = MagicMock()
        self.configuration_service.get_llm_configuration.return_value = ("gpt-test", {})
        self.configuration_service.get_configuration.return_value = None
        # The real runner over the mocked model, wrapped to read what each agent received.
        self.system_agent_runner = MagicMock(wraps=SystemAgentRunner(
            llm_client=self.llm_client,
            configuration_service=self.configuration_service,
        ))
        self.compiler = MemoryCompilerService(
            profile_repo=self.profile_repo,
            memory_repo=self.memory_repo,
            memory_wiki_service=self.memory_wiki_service,
            system_agent_runner=self.system_agent_runner,
            storage_service=self.storage_service,
            db_manager=self.db_manager,
            document_repo=DocumentRepo(self.db_manager),
        )

        self.trigger = MagicMock()
        self.trigger.is_async_enabled.return_value = True
        self.memory_service = MemoryService(
            profile_repo=self.profile_repo,
            memory_repo=self.memory_repo,
            memory_wiki_service=self.memory_wiki_service,
            memory_compiler_service=self.compiler,
            memory_compilation_trigger=self.trigger,
            storage_service=self.storage_service,
            util=MagicMock(normalize_base64_payload=lambda value: value.encode("utf-8") if isinstance(value, str) else value),
        )

    def _upload_bytes(self, *, company_short_name, storage_key, file_content, mime_type):
        self.storage[storage_key] = bytes(file_content)

    def _get_document_content(self, company_short_name, storage_key):
        if storage_key not in self.storage:
            raise FileNotFoundError(storage_key)
        return self.storage[storage_key]

    def _list_files(self, company_short_name, prefix, extension):
        normalized_prefix = str(prefix or "").strip().strip("/")
        return [
            {"path": key, "name": os.path.basename(key), "metadata": {}}
            for key in sorted(self.storage)
            if key.startswith(normalized_prefix) and (not extension or key.endswith(extension))
        ]

    def llm_returns(self, *outputs):
        """Each call to the model returns the next structured output."""
        self.llm_client.invoke.side_effect = [{"structured_output": output} for output in outputs]

    def agent_calls(self, agent_key: str) -> list[dict]:
        """The inputs each run of a system agent received, in order."""
        return [
            call.args[2] for call in self.system_agent_runner.run.call_args_list
            if call.args[1] == agent_key
        ]

    def save_note(self, author: str, text: str, title: str | None = None) -> dict:
        response = self.memory_service.save_capture(
            company_short_name="acme",
            user_identifier=author,
            capture_text=text,
            title=title,
            new_items=[{"item_type": "note", "content_text": text, "title": title}],
        )
        assert response["status"] == "success", response
        return response["capture"]

    def pages(self) -> list[dict]:
        return self.memory_wiki_service.list_pages("acme")

    def page(self, page_id: int) -> dict:
        return self.memory_wiki_service.get_page("acme", page_id)
