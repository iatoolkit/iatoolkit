import hashlib
import json
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
        # Per-key storage metadata. Empty by default, which makes
        # `_file_metadata_unchanged` return False and every page re-parse; tests
        # that need the unchanged-file fast path register an md5 here.
        self.file_metadata = {}

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
                    "metadata": dict(self.file_metadata.get(storage_key) or {}),
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

    def write_stable_storage(self, storage_key: str, markdown: str):
        """Writes a file that reports an md5, so a later sync takes the fast path."""
        self.write_storage(storage_key, markdown)
        self.file_metadata[storage_key] = {
            "md5_hash": hashlib.md5(markdown.encode("utf-8")).hexdigest(),
        }

    def write_access_manifest(self, root: str, pages: dict, **document):
        self.storage[f"{root}/_access-manifest.json"] = json.dumps(
            {"pages": pages, **document}
        ).encode("utf-8")

    def configure_external_wiki(self, wiki_key: str, root: str, access_control: dict | None = None):
        settings = {"authoring_mode": "external_sync"}
        if access_control is not None:
            settings["access_control"] = access_control
        return self.service.configure_wiki(
            "acme",
            wiki_key=wiki_key,
            name=f"{wiki_key.title()} Wiki",
            root_storage_key=root,
            settings=settings,
        )

    def page_access_tags(self, wiki_id: int, path: str) -> list[str]:
        return list(self.repo.get_page_by_path(wiki_id, path).access_tags or [])

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

    def test_sync_wiki_skips_unchanged_files_on_second_sync(self):
        root = "companies/acme/knowledge_wikis/eng"
        page_md = "---\ntitle: API Guide\ntags: [eng, api]\nsummary: API reference.\n---\n# API Guide\n\nEndpoints and schemas.\n"
        self.write_storage(f"{root}/api-guide.md", page_md)
        self.write_storage(f"{root}/runbook.md", "# Runbook\n\nOn-call procedures.\n")

        original_list_files = self.storage_service.list_files.side_effect

        def list_files_with_metadata(company_short_name, prefix, extension):
            rows = original_list_files(company_short_name, prefix, extension)
            for row in rows:
                row["metadata"] = {"size": 100, "last_modified": "2024-01-15T10:00:00"}
            return rows

        self.storage_service.list_files.side_effect = list_files_with_metadata

        first = self.service.sync_wiki("acme", wiki_key="eng", root_storage_key=root, name="Eng Wiki")
        assert first["status"] == "success"
        assert first["sync"]["pages_seen"] == 2
        assert first["sync"]["pages_indexed"] == 2
        assert first["sync"]["pages_skipped"] == 0

        second = self.service.sync_wiki("acme", wiki_key="eng", root_storage_key=root, name="Eng Wiki")
        assert second["status"] == "success"
        assert second["sync"]["pages_seen"] == 2
        assert second["sync"]["pages_indexed"] == 0
        assert second["sync"]["pages_skipped"] == 2

    def test_sync_wiki_reindexes_changed_file_on_second_sync(self):
        root = "companies/acme/knowledge_wikis/product"
        self.write_storage(f"{root}/intro.md", "# Intro\n\nOverview.\n")
        self.write_storage(f"{root}/guide.md", "# Guide\n\nHow-to.\n")

        original_list_files = self.storage_service.list_files.side_effect

        def list_files_with_metadata(company_short_name, prefix, extension):
            rows = original_list_files(company_short_name, prefix, extension)
            for row in rows:
                row["metadata"] = {"size": 50, "last_modified": "2024-01-15T10:00:00"}
            return rows

        self.storage_service.list_files.side_effect = list_files_with_metadata

        self.service.sync_wiki("acme", wiki_key="product", root_storage_key=root, name="Product Wiki")

        # Change one file: update content + metadata
        self.write_storage(f"{root}/guide.md", "# Guide\n\nUpdated how-to with more detail.\n")

        def list_files_with_updated_metadata(company_short_name, prefix, extension):
            rows = original_list_files(company_short_name, prefix, extension)
            for row in rows:
                path = row["path"]
                if path.endswith("guide.md"):
                    row["metadata"] = {"size": 200, "last_modified": "2024-02-01T12:00:00"}
                else:
                    row["metadata"] = {"size": 50, "last_modified": "2024-01-15T10:00:00"}
            return rows

        self.storage_service.list_files.side_effect = list_files_with_updated_metadata

        second = self.service.sync_wiki("acme", wiki_key="product", root_storage_key=root, name="Product Wiki")
        assert second["status"] == "success"
        assert second["sync"]["pages_seen"] == 2
        assert second["sync"]["pages_indexed"] == 1
        assert second["sync"]["pages_skipped"] == 1

        guide_page = self.repo.get_page_by_path(second["wiki"]["id"], "guide.md")
        assert "Updated how-to" in guide_page.body_text

    # --- access manifest (per-page visibility labels) ------------------------

    def test_sync_wiki_labels_pages_from_access_manifest(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.write_storage(f"{root}/board/comp.md", "# Compensation\n\nRestricted.\n")
        self.write_storage(f"{root}/orphan.md", "# Orphan\n\nNot in the manifest.\n")
        self.write_access_manifest(
            root,
            {
                "pricing.md": ["public", "comercial"],
                "./board/comp.md": ["board"],
                "gone.md": ["public"],
            },
            version="7",
            generated_at="2026-08-11T10:00:00",
        )
        self.configure_external_wiki("kb", root, access_control={"mode": "dry_run"})

        result = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert result["status"] == "success"
        wiki_id = result["wiki"]["id"]
        assert self.page_access_tags(wiki_id, "pricing.md") == ["comercial", "public"]
        assert self.page_access_tags(wiki_id, "board/comp.md") == ["board"]
        # No entry in the manifest is a denial, not a default.
        assert self.page_access_tags(wiki_id, "orphan.md") == []

        access = result["sync"]["metadata"]["access_control"]
        assert access["mode"] == "dry_run"
        assert access["manifest_status"] == "loaded"
        assert access["manifest_entries"] == 3
        assert access["manifest_version"] == "7"
        assert access["manifest_generated_at"] == "2026-08-11T10:00:00"
        assert access["pages_without_manifest_entry"] == 1
        assert access["pages_without_manifest_entry_sample"] == ["orphan.md"]
        assert access["manifest_entries_without_page"] == 1
        assert access["manifest_entries_without_page_sample"] == ["gone.md"]

    def test_sync_wiki_relabels_pages_whose_markdown_did_not_change(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_stable_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.write_access_manifest(root, {"pricing.md": ["board"]})
        self.configure_external_wiki("kb", root, access_control={"mode": "enforce"})
        first = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)
        assert self.page_access_tags(first["wiki"]["id"], "pricing.md") == ["board"]

        # Only the manifest changes. The markdown is byte-identical, so the sync
        # takes the unchanged-file fast path -- which still has to relabel.
        self.write_access_manifest(root, {"pricing.md": ["public"]})
        second = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert second["status"] == "success"
        assert second["sync"]["pages_skipped"] == 1
        assert second["sync"]["pages_indexed"] == 0
        assert second["sync"]["metadata"]["access_control"]["pages_relabelled"] == 1
        assert self.page_access_tags(second["wiki"]["id"], "pricing.md") == ["public"]

    def test_sync_wiki_fails_and_touches_nothing_when_required_manifest_is_gone(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.write_access_manifest(root, {"pricing.md": ["board"]})
        self.configure_external_wiki("kb", root, access_control={"mode": "enforce"})
        first = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)
        wiki_id = first["wiki"]["id"]

        self.storage.pop(f"{root}/_access-manifest.json")
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nRewritten bands.\n")
        result = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert result["status"] == "error"
        assert "_access-manifest.json" in result["error_message"]
        assert result["sync"]["status"] == "failed"
        # The corpus is untouched: labels kept, and the new markdown was not
        # indexed either, so nothing is served unlabelled.
        assert self.page_access_tags(wiki_id, "pricing.md") == ["board"]
        assert "Rewritten" not in self.repo.get_page_by_path(wiki_id, "pricing.md").body_text

    def test_sync_wiki_fails_when_required_manifest_is_invalid(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.storage[f"{root}/_access-manifest.json"] = b'{"pages": {}}'
        self.configure_external_wiki("kb", root, access_control={"mode": "enforce"})

        result = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert result["status"] == "error"
        assert "declares no pages" in result["error_message"]
        assert self.repo.get_page_by_path(result["sync"]["wiki_id"], "pricing.md") is None

    def test_sync_wiki_fails_when_manifest_maps_the_same_page_twice(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.write_access_manifest(root, {"pricing.md": ["public"], "./pricing.md": ["board"]})
        self.configure_external_wiki("kb", root, access_control={"mode": "enforce"})

        result = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert result["status"] == "error"
        assert "more than once with different labels" in result["error_message"]

    def test_sync_wiki_without_access_control_ignores_a_missing_manifest(self):
        root = "companies/acme/knowledge_wikis/sales"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")

        result = self.service.sync_wiki("acme", wiki_key="sales", root_storage_key=root)

        assert result["status"] == "success"
        assert self.page_access_tags(result["wiki"]["id"], "pricing.md") == []
        access = result["sync"]["metadata"]["access_control"]
        assert access["mode"] == "off"
        assert access["manifest_status"] == "absent"
        assert "pages_without_manifest_entry" not in access

    def test_sync_wiki_keeps_existing_labels_when_the_manifest_disappears_with_mode_off(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.write_access_manifest(root, {"pricing.md": ["board"]})
        self.configure_external_wiki("kb", root, access_control={"mode": "dry_run"})
        first = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)
        wiki_id = first["wiki"]["id"]

        self.configure_external_wiki("kb", root, access_control={"mode": "off"})
        self.storage.pop(f"{root}/_access-manifest.json")
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nRewritten bands.\n")
        second = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert second["status"] == "success"
        assert "Rewritten" in self.repo.get_page_by_path(wiki_id, "pricing.md").body_text
        # No manifest means "leave the labels alone", not "clear them".
        assert self.page_access_tags(wiki_id, "pricing.md") == ["board"]

    def test_access_labels_are_lowercased_deduplicated_and_sorted(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.write_access_manifest(
            root,
            {"pricing.md": [" Public ", "TECH", "tech", ""]},
        )
        self.configure_external_wiki("kb", root, access_control={"mode": "enforce"})

        result = self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        assert self.page_access_tags(result["wiki"]["id"], "pricing.md") == ["public", "tech"]

    def test_serialized_pages_never_carry_access_labels(self):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/pricing.md", "---\ntags: [sales]\n---\n# Pricing\n\nBands.\n")
        self.write_access_manifest(root, {"pricing.md": ["board"]})
        # Labels are synced but not enforced: this is about what the payload
        # carries, and enforcement is covered by its own tests.
        self.configure_external_wiki("kb", root, access_control={"mode": "off"})
        self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

        page = self.service.get_page("acme", wiki_key="kb", path="pricing.md")["page"]
        results = self.service.search_pages("acme", wiki_key="kb", query="pricing")["results"]
        index_entry = self.service.get_index("acme", wiki_key="kb")["entries"][0]

        # Editorial tags are part of the payload; visibility labels never are.
        assert page["tags"] == ["sales"]
        assert "access_tags" not in page
        assert "access_tags" not in results[0]
        assert "access_tags" not in index_entry
        assert "board" not in json.dumps(results)

    # --- the filter: labels of the page against labels of the reader ---------

    def setup_labelled_wiki(self, mode: str = "enforce"):
        root = "companies/acme/knowledge_wikis/kb"
        self.write_storage(f"{root}/public/pricing.md", "---\ntitle: Pricing\n---\n# Pricing\n\nBands.\n")
        self.write_storage(f"{root}/board/comp.md", "---\ntitle: Compensation\n---\n# Compensation\n\nPricing of people.\n")
        self.write_storage(f"{root}/loose.md", "---\ntitle: Loose\n---\n# Loose\n\nPricing leftovers.\n")
        self.write_storage(f"{root}/index.md", "---\ntitle: KB Home\n---\n# KB Home\n\nSee [Comp](board/comp.md).\n")
        self.write_access_manifest(
            root,
            {"public/pricing.md": ["public"], "board/comp.md": ["board"]},
        )
        self.configure_external_wiki("kb", root, access_control={"mode": mode})
        return self.service.sync_wiki("acme", wiki_key="kb", root_storage_key=root)

    def resolver(self, labels):
        return lambda company_short_name, user_identifier: labels

    def teardown_method(self):
        TenantWikiService.clear_access_label_resolver()

    def test_enforce_serves_only_the_pages_whose_labels_the_reader_holds(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver({"public"}))

        allowed = self.service.get_page("acme", wiki_key="kb", path="public/pricing.md", user_identifier="dcanales")
        denied = self.service.get_page("acme", wiki_key="kb", path="board/comp.md", user_identifier="dcanales")
        unlabelled = self.service.get_page("acme", wiki_key="kb", path="loose.md", user_identifier="dcanales")

        assert allowed["status"] == "success"
        # A denied page is indistinguishable from one that does not exist.
        assert denied == {"status": "error", "error_message": "page not found"}
        assert unlabelled["status"] == "error"

    def test_enforce_denies_everything_without_an_identity(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver({"public", "board"}))

        page = self.service.get_page("acme", wiki_key="kb", path="public/pricing.md")

        assert page["status"] == "error"

    def test_enforce_denies_everything_when_labels_cannot_be_resolved(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver(None))

        page = self.service.get_page("acme", wiki_key="kb", path="public/pricing.md", user_identifier="dcanales")
        results = self.service.search_pages("acme", wiki_key="kb", query="pricing", user_identifier="dcanales")

        assert page["status"] == "error"
        assert results["results"] == []

    def test_enforce_denies_everything_when_no_resolver_is_registered(self):
        self.setup_labelled_wiki()

        page = self.service.get_page("acme", wiki_key="kb", path="public/pricing.md", user_identifier="dcanales")

        assert page["status"] == "error"

    def test_a_resolver_that_raises_denies_instead_of_opening(self):
        self.setup_labelled_wiki()

        def broken(company_short_name, user_identifier):
            raise RuntimeError("access control service is down")

        TenantWikiService.register_access_label_resolver(broken)
        page = self.service.get_page("acme", wiki_key="kb", path="public/pricing.md", user_identifier="dcanales")

        assert page["status"] == "error"

    def test_search_hides_the_existence_of_denied_pages(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver({"public"}))

        results = self.service.search_pages("acme", wiki_key="kb", query="pricing", user_identifier="dcanales")

        assert [item["path"] for item in results["results"]] == ["public/pricing.md"]
        # Neither the title, the path nor a snippet of a denied page leaks.
        assert "Compensation" not in json.dumps(results)
        assert "board" not in json.dumps(results)

    def test_the_readers_home_page_lists_only_what_they_may_read(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver({"public"}))

        home = self.service.get_page("acme", wiki_key="kb", path="/", user_identifier="dcanales")

        assert home["status"] == "success"
        assert "public/pricing.md" in home["page"]["markdown"]
        # The authored index.md links to a denied page, so it is replaced by a
        # generated one listing only the visible pages.
        assert "board/comp.md" not in home["page"]["markdown"]

    def test_dry_run_serves_everything_and_only_reports(self, caplog):
        self.setup_labelled_wiki(mode="dry_run")
        TenantWikiService.register_access_label_resolver(self.resolver({"public"}))

        with caplog.at_level("INFO"):
            denied = self.service.get_page("acme", wiki_key="kb", path="board/comp.md", user_identifier="dcanales")
            results = self.service.search_pages("acme", wiki_key="kb", query="pricing", user_identifier="dcanales")

        assert denied["status"] == "success"
        assert {item["path"] for item in results["results"]} == {
            "public/pricing.md", "board/comp.md", "loose.md",
        }
        assert "would deny (dry_run)" in caplog.text

    def test_a_wiki_with_access_control_off_is_untouched(self):
        self.setup_labelled_wiki(mode="off")
        TenantWikiService.register_access_label_resolver(self.resolver(None))

        page = self.service.get_page("acme", wiki_key="kb", path="board/comp.md", user_identifier="dcanales")
        results = self.service.search_pages("acme", wiki_key="kb", query="pricing", user_identifier="dcanales")

        assert page["status"] == "success"
        assert len(results["results"]) == 3

    def test_labels_compose_with_the_callers_own_filter(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver({"public", "board"}))

        # The reader holds both labels, but the policy filter still excludes board/.
        denied = self.service.get_page(
            "acme",
            wiki_key="kb",
            path="board/comp.md",
            user_identifier="dcanales",
            visibility_filter=lambda path: not path.startswith("board/"),
        )
        allowed = self.service.get_page(
            "acme",
            wiki_key="kb",
            path="public/pricing.md",
            user_identifier="dcanales",
            visibility_filter=lambda path: not path.startswith("board/"),
        )

        assert denied["status"] == "error"
        assert allowed["status"] == "success"

    def test_the_admin_index_is_never_filtered_by_labels(self):
        result = self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver(None))

        index = self.service.get_index("acme", wiki_key="kb")

        # The operator's view of the wiki: everything, so the panel does not go
        # blank for a wiki under enforcement.
        assert index["status"] == "success"
        assert len(index["entries"]) == 3
        assert result["wiki"]["settings"]["access_control"]["mode"] == "enforce"

    def test_the_visibility_report_counts_what_a_reader_would_see(self):
        self.setup_labelled_wiki()

        report = self.service.access_visibility_report("acme", wiki_key="kb", user_labels={"public"})
        blind = self.service.access_visibility_report("acme", wiki_key="kb", user_labels=None)

        assert report["mode"] == "enforce"
        assert (report["pages"], report["visible"], report["denied"]) == (3, 1, 2)
        assert report["unlabelled"] == 1
        assert report["visible_sample"] == ["public/pricing.md"]
        assert (blind["visible"], blind["denied"]) == (0, 3)

    def test_the_admin_page_viewer_bypasses_labels_explicitly(self):
        self.setup_labelled_wiki()
        TenantWikiService.register_access_label_resolver(self.resolver(None))

        as_reader = self.service.get_page("acme", wiki_key="kb", path="board/comp.md", user_identifier="dcanales")
        as_owner = self.service.get_page(
            "acme",
            wiki_key="kb",
            path="board/comp.md",
            bypass_access_control=True,
        )

        assert as_reader["status"] == "error"
        assert as_owner["status"] == "success"
        assert "Pricing of people" in as_owner["page"]["markdown"]

    # --- switching the mode --------------------------------------------------

    def test_setting_the_mode_touches_nothing_else(self):
        self.setup_labelled_wiki(mode="off")
        before = self.repo.get_wiki_by_key(self.company.id, "kb")
        name_before, root_before = before.name, before.root_storage_key

        result = self.service.set_access_control_mode("acme", wiki_key="kb", mode="dry_run")

        assert result["status"] == "success"
        assert (result["previous_mode"], result["mode"]) == ("off", "dry_run")
        assert (result["pages"], result["labelled"], result["unlabelled"]) == (3, 2, 1)
        assert result["manifest_status"] == "loaded"
        after = self.repo.get_wiki_by_key(self.company.id, "kb")
        # configure_wiki would have renamed it and reset the prefix; this does not.
        assert (after.name, after.root_storage_key) == (name_before, root_before)
        assert after.settings["authoring_mode"] == "external_sync"
        assert after.settings["access_control"]["mode"] == "dry_run"

    def test_the_new_mode_actually_takes_effect(self):
        self.setup_labelled_wiki(mode="off")
        TenantWikiService.register_access_label_resolver(self.resolver({"public"}))

        served = self.service.get_page("acme", wiki_key="kb", path="board/comp.md", user_identifier="dcanales")
        self.service.set_access_control_mode("acme", wiki_key="kb", mode="enforce")
        denied = self.service.get_page("acme", wiki_key="kb", path="board/comp.md", user_identifier="dcanales")

        assert served["status"] == "success"
        assert denied["status"] == "error"

    def test_an_unknown_mode_is_refused_rather_than_read_as_off(self):
        self.setup_labelled_wiki(mode="enforce")

        result = self.service.set_access_control_mode("acme", wiki_key="kb", mode="Enforce!")

        assert result["status"] == "error"
        assert "must be one of" in result["error_message"]
        assert self.repo.get_wiki_by_key(self.company.id, "kb").settings["access_control"]["mode"] == "enforce"

    def test_enforcing_a_wiki_with_no_labels_is_refused(self):
        root = "companies/acme/knowledge_wikis/plain"
        self.write_storage(f"{root}/pricing.md", "# Pricing\n\nBands.\n")
        self.configure_external_wiki("plain", root)
        self.service.sync_wiki("acme", wiki_key="plain", root_storage_key=root)

        refused = self.service.set_access_control_mode("acme", wiki_key="plain", mode="enforce")
        forced = self.service.set_access_control_mode(
            "acme",
            wiki_key="plain",
            mode="enforce",
            allow_dark=True,
        )

        assert refused["status"] == "error"
        assert "hide all of it" in refused["error_message"]
        assert forced["status"] == "success"

    def test_raising_the_mode_reports_a_manifest_that_would_break_the_next_sync(self):
        self.setup_labelled_wiki(mode="off")
        self.storage.pop("companies/acme/knowledge_wikis/kb/_access-manifest.json")

        result = self.service.set_access_control_mode("acme", wiki_key="kb", mode="dry_run")

        assert result["status"] == "success"
        assert "the next sync will abort" in result["manifest_status"]

    def test_setting_the_mode_on_a_missing_wiki_errors(self):
        assert self.service.set_access_control_mode("acme", wiki_key="ghost", mode="off") == {
            "status": "error",
            "error_message": "wiki not found",
        }

    def test_the_admin_index_reports_the_access_control_state(self):
        self.setup_labelled_wiki(mode="dry_run")

        access = self.service.get_index("acme", wiki_key="kb")["access_control"]

        assert access["mode"] == "dry_run"
        assert access["manifest"] == "_access-manifest.json"
        assert access["modes"] == ["off", "dry_run", "enforce"]
        assert (access["pages"], access["labelled"], access["unlabelled"]) == (3, 2, 1)

    def test_saving_the_wiki_form_does_not_turn_access_control_off(self):
        self.setup_labelled_wiki(mode="enforce")

        # What the admin form sends when someone edits the name: settings without
        # access_control. Dropping the mode here would silently unprotect the wiki.
        self.service.configure_wiki(
            "acme",
            wiki_key="kb",
            name="KB renamed",
            root_storage_key="companies/acme/knowledge_wikis/kb",
            settings={"publication": "storage", "authoring_mode": "external_sync"},
        )

        wiki = self.repo.get_wiki_by_key(self.company.id, "kb")
        assert wiki.name == "KB renamed"
        assert wiki.settings["access_control"]["mode"] == "enforce"
        assert self.service.wiki_access_control(wiki) == {
            "mode": "enforce",
            "manifest": "_access-manifest.json",
        }
