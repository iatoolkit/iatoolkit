# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from injector import inject

from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.tenant_wiki_service import TenantWikiService
from iatoolkit.common.access import ADMIN
from iatoolkit.common import access


class MemoryWikiService:
    """
    Where the company's Memoria keeps its pages: a managed system wiki per
    tenant, written through `TenantWikiService` so every change gets a revision
    (author, date, undo) and the pages can be corrected in the wiki editor.

    The wiki is owned by Memoria (`system_owner`), so the generic wiki surfaces
    leave it out and only this service reads it.
    """

    WIKI_KEY = "iatoolkit-memory"
    SYSTEM_OWNER = "memory"
    WIKI_NAME = "Memoria"
    WIKI_DESCRIPTION = "Lo que la empresa sabe hacer: conocimiento capturado de su gente."
    SCHEMA_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "memory" / "wiki_schema.md"
    MAX_INDEX_ENTRIES = 5000

    @inject
    def __init__(self,
                 tenant_wiki_service: TenantWikiService,
                 markdown_wiki_service: MarkdownWikiService):
        self.tenant_wiki_service = tenant_wiki_service
        self.markdown_wiki_service = markdown_wiki_service

    def ensure_wiki(self, company_short_name: str) -> dict:
        return self.tenant_wiki_service.ensure_system_wiki(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            system_owner=self.SYSTEM_OWNER,
            name=self.WIKI_NAME,
            description=self.WIKI_DESCRIPTION,
        )

    @classmethod
    def read_schema(cls) -> str:
        return _read_schema_template(str(cls.SCHEMA_TEMPLATE_PATH))

    # Audiences (BL-010, Fase 3): `audience_keys` lists the audiences to include (None in
    # the list is the whole company); omitted, every page (the compiler's own bookkeeping
    # and the administration).

    def list_pages(self, company_short_name: str, audience_keys: list | None = None) -> list[dict]:
        """Every page of the company's Memoria (of `audience_keys`, when given), without bodies."""
        response = self.tenant_wiki_service.get_index(company_short_name, wiki_key=self.WIKI_KEY,
                                                      audience_keys=audience_keys)
        if response.get("status") != "success":
            return []
        return list(response.get("entries") or [])[:self.MAX_INDEX_ENTRIES]

    def search_pages(self, company_short_name: str, query: str, limit: int = 5,
                     audience_keys: list | None = None) -> list[dict]:
        response = self.tenant_wiki_service.search_pages(
            company_short_name,
            query=query,
            wiki_key=self.WIKI_KEY,
            limit=limit,
            include_system=True,
            audience_keys=audience_keys,
        )
        if response.get("status") != "success":
            return []
        return list(response.get("results") or [])

    def get_page(self, company_short_name: str, page_id: int, audience_keys: list | None = None) -> dict | None:
        """The page with its markdown and `checksum`, or None (also when it is of another audience)."""
        response = self.tenant_wiki_service.get_page_by_id(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            page_id=page_id,
            include_system=True,
            audience_keys=audience_keys,
        )
        if response.get("status") != "success":
            return None
        return response.get("page")

    def create_page(self,
                    company_short_name: str,
                    *,
                    title: str,
                    body: str,
                    summary: str = "",
                    edited_by: str | None = None,
                    change_summary: str | None = None,
                    revision_metadata: dict | None = None,
                    audience_key: str | None = None) -> dict:
        """A new page; one of a restricted audience lives under its own folder (`rrhh/...`)."""
        path = self._available_path(company_short_name, title, audience_key=audience_key)
        response = self.tenant_wiki_service.create_page(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            path=path,
            title=title,
            markdown=self.render_page(title=title, summary=summary, body=body),
            edited_by=edited_by,
            change_summary=change_summary,
            revision_metadata=revision_metadata,
        )
        page_id = ((response or {}).get("page") or {}).get("id")
        if audience_key and page_id:
            self.tenant_wiki_service.set_page_audience(company_short_name, wiki_key=self.WIKI_KEY,
                                                       page_id=page_id, audience_key=audience_key)
            response["page"]["audience_key"] = audience_key
        return response

    def update_page(self,
                    company_short_name: str,
                    *,
                    page: dict,
                    title: str,
                    body: str,
                    summary: str = "",
                    edited_by: str | None = None,
                    change_summary: str | None = None,
                    revision_metadata: dict | None = None) -> dict:
        """
        Saves new content over `page` as it was read. Refused with
        `error_code=page_changed` when someone saved it in between.
        """
        return self.tenant_wiki_service.save_page(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            path=page.get("path"),
            markdown=self.render_page(
                title=title,
                summary=summary,
                body=body,
                frontmatter=page.get("frontmatter") or {},
            ),
            edited_by=edited_by,
            expected_checksum=page.get("checksum"),
            change_summary=change_summary,
            revision_metadata=revision_metadata,
        )

    def list_revisions(self, company_short_name: str, *, path: str | None = None, limit: int = 50) -> list[dict]:
        response = self.tenant_wiki_service.list_page_revisions(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            path=path,
            limit=limit,
        )
        if response.get("status") != "success":
            return []
        return list(response.get("revisions") or [])

    def list_activity(self, company_short_name: str, *, limit: int = 50) -> list[dict]:
        """Latest changes across every page of the company's Memoria."""
        response = self.tenant_wiki_service.list_wiki_revisions(company_short_name, wiki_key=self.WIKI_KEY, limit=limit)
        if response.get("status") != "success":
            return []
        return list(response.get("revisions") or [])

    def get_revision(self, company_short_name: str, revision_id: int) -> dict | None:
        response = self.tenant_wiki_service.get_page_revision(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            revision_id=revision_id,
        )
        if response.get("status") != "success":
            return None
        return response.get("revision")

    def set_page_audience(self, company_short_name: str, page_id: int, audience_key: str | None) -> bool:
        return self.tenant_wiki_service.set_page_audience(company_short_name, wiki_key=self.WIKI_KEY,
                                                          page_id=page_id, audience_key=audience_key)

    def list_audience_pages(self, company_short_name: str, audience_key: str | None) -> list[dict]:
        """Every page of one audience, with no cap (re-scoping and deleting go through all of them)."""
        response = self.tenant_wiki_service.get_index(company_short_name, wiki_key=self.WIKI_KEY,
                                                      audience_keys=[audience_key or None])
        return list(response.get("entries") or []) if response.get("status") == "success" else []

    def delete_page(self, company_short_name: str, *, page: dict, edited_by: str | None = None) -> dict:
        return self.tenant_wiki_service.delete_page(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            path=page.get("path"),
            edited_by=edited_by,
        )

    def save_markdown(self,
                      company_short_name: str,
                      *,
                      page: dict,
                      markdown: str,
                      edited_by: str | None = None,
                      expected_checksum: str | None = None,
                      change_summary: str | None = None,
                      revision_metadata: dict | None = None) -> dict:
        """Saves a whole markdown document (frontmatter included), as a person edits it."""
        return self.tenant_wiki_service.save_page(
            company_short_name,
            wiki_key=self.WIKI_KEY,
            path=page.get("path"),
            markdown=markdown,
            edited_by=edited_by,
            expected_checksum=expected_checksum,
            change_summary=change_summary,
            revision_metadata=revision_metadata,
        )

    def page_body(self, page: dict | None) -> str:
        """The page markdown without its frontmatter: what the compiler edits."""
        if not page:
            return ""
        parsed = self.markdown_wiki_service.parse_frontmatter_document(str(page.get("markdown") or ""))
        return str(parsed.get("body") or "").strip()

    def render_page(self, *, title: str, summary: str, body: str, frontmatter: dict | None = None) -> str:
        merged = dict(frontmatter or {})
        merged["title"] = str(title or "").strip()
        merged["summary"] = str(summary or "").strip()
        merged.setdefault("status", "published")
        return self.markdown_wiki_service.render_frontmatter_document(merged, str(body or "").strip() + "\n")

    def audience_folder(self, company_short_name: str, audience_key: str | None) -> str:
        """The path prefix of an audience's pages: its name, slugified ("" for the whole company)."""
        if not audience_key:
            return ""
        label = access.audience_label(company_short_name, audience_key) or audience_key
        return self.markdown_wiki_service.slugify(label) or self.markdown_wiki_service.slugify(audience_key) or "restringido"

    def _available_path(self, company_short_name: str, title: str, audience_key: str | None = None) -> str:
        folder = self.audience_folder(company_short_name, audience_key)
        base = self.markdown_wiki_service.slugify(title) or "pagina"
        if folder:
            base = f"{folder}/{base}"
        taken = {str(entry.get("path") or "") for entry in self.list_pages(company_short_name)}
        candidate = f"{base}.md"
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}.md"
            suffix += 1
        return candidate


@lru_cache(maxsize=4)
def _read_schema_template(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


# Memoria's wiki opens in the wiki viewer only for those who administer the company
# ("Ver como wiki", BL-014); for everyone else, and for the wiki tools and MCP, it
# stays hidden.
TenantWikiService.register_system_wiki_readers(MemoryWikiService.SYSTEM_OWNER, ADMIN)

