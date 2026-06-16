from unittest.mock import MagicMock

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo
from iatoolkit.repositories.models import Company
from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.tenant_knowledge_wiki_service import TenantKnowledgeWikiService


class TestTenantKnowledgeWikiService:
    def setup_method(self):
        self.db_manager = DatabaseManager("sqlite:///:memory:")
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.company = Company(name="Acme", short_name="acme")
        self.session.add(self.company)
        self.session.commit()

        self.profile_repo = MagicMock()
        self.profile_repo.get_company_by_short_name.return_value = self.company
        self.storage_service = MagicMock(spec=StorageService)
        self.markdown_wiki_service = MarkdownWikiService(storage_service=self.storage_service)
        self.repo = KnowledgeWikiRepo(self.db_manager)
        self.service = TenantKnowledgeWikiService(
            profile_repo=self.profile_repo,
            knowledge_wiki_repo=self.repo,
            markdown_wiki_service=self.markdown_wiki_service,
            storage_service=self.storage_service,
        )

    def test_sync_wiki_imports_markdown_pages_and_generates_index(self):
        root = "companies/acme/knowledge_wikis/sales"
        self.storage_service.list_files.return_value = [
            {"path": f"{root}/pricing.md", "name": "pricing.md", "metadata": {"size": 120}},
            {"path": f"{root}/playbooks/discovery.md", "name": "discovery.md", "metadata": {}},
            {"path": f"{root}/index.md", "name": "index.md", "metadata": {}},
            {"path": f"{root}/.iatoolkit/index.md", "name": "index.md", "metadata": {}},
        ]

        def content_for(company_short_name, storage_key):
            if storage_key.endswith("pricing.md"):
                return b"---\ntitle: Pricing\ntags: [sales, pricing]\nsummary: Pricing rules.\n---\n# Pricing\n\nUse approved bands."
            if storage_key.endswith("discovery.md"):
                return b"# Discovery\n\nAsk about urgency and stakeholders."
            raise AssertionError(f"unexpected storage key {storage_key}")

        self.storage_service.get_document_content.side_effect = content_for

        result = self.service.sync_wiki(
            "acme",
            wiki_key="sales",
            root_storage_key=root,
            name="Sales Wiki",
        )

        assert result["status"] == "success"
        assert result["sync"]["pages_seen"] == 2
        assert result["sync"]["pages_indexed"] == 2
        pages = self.repo.list_pages(result["wiki"]["id"])
        assert [page.path for page in pages] == ["playbooks/discovery.md", "pricing.md"]
        pricing = self.repo.get_page_by_path(result["wiki"]["id"], "pricing.md")
        assert pricing.title == "Pricing"
        assert pricing.tags == ["sales", "pricing"]
        self.storage_service.upload_bytes.assert_called_once()
        assert self.storage_service.upload_bytes.call_args.kwargs["storage_key"] == f"{root}/.iatoolkit/index.md"

    def test_get_index_and_page_return_published_content(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.storage_service.list_files.return_value = [
            {"path": f"{root}/incident-response.md", "name": "incident-response.md", "metadata": {}},
        ]
        markdown = b"---\ntitle: Incident Response\nowner: ops\n---\n# Incident Response\n\nEscalate by severity."
        self.storage_service.get_document_content.return_value = markdown

        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        index = self.service.get_index("acme", wiki_key="ops")
        page = self.service.get_page("acme", wiki_key="ops", path="incident-response.md")

        assert index["status"] == "success"
        assert index["entries"][0]["title"] == "Incident Response"
        assert "Incident Response" in index["markdown"]
        assert page["status"] == "success"
        assert page["page"]["frontmatter"]["owner"] == "ops"
        assert page["page"]["body_text"] == "# Incident Response\n\nEscalate by severity."

    def test_search_pages_ranks_matching_wiki_content(self):
        root = "companies/acme/knowledge_wikis/sales"
        self.storage_service.list_files.return_value = [
            {"path": f"{root}/pricing.md", "name": "pricing.md", "metadata": {}},
            {"path": f"{root}/handoff.md", "name": "handoff.md", "metadata": {}},
        ]

        def content_for(company_short_name, storage_key):
            if storage_key.endswith("pricing.md"):
                return b"---\ntitle: Discount Policy\ntags: [pricing]\nsummary: Enterprise discount approvals.\n---\n# Discount Policy\n\nFinance approval is required."
            return b"---\ntitle: Sales Handoff\ntags: [sales]\n---\n# Sales Handoff\n\nSend context to customer success."

        self.storage_service.get_document_content.side_effect = content_for
        self.service.sync_wiki("acme", wiki_key="sales", root_storage_key=root, name="Sales Wiki")

        result = self.service.search_pages("acme", wiki_key="sales", query="enterprise discount", limit=2)

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["results"][0]["path"] == "pricing.md"
        assert result["results"][0]["wiki_key"] == "sales"

    def test_lint_reports_missing_metadata_and_broken_internal_links(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.storage_service.list_files.return_value = [
            {"path": f"{root}/runbook.md", "name": "runbook.md", "metadata": {}},
        ]
        self.storage_service.get_document_content.return_value = (
            b"# Runbook\n\nFollow [[missing page]] and [legacy](legacy.md)."
        )
        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        result = self.service.lint_wikis("acme", wiki_key="ops")

        assert result["status"] == "success"
        issue_types = {issue["issue_type"] for issue in result["issues"]}
        assert "missing_tags" in issue_types
        assert "broken_internal_link" in issue_types
