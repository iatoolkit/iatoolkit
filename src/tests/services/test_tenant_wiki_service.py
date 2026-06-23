import os
from unittest.mock import MagicMock

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo
from iatoolkit.repositories.models import Company
from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.tenant_wiki_service import TenantWikiService


class TestTenantWikiService:
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
        self.storage = {}

        def upload_bytes(*, company_short_name, storage_key, file_content, mime_type):
            self.storage[storage_key] = bytes(file_content)

        def get_document_content(company_short_name, storage_key):
            if storage_key not in self.storage:
                raise FileNotFoundError(storage_key)
            return self.storage[storage_key]

        def list_files(company_short_name, prefix, extension):
            rows = []
            normalized_prefix = str(prefix or "").strip().strip("/")
            for storage_key in sorted(self.storage.keys()):
                if normalized_prefix and not storage_key.startswith(normalized_prefix):
                    continue
                if extension and not storage_key.endswith(extension):
                    continue
                rows.append({
                    "path": storage_key,
                    "name": os.path.basename(storage_key),
                    "metadata": {},
                })
            return rows

        def delete_file(company_short_name, storage_key):
            self.storage.pop(storage_key, None)

        self.storage_service.upload_bytes.side_effect = upload_bytes
        self.storage_service.get_document_content.side_effect = get_document_content
        self.storage_service.list_files.side_effect = list_files
        self.storage_service.delete_file.side_effect = delete_file

        self.markdown_wiki_service = MarkdownWikiService(storage_service=self.storage_service)
        self.repo = KnowledgeWikiRepo(self.db_manager)
        self.service = TenantWikiService(
            profile_repo=self.profile_repo,
            knowledge_wiki_repo=self.repo,
            markdown_wiki_service=self.markdown_wiki_service,
            storage_service=self.storage_service,
        )

    def write_storage(self, storage_key: str, markdown: str):
        self.storage[storage_key] = markdown.encode("utf-8")

    def read_storage(self, storage_key: str) -> str:
        return self.storage[storage_key].decode("utf-8")

    def test_sync_wiki_imports_markdown_pages_and_generates_indexes(self):
        root = "companies/acme/knowledge_wikis/sales"
        self.write_storage(
            f"{root}/pricing.md",
            "---\ntitle: Pricing\ntags: [sales, pricing]\nsummary: Pricing rules.\n---\n# Pricing\n\nUse approved bands.\n",
        )
        self.write_storage(
            f"{root}/playbooks/discovery.md",
            "# Discovery\n\nAsk about urgency and stakeholders.\n",
        )

        result = self.service.sync_wiki(
            "acme",
            wiki_key="sales",
            root_storage_key=root,
            name="Sales Wiki",
        )

        assert result["status"] == "success"
        assert result["wiki"]["authoring_mode"] == "external_sync"
        assert result["sync"]["pages_seen"] == 2
        assert result["sync"]["pages_indexed"] == 2
        pages = self.repo.list_pages(result["wiki"]["id"])
        assert [page.path for page in pages] == ["playbooks/discovery.md", "pricing.md"]
        pricing = self.repo.get_page_by_path(result["wiki"]["id"], "pricing.md")
        assert pricing.title == "Pricing"
        assert pricing.tags == ["sales", "pricing"]
        assert f"{root}/index.md" in self.storage
        assert f"{root}/.iatoolkit/index.md" in self.storage
        assert "[Pricing](pricing.md)" in self.read_storage(f"{root}/index.md")

    def test_get_index_and_page_return_published_content(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(
            f"{root}/incident-response.md",
            "---\ntitle: Incident Response\nowner: ops\n---\n# Incident Response\n\nEscalate by severity.\n",
        )

        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        index = self.service.get_index("acme", wiki_key="ops")
        root_page = self.service.get_page("acme", wiki_key="ops", path="/")
        page = self.service.get_page("acme", wiki_key="ops", path="incident-response.md")

        assert index["status"] == "success"
        assert index["entries"][0]["title"] == "Incident Response"
        assert "Incident Response" in index["markdown"]
        assert "Incident Response" in index["generated_markdown"]
        assert self.markdown_wiki_service.parse_generic_index(index["generated_markdown"])["entries"][0]["path"] == "incident-response.md"
        assert index["index_path"] == "/"
        assert index["index_source_path"] == "index.md"
        assert root_page["status"] == "success"
        assert root_page["page"]["path"] == "/"
        assert "Incident Response" in root_page["page"]["markdown"]
        assert page["status"] == "success"
        assert page["page"]["frontmatter"]["owner"] == "ops"
        assert page["page"]["body_text"] == "# Incident Response\n\nEscalate by severity."

    def test_sync_wiki_serializes_frontmatter_dates_before_persisting(self):
        root = "companies/acme/knowledge_wikis/legal"
        self.write_storage(
            f"{root}/ai-providers.md",
            "---\n"
            "title: Legal AI Providers\n"
            "review_date: 2026-06-17\n"
            "milestones:\n"
            "  - name: contract-review\n"
            "    due_on: 2026-06-20\n"
            "---\n"
            "# Legal AI Providers\n\nApproved vendor list.\n",
        )

        result = self.service.sync_wiki("acme", wiki_key="legal", root_storage_key=root, name="Legal Wiki")

        assert result["status"] == "success"
        page = self.repo.get_page_by_path(result["wiki"]["id"], "ai-providers.md")
        assert page is not None
        assert page.source_meta["frontmatter"]["review_date"] == "2026-06-17"
        assert page.source_meta["frontmatter"]["milestones"][0]["due_on"] == "2026-06-20"

    def test_get_index_uses_authored_root_when_index_md_exists(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(
            f"{root}/incident-response.md",
            "---\ntitle: Incident Response\nsummary: Escalation guide.\n---\n# Incident Response\n\nEscalate by severity.\n",
        )
        self.write_storage(
            f"{root}/index.md",
            "---\ntitle: Ops Home\nowner: ops\n---\n# Ops Home\n\nStart here before opening a page.\n",
        )

        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")
        index = self.service.get_index("acme", wiki_key="ops")
        root_page = self.service.get_page("acme", wiki_key="ops", path="/")
        index_page = self.service.get_page("acme", wiki_key="ops", path="index.md")
        parsed = self.markdown_wiki_service.parse_generic_index(index["generated_markdown"])

        assert index["status"] == "success"
        assert index["entries"][0]["path"] == "incident-response.md"
        assert "Start here before opening a page." in index["mcp_markdown"]
        assert index["index_path"] == "/"
        assert index["index_source_path"] == "index.md"
        assert "- [Incident Response](incident-response.md) - Escalation guide." in index["generated_markdown"]
        assert parsed["entries"][0]["path"] == "incident-response.md"
        assert root_page["page"]["path"] == "/"
        assert "Start here before opening a page." in root_page["page"]["markdown"]
        assert index_page["page"]["path"] == "index.md"
        assert index_page["page"]["title"] == "Ops Home"
        assert "Start here before opening a page." in index_page["page"]["markdown"]

    def test_get_page_root_uses_filtered_generated_index_when_visibility_is_restricted(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(
            f"{root}/incident-response.md",
            "---\ntitle: Incident Response\nsummary: Escalation guide.\n---\n# Incident Response\n\nEscalate by severity.\n",
        )
        self.write_storage(
            f"{root}/board/compensation.md",
            "---\ntitle: Compensation\nsummary: Board-only.\n---\n# Compensation\n\nRestricted.\n",
        )
        self.write_storage(
            f"{root}/index.md",
            "---\ntitle: Ops Home\n---\n# Ops Home\n\nSee [Compensation](board/compensation.md).\n",
        )

        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        root_page = self.service.get_page(
            "acme",
            wiki_key="ops",
            path="/",
            visibility_filter=lambda path: not path.startswith("board/"),
        )

        assert root_page["status"] == "success"
        assert "board/compensation.md" not in root_page["page"]["markdown"]
        assert "incident-response.md" in root_page["page"]["markdown"]
        assert root_page["page"]["source_storage_key"].endswith("/.iatoolkit/index.md")

    def test_configure_managed_wiki_creates_default_root_index(self):
        result = self.service.configure_wiki(
            "acme",
            wiki_key="handbook",
            name="Handbook",
            description="Company handbook",
            settings={"authoring_mode": "managed"},
        )

        assert result["status"] == "success"
        assert result["wiki"]["authoring_mode"] == "managed"
        assert result["wiki"]["editing_enabled"] is True
        assert self.read_storage("companies/acme/knowledge_wikis/handbook/index.md").startswith("---")

    def test_managed_page_crud_updates_storage_and_home_index(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="handbook",
            name="Handbook",
            description="Company handbook",
            settings={"authoring_mode": "managed"},
        )

        created = self.service.create_page(
            "acme",
            wiki_key="handbook",
            path="policies/remote-work",
            title="Remote Work",
        )
        assert created["status"] == "success"
        assert created["page"]["path"] == "policies/remote-work.md"
        assert "[Remote Work](policies/remote-work.md)" in self.read_storage(
            "companies/acme/knowledge_wikis/handbook/index.md"
        )

        saved = self.service.save_page(
            "acme",
            wiki_key="handbook",
            path="policies/remote-work.md",
            markdown="---\ntitle: Remote Work\nsummary: Rules\n---\n# Remote Work\n\nPolicy.\n",
        )
        assert saved["status"] == "success"
        assert "Policy." in saved["page"]["markdown"]

        home_saved = self.service.save_page(
            "acme",
            wiki_key="handbook",
            path="index.md",
            markdown="---\ntitle: Handbook Home\n---\n# Handbook Home\n\nStart here.\n",
        )
        assert home_saved["status"] == "success"
        assert "Handbook Home" in home_saved["page"]["markdown"]

        deleted = self.service.delete_page(
            "acme",
            wiki_key="handbook",
            path="policies/remote-work.md",
        )
        assert deleted["status"] == "success"
        assert "companies/acme/knowledge_wikis/handbook/policies/remote-work.md" not in self.storage

    def test_managed_create_page_normalizes_path_and_persists_record(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="playbook",
            name="Playbook",
            settings={"authoring_mode": "managed"},
        )

        result = self.service.create_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery",
            title="Discovery Call",
        )

        assert result["status"] == "success"
        assert result["page"]["path"] == "sales/discovery.md"
        assert self.repo.get_page_by_path(
            self.repo.get_wiki_by_key(self.company.id, "playbook").id,
            "sales/discovery.md",
        )
        assert "companies/acme/knowledge_wikis/playbook/sales/discovery.md" in self.storage

    def test_managed_create_page_rejects_unsafe_path_segments(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="playbook",
            name="Playbook",
            settings={"authoring_mode": "managed"},
        )

        result = self.service.create_page(
            "acme",
            wiki_key="playbook",
            path="sales/../secret.md",
            title="Secret",
        )

        assert result["status"] == "error"
        assert result["error_message"] == "page path is required"

    def test_managed_home_page_becomes_manual_after_edit(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="playbook",
            name="Playbook",
            settings={"authoring_mode": "managed"},
        )

        save_result = self.service.save_page(
            "acme",
            wiki_key="playbook",
            path="index.md",
            markdown="---\ntitle: Playbook Home\n---\n# Playbook Home\n\nCustom intro.\n",
        )
        create_result = self.service.create_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            title="Discovery Call",
        )

        assert save_result["status"] == "success"
        assert create_result["status"] == "success"
        home_markdown = self.read_storage("companies/acme/knowledge_wikis/playbook/index.md")
        assert "Custom intro." in home_markdown
        assert "sales/discovery.md" not in home_markdown
        assert "iatoolkit_generated: false" in home_markdown

    def test_managed_delete_page_removes_record_and_storage_file(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="playbook",
            name="Playbook",
            settings={"authoring_mode": "managed"},
        )
        self.service.create_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            title="Discovery Call",
        )

        result = self.service.delete_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
        )

        wiki = self.repo.get_wiki_by_key(self.company.id, "playbook")
        assert result["status"] == "success"
        assert self.repo.get_page_by_path(wiki.id, "sales/discovery.md") is None
        assert "companies/acme/knowledge_wikis/playbook/sales/discovery.md" not in self.storage

    def test_managed_page_crud_records_revisions(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="playbook",
            name="Playbook",
            settings={"authoring_mode": "managed"},
        )
        self.service.create_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            title="Discovery Call",
            edited_by="editor@acme.com",
        )
        self.service.save_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            markdown="---\ntitle: Discovery Call\nsummary: Updated\n---\n# Discovery Call\n\nUpdated.\n",
            edited_by="editor@acme.com",
        )
        self.service.delete_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            edited_by="editor@acme.com",
        )

        wiki = self.repo.get_wiki_by_key(self.company.id, "playbook")
        revisions = self.repo.list_page_revisions(wiki.id, path="sales/discovery.md")

        assert [revision.action for revision in revisions] == ["delete", "update", "create"]
        assert {revision.edited_by for revision in revisions} == {"editor@acme.com"}
        assert all(revision.checksum for revision in revisions)
        assert "Updated." in revisions[1].markdown

    def test_managed_move_page_updates_storage_record_and_revision(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="playbook",
            name="Playbook",
            settings={"authoring_mode": "managed"},
        )
        self.service.create_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            title="Discovery Call",
        )
        self.service.save_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            markdown="---\ntitle: Discovery Call\nsummary: Updated\n---\n# Discovery Call\n\nUpdated.\n",
            edited_by="editor@acme.com",
        )

        result = self.service.move_page(
            "acme",
            wiki_key="playbook",
            path="sales/discovery.md",
            new_path="revenue/discovery.md",
            title="Revenue Discovery",
            edited_by="editor@acme.com",
        )

        wiki = self.repo.get_wiki_by_key(self.company.id, "playbook")
        page = self.repo.get_page_by_path(wiki.id, "revenue/discovery.md")
        revisions = self.service.list_page_revisions(
            "acme",
            wiki_key="playbook",
            path="revenue/discovery.md",
        )["revisions"]

        assert result["status"] == "success"
        assert result["page"]["path"] == "revenue/discovery.md"
        assert page.title == "Revenue Discovery"
        assert "companies/acme/knowledge_wikis/playbook/sales/discovery.md" not in self.storage
        assert "companies/acme/knowledge_wikis/playbook/revenue/discovery.md" in self.storage
        assert [revision["action"] for revision in revisions] == ["move", "update", "create"]
        assert revisions[0]["previous_path"] == "sales/discovery.md"
        assert revisions[0]["edited_by"] == "editor@acme.com"

    def test_external_wiki_rejects_manual_page_edits(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(f"{root}/runbook.md", "# Runbook\n\nEscalation path.\n")
        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        result = self.service.create_page(
            "acme",
            wiki_key="ops",
            path="new-page.md",
            title="New Page",
        )

        assert result["status"] == "error"
        assert "read-only" in result["error_message"]

    def test_managed_wiki_rejects_storage_refresh(self):
        self.service.configure_wiki(
            "acme",
            wiki_key="handbook",
            name="Handbook",
            settings={"authoring_mode": "managed"},
        )

        result = self.service.sync_wiki(
            "acme",
            wiki_key="handbook",
            root_storage_key="companies/acme/knowledge_wikis/handbook",
        )

        assert result["status"] == "error"
        assert "managed in the GUI" in result["error_message"]

    def test_search_pages_ranks_matching_wiki_content(self):
        root = "companies/acme/knowledge_wikis/sales"
        self.write_storage(
            f"{root}/pricing.md",
            "---\ntitle: Discount Policy\ntags: [pricing]\nsummary: Enterprise discount approvals.\n---\n# Discount Policy\n\nFinance approval is required.\n",
        )
        self.write_storage(
            f"{root}/handoff.md",
            "---\ntitle: Sales Handoff\ntags: [sales]\n---\n# Sales Handoff\n\nSend context to customer success.\n",
        )
        self.service.sync_wiki("acme", wiki_key="sales", root_storage_key=root, name="Sales Wiki")

        result = self.service.search_pages("acme", wiki_key="sales", query="enterprise discount", limit=2)

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["results"][0]["path"] == "pricing.md"
        assert result["results"][0]["wiki_key"] == "sales"

    def test_search_pages_can_be_scoped_to_allowed_wikis(self):
        sales_root = "companies/acme/knowledge_wikis/sales"
        ops_root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(f"{sales_root}/pricing.md", "# Pricing\n\nEnterprise discount approvals.\n")
        self.write_storage(f"{ops_root}/runbook.md", "# Runbook\n\nIncident escalation path.\n")

        self.service.sync_wiki("acme", wiki_key="sales", root_storage_key=sales_root, name="Sales Wiki")
        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=ops_root, name="Ops Wiki")

        result = self.service.search_pages(
            "acme",
            query="incident escalation",
            allowed_wiki_keys=["ops"],
            limit=5,
        )

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["results"][0]["wiki_key"] == "ops"

    def test_search_pages_respects_visibility_filter(self):
        root = "companies/acme/knowledge_wikis/company"
        self.write_storage(f"{root}/tech/roadmap.md", "# Roadmap\n\nTech plan.\n")
        self.write_storage(f"{root}/public/intro.md", "# Intro\n\nShared overview.\n")

        self.service.sync_wiki("acme", wiki_key="company", root_storage_key=root, name="Company Wiki")

        result = self.service.search_pages(
            "acme",
            wiki_key="company",
            query="plan overview",
            visibility_filter=lambda path: not path.startswith("tech/"),
            limit=5,
        )

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["results"][0]["path"] == "public/intro.md"

    def test_search_pages_rejects_unpublished_wiki_scope(self):
        result = self.service.search_pages(
            "acme",
            wiki_key="sales",
            query="discount policy",
            allowed_wiki_keys=["ops"],
            limit=5,
        )

        assert result["status"] == "error"
        assert result["error_message"] == "wiki not exposed to MCP"
        assert result["results"] == []

    def test_get_page_rejects_unpublished_wiki_scope(self):
        result = self.service.get_page(
            "acme",
            wiki_key="sales",
            path="pricing.md",
            allowed_wiki_keys=["ops"],
        )

        assert result["status"] == "error"
        assert result["error_message"] == "wiki not exposed to MCP"

    def test_lint_reports_missing_metadata_and_broken_internal_links(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(
            f"{root}/runbook.md",
            "# Runbook\n\nFollow [[missing page]] and [legacy](legacy.md).\n",
        )
        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        result = self.service.lint_wikis("acme", wiki_key="ops")

        assert result["status"] == "success"
        issue_types = {issue["issue_type"] for issue in result["issues"]}
        assert "missing_tags" in issue_types
        assert "broken_internal_link" in issue_types

    def test_lint_resolves_relative_markdown_links(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(f"{root}/docs/a.md", "# A\n\nSee [B](b.md).\n")
        self.write_storage(f"{root}/docs/b.md", "# B\n\nTarget.\n")
        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        result = self.service.lint_wikis("acme", wiki_key="ops")

        broken = [
            issue for issue in result["issues"]
            if issue["issue_type"] == "broken_internal_link"
        ]
        assert broken == []

    def test_lint_resolves_parent_relative_markdown_links(self):
        root = "companies/acme/knowledge_wikis/ops"
        self.write_storage(f"{root}/README.md", "# Home\n\nTarget.\n")
        self.write_storage(f"{root}/docs/a.md", "# A\n\nSee [Home](../README.md).\n")
        self.service.sync_wiki("acme", wiki_key="ops", root_storage_key=root, name="Ops Wiki")

        result = self.service.lint_wikis("acme", wiki_key="ops")

        broken = [
            issue for issue in result["issues"]
            if issue["issue_type"] == "broken_internal_link"
        ]
        assert broken == []

    def test_delete_wiki_removes_indexed_records_without_touching_source_markdown(self):
        root = "companies/acme/knowledge_wikis/sales"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nApproved bands.\n")

        sync = self.service.sync_wiki("acme", wiki_key="sales", root_storage_key=root, name="Sales Wiki")
        result = self.service.delete_wiki("acme", wiki_key="sales")

        assert sync["status"] == "success"
        assert result["status"] == "success"
        assert self.repo.list_wikis(self.company.id) == []
        assert self.repo.list_pages(sync["wiki"]["id"]) == []
        assert f"{root}/pricing.md" in self.storage
        assert f"{root}/index.md" in self.storage
        assert f"{root}/.iatoolkit/index.md" not in self.storage
