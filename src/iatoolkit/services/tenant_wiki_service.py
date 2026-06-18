# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from injector import inject

from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo
from iatoolkit.repositories.models import (
    Company,
    KnowledgeWiki,
    KnowledgeWikiPage,
    KnowledgeWikiPageRevision,
    KnowledgeWikiPageStatus,
    KnowledgeWikiStatus,
    KnowledgeWikiSyncStatus,
)
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.storage_service import StorageService


class TenantWikiService:
    GENERATED_FOLDER = ".iatoolkit"
    INDEX_FILENAME = "index.md"
    AUTHORING_MODE_MANAGED = "managed"
    AUTHORING_MODE_EXTERNAL_SYNC = "external_sync"
    ROOT_INDEX_GENERATED_FLAG = "iatoolkit_generated"

    @inject
    def __init__(
        self,
        profile_repo: ProfileRepo,
        knowledge_wiki_repo: KnowledgeWikiRepo,
        markdown_wiki_service: MarkdownWikiService,
        storage_service: StorageService,
    ):
        self.profile_repo = profile_repo
        self.knowledge_wiki_repo = knowledge_wiki_repo
        self.markdown_wiki_service = markdown_wiki_service
        self.storage_service = storage_service

    @classmethod
    def normalize_wiki_key(cls, value: str) -> str:
        candidate = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lower()).strip("-._")
        return candidate[:80]

    @classmethod
    def default_root_storage_key(cls, company_short_name: str, wiki_key: str) -> str:
        return f"companies/{company_short_name}/knowledge_wikis/{cls.normalize_wiki_key(wiki_key)}"

    @classmethod
    def normalize_authoring_mode(cls, value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == cls.AUTHORING_MODE_EXTERNAL_SYNC:
            return cls.AUTHORING_MODE_EXTERNAL_SYNC
        return cls.AUTHORING_MODE_MANAGED

    def wiki_authoring_mode(self, wiki: KnowledgeWiki | None) -> str:
        if wiki is None:
            return self.AUTHORING_MODE_MANAGED
        settings = wiki.settings if isinstance(wiki.settings, dict) else {}
        configured = settings.get("authoring_mode")
        if configured:
            return self.normalize_authoring_mode(configured)
        if wiki.last_synced_at:
            return self.AUTHORING_MODE_EXTERNAL_SYNC
        return self.AUTHORING_MODE_MANAGED

    def configure_wiki(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        name: str | None = None,
        description: str | None = None,
        root_storage_key: str | None = None,
        status: str = "published",
        settings: dict | None = None,
    ) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        normalized_key = self.normalize_wiki_key(wiki_key)
        if not normalized_key:
            return {"status": "error", "error_message": "wiki_key is required"}
        wiki_status = self._normalize_wiki_status(status)
        existing = self.knowledge_wiki_repo.get_wiki_by_key(company.id, normalized_key)
        normalized_settings = self._normalize_wiki_settings(
            settings,
            existing_settings=existing.settings if existing else None,
            default_authoring_mode=self.AUTHORING_MODE_MANAGED,
        )
        wiki = self.knowledge_wiki_repo.create_or_update_wiki(
            company_id=company.id,
            wiki_key=normalized_key,
            name=str(name or normalized_key).strip(),
            description=str(description or "").strip() or None,
            root_storage_key=self._normalize_root_storage_key(
                root_storage_key or self.default_root_storage_key(company_short_name, normalized_key)
            ),
            status=wiki_status,
            settings=normalized_settings,
        )
        if self.wiki_authoring_mode(wiki) == self.AUTHORING_MODE_MANAGED:
            self._ensure_root_index(
                company_short_name,
                wiki,
                entries=self._page_entries(wiki),
                force=False,
            )
        return {"status": "success", "wiki": self.serialize_wiki(wiki)}

    def list_wikis(self, company_short_name: str, *, include_archived: bool = False) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "wikis": [], "error_message": "company not found"}
        wikis = self.knowledge_wiki_repo.list_wikis(company.id, include_archived=include_archived)
        return {"status": "success", "wikis": [self.serialize_wiki(wiki) for wiki in wikis]}

    def delete_wiki(self, company_short_name: str, *, wiki_key: str) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        normalized_key = self.normalize_wiki_key(wiki_key)
        if not normalized_key:
            return {"status": "error", "error_message": "wiki_key is required"}
        wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, normalized_key)
        if not wiki:
            return {"status": "error", "error_message": "wiki not found"}

        generated_index_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.GENERATED_FOLDER,
            self.INDEX_FILENAME,
        )
        try:
            self.markdown_wiki_service.delete_markdown(company_short_name, generated_index_key)
        except Exception:
            pass

        self.knowledge_wiki_repo.delete_wiki(company.id, normalized_key)
        return {
            "status": "success",
            "wiki_key": normalized_key,
            "root_storage_key": wiki.root_storage_key,
        }

    def sync_wiki(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        root_storage_key: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        wiki = self._get_or_create_wiki(
            company,
            company_short_name=company_short_name,
            wiki_key=wiki_key,
            root_storage_key=root_storage_key,
            name=name,
            description=description,
        )
        if not wiki:
            return {"status": "error", "error_message": "wiki_key is required"}
        if self.wiki_authoring_mode(wiki) != self.AUTHORING_MODE_EXTERNAL_SYNC:
            return {
                "status": "error",
                "error_message": "wiki is managed in the GUI and cannot be refreshed from storage",
            }

        sync_started_at = datetime.now()
        run = self.knowledge_wiki_repo.create_sync_run(
            company_id=company.id,
            wiki_id=wiki.id,
            metadata_json={"root_storage_key": wiki.root_storage_key},
        )
        errors = []
        seen_paths: set[str] = set()
        indexed = 0
        failed = 0

        try:
            files = self.storage_service.list_files(
                company_short_name,
                prefix=wiki.root_storage_key,
                extension=".md",
            )
            source_files = [
                item for item in files
                if self._is_source_markdown_file(wiki.root_storage_key, str(item.get("path") or ""))
            ]
            for item in source_files:
                storage_key = str(item.get("path") or "").strip()
                try:
                    markdown = self.markdown_wiki_service.read_markdown(company_short_name, storage_key)
                    page_payload = self._parse_markdown_page(
                        root_storage_key=wiki.root_storage_key,
                        storage_key=storage_key,
                        markdown=markdown,
                        file_metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    )
                    seen_paths.add(page_payload["path"])
                    unique_slug = self._resolve_unique_slug(wiki.id, page_payload["slug"], page_payload["path"])
                    page_payload["slug"] = unique_slug
                    self.knowledge_wiki_repo.create_or_update_page(
                        company_id=company.id,
                        wiki_id=wiki.id,
                        last_synced_at=sync_started_at,
                        **page_payload,
                    )
                    indexed += 1
                except Exception as exc:
                    failed += 1
                    errors.append({
                        "path": storage_key,
                        "error": str(exc),
                    })

            archived = self.knowledge_wiki_repo.archive_pages_not_in_paths(wiki.id, seen_paths)
            wiki.last_synced_at = sync_started_at
            self.knowledge_wiki_repo.commit()
            page_entries = self._page_entries(wiki)
            self._ensure_root_index(
                company_short_name,
                wiki,
                entries=page_entries,
                force=False,
            )
            self._write_generated_index(company_short_name, wiki)

            run.status = KnowledgeWikiSyncStatus.SUCCESS if failed == 0 else KnowledgeWikiSyncStatus.FAILED
            run.pages_seen = len(source_files)
            run.pages_indexed = indexed
            run.pages_failed = failed
            run.errors = errors
            run.metadata_json = {**(run.metadata_json or {}), "archived_pages": archived}
            run.finished_at = datetime.now()
            self.knowledge_wiki_repo.save_sync_run(run)
            return {
                "status": "success" if failed == 0 else "partial_success",
                "wiki": self.serialize_wiki(wiki),
                "sync": self.serialize_sync_run(run),
            }
        except Exception as exc:
            run.status = KnowledgeWikiSyncStatus.FAILED
            run.errors = [{"error": str(exc)}]
            run.finished_at = datetime.now()
            self.knowledge_wiki_repo.save_sync_run(run)
            return {"status": "error", "error_message": str(exc), "sync": self.serialize_sync_run(run)}

    def get_index(self, company_short_name: str, *, wiki_key: str) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, self.normalize_wiki_key(wiki_key))
        if not wiki:
            return {"status": "error", "error_message": "wiki not found"}
        page_entries = self._page_entries(wiki)
        generated_markdown = self.markdown_wiki_service.render_generic_index(page_entries, title=wiki.name)
        home_markdown, source_storage_key = self._resolve_home_markdown(
            company_short_name,
            wiki,
            page_entries,
        )
        home_page = self._build_virtual_index_page(
            wiki,
            markdown=home_markdown,
            source_storage_key=source_storage_key,
            path="/",
        )
        return {
            "status": "success",
            "wiki": self.serialize_wiki(wiki),
            "entries": page_entries,
            "markdown": home_markdown,
            "home_markdown": home_markdown,
            "home_page": home_page,
            "generated_markdown": generated_markdown,
            "generated_index_path": self.markdown_wiki_service.join_storage_path(self.GENERATED_FOLDER, self.INDEX_FILENAME),
            "generated_index_source_path": self.markdown_wiki_service.join_storage_path(self.GENERATED_FOLDER, self.INDEX_FILENAME),
            "mcp_markdown": home_markdown,
            "mcp_index_path": "/",
            "mcp_index_source_path": self._index_source_display_path(wiki, source_storage_key),
            "index_path": "/",
            "index_source_path": self._index_source_display_path(wiki, source_storage_key),
        }

    def get_page(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        path: str,
        allowed_wiki_keys: list[str] | set[str] | tuple[str, ...] | None = None,
    ) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        normalized_wiki_key = self.normalize_wiki_key(wiki_key)
        allowed_keys = self._normalize_allowed_wiki_keys(allowed_wiki_keys)
        if allowed_keys is not None and not allowed_keys:
            return {"status": "error", "error_message": "no published knowledge wiki resources available"}
        if allowed_keys is not None and normalized_wiki_key not in allowed_keys:
            return {"status": "error", "error_message": "wiki not exposed to MCP"}
        wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, normalized_wiki_key)
        if not wiki:
            return {"status": "error", "error_message": "wiki not found"}

        normalized_path = self._normalize_page_path(path)
        if normalized_path in {"", "/"}:
            entries = self._page_entries(wiki)
            markdown, source_storage_key = self._resolve_home_markdown(
                company_short_name,
                wiki,
                entries,
            )
            return {
                "status": "success",
                "wiki": self.serialize_wiki(wiki),
                "page": self._build_virtual_index_page(
                    wiki,
                    markdown=markdown,
                    source_storage_key=source_storage_key,
                    path="/",
                ),
            }
        if normalized_path == self.INDEX_FILENAME:
            entries = self._page_entries(wiki)
            authored_index_markdown, authored_index_storage_key = self._resolve_home_markdown(
                company_short_name,
                wiki,
                entries,
            )
            return {
                "status": "success",
                "wiki": self.serialize_wiki(wiki),
                "page": self._build_virtual_index_page(
                    wiki,
                    markdown=authored_index_markdown,
                    source_storage_key=authored_index_storage_key,
                    path=self.INDEX_FILENAME,
                ),
            }
        page = self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_path)
        if page is None:
            page = self.knowledge_wiki_repo.get_page_by_slug(wiki.id, self.markdown_wiki_service.slugify(path))
        if page is None or page.status == KnowledgeWikiPageStatus.ARCHIVED:
            return {"status": "error", "error_message": "page not found"}

        markdown = self.markdown_wiki_service.read_markdown(company_short_name, page.source_storage_key)
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown)
        return {
            "status": "success",
            "wiki": self.serialize_wiki(wiki),
            "page": {
                **self.serialize_page(page, include_body=True),
                "frontmatter": parsed.get("frontmatter") or {},
                "markdown": markdown,
            },
        }

    def create_page(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        path: str,
        title: str | None = None,
        markdown: str | None = None,
        edited_by: str | None = None,
    ) -> dict:
        company, wiki, error = self._resolve_managed_wiki(company_short_name, wiki_key)
        if error:
            return error
        normalized_path = self._normalize_managed_page_path(path)
        if not normalized_path:
            return {"status": "error", "error_message": "page path is required"}
        if normalized_path == self.INDEX_FILENAME:
            return {"status": "error", "error_message": "index.md is reserved for the wiki home page"}
        if self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_path):
            return {"status": "error", "error_message": "page already exists"}

        page_title = str(title or "").strip() or self._title_from_path(normalized_path)
        page_markdown = str(markdown or "").strip() or self._default_page_markdown(page_title)
        storage_key = self._page_storage_key(wiki, normalized_path)
        page = self._write_page_document(
            company_short_name,
            company_id=company.id,
            wiki=wiki,
            path=normalized_path,
            storage_key=storage_key,
            markdown=page_markdown,
        )
        self._record_page_revision(
            company_id=company.id,
            wiki=wiki,
            page=page,
            action="create",
            markdown=page_markdown,
            edited_by=edited_by,
        )
        self._refresh_root_index_if_generated(company_short_name, wiki)
        return self.get_page(company_short_name, wiki_key=wiki.wiki_key, path=page.path)

    def save_page(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        path: str,
        markdown: str,
        edited_by: str | None = None,
    ) -> dict:
        company, wiki, error = self._resolve_managed_wiki(company_short_name, wiki_key)
        if error:
            return error
        normalized_path = self._normalize_page_path(path)
        if normalized_path in {"", "/"}:
            normalized_path = self.INDEX_FILENAME
        if not normalized_path:
            return {"status": "error", "error_message": "page path is required"}

        markdown_text = str(markdown or "")
        if normalized_path == self.INDEX_FILENAME:
            storage_key = self._root_index_storage_key(wiki)
            self.markdown_wiki_service.write_markdown(
                company_short_name,
                storage_key,
                self._mark_root_index_as_manual(markdown_text),
            )
            self._record_page_revision(
                company_id=company.id,
                wiki=wiki,
                page=None,
                action="update",
                path=self.INDEX_FILENAME,
                markdown=markdown_text,
                edited_by=edited_by,
                metadata={"root_index": True},
            )
            self._write_generated_index(company_short_name, wiki)
            return self.get_page(company_short_name, wiki_key=wiki.wiki_key, path=self.INDEX_FILENAME)

        page = self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_path)
        if page is None:
            return {"status": "error", "error_message": "page not found"}
        self._write_page_document(
            company_short_name,
            company_id=company.id,
            wiki=wiki,
            path=normalized_path,
            storage_key=page.source_storage_key,
            markdown=markdown_text,
        )
        self._record_page_revision(
            company_id=company.id,
            wiki=wiki,
            page=page,
            action="update",
            markdown=markdown_text,
            edited_by=edited_by,
        )
        self._refresh_root_index_if_generated(company_short_name, wiki)
        return self.get_page(company_short_name, wiki_key=wiki.wiki_key, path=normalized_path)

    def delete_page(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        path: str,
        edited_by: str | None = None,
    ) -> dict:
        company, wiki, error = self._resolve_managed_wiki(company_short_name, wiki_key)
        if error:
            return error
        normalized_path = self._normalize_page_path(path)
        if normalized_path in {"", "/", self.INDEX_FILENAME}:
            return {"status": "error", "error_message": "index.md cannot be deleted"}
        page = self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_path)
        if page is None:
            return {"status": "error", "error_message": "page not found"}
        markdown = self.markdown_wiki_service.read_markdown(company_short_name, page.source_storage_key)
        self._record_page_revision(
            company_id=company.id,
            wiki=wiki,
            page=page,
            action="delete",
            markdown=markdown,
            edited_by=edited_by,
        )
        self.markdown_wiki_service.delete_markdown(company_short_name, page.source_storage_key)
        self.knowledge_wiki_repo.delete_page(wiki.id, normalized_path)
        self._refresh_root_index_if_generated(company_short_name, wiki)
        return {"status": "success", "wiki_key": wiki.wiki_key, "path": normalized_path}

    def move_page(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        path: str,
        new_path: str,
        title: str | None = None,
        edited_by: str | None = None,
    ) -> dict:
        company, wiki, error = self._resolve_managed_wiki(company_short_name, wiki_key)
        if error:
            return error

        normalized_path = self._normalize_page_path(path)
        if normalized_path in {"", "/", self.INDEX_FILENAME}:
            return {"status": "error", "error_message": "index.md cannot be moved"}

        normalized_new_path = self._normalize_managed_page_path(new_path)
        if not normalized_new_path:
            return {"status": "error", "error_message": "new page path is required"}
        if normalized_new_path == self.INDEX_FILENAME:
            return {"status": "error", "error_message": "index.md is reserved for the wiki home page"}

        page = self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_path)
        if page is None:
            return {"status": "error", "error_message": "page not found"}

        existing_target = self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_new_path)
        if existing_target is not None and existing_target.id != page.id:
            return {"status": "error", "error_message": "target page already exists"}

        old_storage_key = page.source_storage_key
        new_storage_key = self._page_storage_key(wiki, normalized_new_path)
        original_markdown = self.markdown_wiki_service.read_markdown(company_short_name, old_storage_key)
        moved_markdown = self._apply_title_to_markdown(original_markdown, title)

        self.markdown_wiki_service.write_markdown(company_short_name, new_storage_key, moved_markdown)
        if new_storage_key != old_storage_key:
            self.markdown_wiki_service.delete_markdown(company_short_name, old_storage_key)

        page_payload = self._parse_markdown_page(
            root_storage_key=wiki.root_storage_key,
            storage_key=new_storage_key,
            markdown=moved_markdown,
            file_metadata={},
        )
        page.path = normalized_new_path
        page.slug = self._resolve_unique_slug(wiki.id, page_payload["slug"], normalized_new_path)
        page.title = page_payload["title"]
        page.summary = page_payload["summary"]
        page.body_text = page_payload["body_text"]
        page.source_storage_key = new_storage_key
        page.status = page_payload["status"]
        page.tags = page_payload["tags"]
        page.owner = page_payload["owner"]
        page.source_meta = self.markdown_wiki_service.make_json_safe(
            {
                **(page_payload.get("source_meta") or {}),
                "origin": "managed",
                "moved_from": normalized_path,
            }
        )
        page = self.knowledge_wiki_repo.save_page(page)

        self._record_page_revision(
            company_id=company.id,
            wiki=wiki,
            page=page,
            action="move",
            path=normalized_new_path,
            previous_path=normalized_path,
            markdown=moved_markdown,
            edited_by=edited_by,
            metadata={
                "old_storage_key": old_storage_key,
                "new_storage_key": new_storage_key,
            },
        )
        self._refresh_root_index_if_generated(company_short_name, wiki)
        return self.get_page(company_short_name, wiki_key=wiki.wiki_key, path=normalized_new_path)

    def list_page_revisions(
        self,
        company_short_name: str,
        *,
        wiki_key: str,
        path: str | None = None,
        limit: int = 50,
    ) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found", "revisions": []}
        wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, self.normalize_wiki_key(wiki_key))
        if not wiki:
            return {"status": "error", "error_message": "wiki not found", "revisions": []}

        normalized_path = self._normalize_page_path(path or "")
        if normalized_path in {"", "/"}:
            normalized_path = self.INDEX_FILENAME
        page = self.knowledge_wiki_repo.get_page_by_path(wiki.id, normalized_path) if normalized_path else None
        revisions = self.knowledge_wiki_repo.list_page_revisions(
            wiki.id,
            path=normalized_path or None,
            page_id=page.id if page else None,
            limit=limit,
        )
        return {
            "status": "success",
            "wiki": self.serialize_wiki(wiki),
            "path": normalized_path or None,
            "revisions": [self.serialize_page_revision(revision) for revision in revisions],
        }

    def search_pages(
        self,
        company_short_name: str,
        *,
        query: str,
        wiki_key: str | None = None,
        limit: int = 5,
        allowed_wiki_keys: list[str] | set[str] | tuple[str, ...] | None = None,
    ) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "results": [], "error_message": "company not found"}
        normalized_query = self._normalize_text(query)
        query_tokens = self._tokenize(query)
        allowed_keys = self._normalize_allowed_wiki_keys(allowed_wiki_keys)
        normalized_wiki_key = self.normalize_wiki_key(wiki_key) if wiki_key else None
        if allowed_keys is not None and not allowed_keys:
            return {
                "status": "error",
                "query": query,
                "wiki_key": normalized_wiki_key,
                "count": 0,
                "results": [],
                "error_message": "no published knowledge wiki resources available",
            }
        if wiki_key:
            if allowed_keys is not None and normalized_wiki_key not in allowed_keys:
                return {
                    "status": "error",
                    "query": query,
                    "wiki_key": normalized_wiki_key,
                    "count": 0,
                    "results": [],
                    "error_message": "wiki not exposed to MCP",
                }
            wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, normalized_wiki_key)
            wikis = [wiki] if wiki else []
        else:
            wikis = self.knowledge_wiki_repo.list_wikis(company.id, include_archived=False)
            if allowed_keys is not None:
                wikis = [
                    wiki for wiki in wikis
                    if wiki and self.normalize_wiki_key(wiki.wiki_key) in allowed_keys
                ]

        results = []
        for wiki in wikis:
            if not wiki or wiki.status == KnowledgeWikiStatus.ARCHIVED:
                continue
            pages = self.knowledge_wiki_repo.list_pages(wiki.id, include_archived=False, limit=1000)
            for page in pages:
                if page.status == KnowledgeWikiPageStatus.ARCHIVED:
                    continue
                score = self._score_page_match(normalized_query, query_tokens, page)
                if normalized_query and score <= 0:
                    continue
                results.append({
                    **self.serialize_page(page, include_body=False),
                    "wiki_key": wiki.wiki_key,
                    "wiki_name": wiki.name,
                    "score": round(score if score > 0 else 1.0, 4),
                })

        results.sort(
            key=lambda item: (
                float(item.get("score") or 0),
                item.get("updated_at") or "",
                item.get("path") or "",
            ),
            reverse=True,
        )
        bounded_limit = min(max(int(limit or 5), 1), 25)
        return {
            "status": "success",
            "query": query,
            "wiki_key": normalized_wiki_key,
            "count": len(results[:bounded_limit]),
            "results": results[:bounded_limit],
        }

    def lint_wikis(self, company_short_name: str, *, wiki_key: str | None = None) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        if wiki_key:
            wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, self.normalize_wiki_key(wiki_key))
            wikis = [wiki] if wiki else []
        else:
            wikis = self.knowledge_wiki_repo.list_wikis(company.id, include_archived=False)

        issues = []
        checked_pages = 0
        for wiki in wikis:
            if not wiki or wiki.status == KnowledgeWikiStatus.ARCHIVED:
                continue
            pages = self.knowledge_wiki_repo.list_pages(wiki.id, include_archived=False, limit=1000)
            checked_pages += len(pages)
            issues.extend(self._lint_wiki_pages(wiki, pages))

        return {
            "status": "success",
            "checked_wikis": len([wiki for wiki in wikis if wiki]),
            "checked_pages": checked_pages,
            "issues": issues,
            "issue_count": len(issues),
        }

    def _get_or_create_wiki(
        self,
        company: Company,
        *,
        company_short_name: str,
        wiki_key: str,
        root_storage_key: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> KnowledgeWiki | None:
        normalized_key = self.normalize_wiki_key(wiki_key)
        if not normalized_key:
            return None
        existing = self.knowledge_wiki_repo.get_wiki_by_key(company.id, normalized_key)
        if existing:
            if root_storage_key or name or description is not None:
                return self.knowledge_wiki_repo.create_or_update_wiki(
                    company_id=company.id,
                    wiki_key=normalized_key,
                    name=str(name or existing.name or normalized_key).strip(),
                    description=description if description is not None else existing.description,
                    root_storage_key=self._normalize_root_storage_key(root_storage_key or existing.root_storage_key),
                    status=existing.status,
                    settings=self._normalize_wiki_settings(
                        existing.settings,
                        existing_settings=existing.settings,
                        default_authoring_mode=self.AUTHORING_MODE_EXTERNAL_SYNC,
                    ),
                )
            return existing
        return self.knowledge_wiki_repo.create_or_update_wiki(
            company_id=company.id,
            wiki_key=normalized_key,
            name=str(name or normalized_key).strip(),
            description=str(description or "").strip() or None,
            root_storage_key=self._normalize_root_storage_key(
                root_storage_key or self.default_root_storage_key(company_short_name, normalized_key)
            ),
            status=KnowledgeWikiStatus.PUBLISHED,
            settings=self._normalize_wiki_settings(
                {},
                existing_settings=None,
                default_authoring_mode=self.AUTHORING_MODE_EXTERNAL_SYNC,
            ),
        )

    def _resolve_managed_wiki(
        self,
        company_short_name: str,
        wiki_key: str,
    ) -> tuple[Company | None, KnowledgeWiki | None, dict | None]:
        company = self._get_company(company_short_name)
        if not company:
            return None, None, {"status": "error", "error_message": "company not found"}
        normalized_key = self.normalize_wiki_key(wiki_key)
        wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, normalized_key)
        if not wiki:
            return company, None, {"status": "error", "error_message": "wiki not found"}
        if self.wiki_authoring_mode(wiki) != self.AUTHORING_MODE_MANAGED:
            return company, wiki, {
                "status": "error",
                "error_message": "wiki is read-only because its source of truth is external storage",
            }
        return company, wiki, None

    def _normalize_wiki_settings(
        self,
        settings: dict | None,
        *,
        existing_settings: dict | None = None,
        default_authoring_mode: str | None = None,
    ) -> dict:
        normalized = dict(existing_settings or {})
        if isinstance(settings, dict):
            normalized.update(settings)
        normalized["authoring_mode"] = self.normalize_authoring_mode(
            normalized.get("authoring_mode") or default_authoring_mode
        )
        return normalized

    def _page_entries(self, wiki: KnowledgeWiki) -> list[dict]:
        pages = self.knowledge_wiki_repo.list_pages(wiki.id, include_archived=False, limit=1000)
        return [self.serialize_page(page, include_body=False) for page in pages]

    def _root_index_storage_key(self, wiki: KnowledgeWiki) -> str:
        return self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.INDEX_FILENAME,
        )

    def _page_storage_key(self, wiki: KnowledgeWiki, path: str) -> str:
        return self.markdown_wiki_service.join_storage_path(wiki.root_storage_key, path)

    def _render_root_index_markdown(self, wiki: KnowledgeWiki, entries: list[dict]) -> str:
        frontmatter = {
            "title": wiki.name,
            "summary": str(wiki.description or "").strip(),
            "status": "published",
            self.ROOT_INDEX_GENERATED_FLAG: True,
        }
        body_lines = [f"# {wiki.name}", ""]
        if str(wiki.description or "").strip():
            body_lines.append(str(wiki.description or "").strip())
            body_lines.append("")
        body_lines.append("## Available pages")
        body_lines.append("")
        body_lines.extend(self.markdown_wiki_service._render_index_entry_lines(entries))
        return self.markdown_wiki_service.render_frontmatter_document(frontmatter, "\n".join(body_lines).strip())

    def _ensure_root_index(
        self,
        company_short_name: str,
        wiki: KnowledgeWiki,
        *,
        entries: list[dict],
        force: bool = False,
    ) -> tuple[str, str]:
        storage_key = self._root_index_storage_key(wiki)
        existing = self.markdown_wiki_service.read_optional_markdown(company_short_name, storage_key)
        if existing and not force:
            return existing, storage_key
        markdown = self._render_root_index_markdown(wiki, entries)
        self.markdown_wiki_service.write_markdown(company_short_name, storage_key, markdown)
        return markdown, storage_key

    def _resolve_home_markdown(
        self,
        company_short_name: str,
        wiki: KnowledgeWiki,
        entries: list[dict],
    ) -> tuple[str, str]:
        storage_key = self._root_index_storage_key(wiki)
        markdown = self.markdown_wiki_service.read_optional_markdown(company_short_name, storage_key)
        if markdown:
            return markdown, storage_key
        generated_storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.GENERATED_FOLDER,
            self.INDEX_FILENAME,
        )
        return self._render_root_index_markdown(wiki, entries), generated_storage_key

    def _root_index_is_generated(self, markdown: str | None) -> bool:
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown or "")
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        return bool(frontmatter.get(self.ROOT_INDEX_GENERATED_FLAG))

    def _refresh_root_index_if_generated(self, company_short_name: str, wiki: KnowledgeWiki) -> None:
        storage_key = self._root_index_storage_key(wiki)
        existing = self.markdown_wiki_service.read_optional_markdown(company_short_name, storage_key)
        if not existing or self._root_index_is_generated(existing):
            self._ensure_root_index(
                company_short_name,
                wiki,
                entries=self._page_entries(wiki),
                force=True,
            )
        self._write_generated_index(company_short_name, wiki)

    def _mark_root_index_as_manual(self, markdown: str) -> str:
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        body = str(parsed.get("body") or "").strip()
        if not frontmatter and not str(markdown or "").lstrip().startswith("---"):
            return str(markdown or "")
        frontmatter[self.ROOT_INDEX_GENERATED_FLAG] = False
        return self.markdown_wiki_service.render_frontmatter_document(frontmatter, body)

    def _write_page_document(
        self,
        company_short_name: str,
        *,
        company_id: int,
        wiki: KnowledgeWiki,
        path: str,
        storage_key: str,
        markdown: str,
    ) -> KnowledgeWikiPage:
        self.markdown_wiki_service.write_markdown(company_short_name, storage_key, markdown)
        page_payload = self._parse_markdown_page(
            root_storage_key=wiki.root_storage_key,
            storage_key=storage_key,
            markdown=markdown,
            file_metadata={},
        )
        page_payload["path"] = path
        page_payload["slug"] = self._resolve_unique_slug(wiki.id, page_payload["slug"], path)
        page_payload["source_meta"] = self.markdown_wiki_service.make_json_safe(
            {
                **(page_payload.get("source_meta") or {}),
                "origin": "managed",
            }
        )
        return self.knowledge_wiki_repo.create_or_update_page(
            company_id=company_id,
            wiki_id=wiki.id,
            last_synced_at=wiki.last_synced_at,
            **page_payload,
        )

    def _apply_title_to_markdown(self, markdown: str, title: str | None) -> str:
        normalized_title = str(title or "").strip()
        if not normalized_title:
            return str(markdown or "")
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        frontmatter["title"] = normalized_title
        return self.markdown_wiki_service.render_frontmatter_document(
            frontmatter,
            str(parsed.get("body") or "").strip(),
        )

    def _record_page_revision(
        self,
        *,
        company_id: int,
        wiki: KnowledgeWiki,
        page: KnowledgeWikiPage | None,
        action: str,
        markdown: str | None,
        edited_by: str | None = None,
        path: str | None = None,
        previous_path: str | None = None,
        title: str | None = None,
        change_summary: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        markdown_text = str(markdown or "")
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown_text)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        body = str(parsed.get("body") or "").strip()
        raw_path = path or (page.path if page else "")
        revision_path = self._normalize_page_path(raw_path)
        if revision_path in {"", "/"}:
            revision_path = self.INDEX_FILENAME
        revision_title = str(title or page.title if page else title or "").strip()
        if not revision_title:
            revision_title = self._page_title(revision_path, body, frontmatter)
        checksum = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest() if markdown_text else None
        self.knowledge_wiki_repo.create_page_revision(
            company_id=company_id,
            wiki_id=wiki.id,
            page_id=page.id if page else None,
            action=str(action or "update").strip().lower() or "update",
            path=revision_path,
            previous_path=self._normalize_page_path(previous_path or "") or None,
            title=revision_title,
            markdown=markdown_text,
            checksum=checksum,
            edited_by=str(edited_by or "").strip() or None,
            change_summary=str(change_summary or "").strip() or None,
            metadata_json=self.markdown_wiki_service.make_json_safe(metadata or {}),
        )

    def _default_page_markdown(self, title: str) -> str:
        frontmatter = {
            "title": title,
            "summary": "",
            "status": "published",
            "tags": [],
        }
        body = f"# {title}\n\n"
        return self.markdown_wiki_service.render_frontmatter_document(frontmatter, body)

    def _title_from_path(self, path: str) -> str:
        filename = os.path.splitext(os.path.basename(path))[0]
        return filename.replace("-", " ").replace("_", " ").strip().title() or "Untitled page"

    def _normalize_managed_page_path(self, value: str) -> str:
        if self._has_unsafe_page_segments(value):
            return ""
        path = self._normalize_page_path(value)
        if not path:
            return ""
        if not path.lower().endswith(".md"):
            path = f"{path}.md"
        if path.startswith(f"{self.GENERATED_FOLDER}/") or path.startswith("."):
            return ""
        return path

    def _parse_markdown_page(
        self,
        *,
        root_storage_key: str,
        storage_key: str,
        markdown: str,
        file_metadata: dict,
    ) -> dict:
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        body = str(parsed.get("body") or "").strip()
        path = self._relative_path(root_storage_key, storage_key)
        title = self._page_title(path, body, frontmatter)
        summary = str(frontmatter.get("summary") or "").strip() or self._summary_from_body(body)
        slug = str(frontmatter.get("slug") or "").strip() or self.markdown_wiki_service.slugify(path.rsplit(".", 1)[0])
        status = self._normalize_page_status(frontmatter.get("status"))
        source_meta = {
            "frontmatter": frontmatter,
            "file_metadata": file_metadata,
            "checksum": hashlib.sha256(str(markdown or "").encode("utf-8")).hexdigest(),
        }
        return {
            "path": path,
            "slug": slug,
            "title": title,
            "summary": summary,
            "body_text": body,
            "source_storage_key": storage_key,
            "status": status,
            "tags": self._normalize_tags(frontmatter.get("tags")),
            "owner": str(frontmatter.get("owner") or "").strip() or None,
            "source_meta": self.markdown_wiki_service.make_json_safe(source_meta),
        }

    def _write_generated_index(self, company_short_name: str, wiki: KnowledgeWiki) -> str:
        pages = self.knowledge_wiki_repo.list_pages(wiki.id, include_archived=False, limit=1000)
        entries = [self.serialize_page(page, include_body=False) for page in pages]
        markdown = self.markdown_wiki_service.render_generic_index(entries, title=wiki.name)
        storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.GENERATED_FOLDER,
            self.INDEX_FILENAME,
        )
        return self.markdown_wiki_service.write_markdown(company_short_name, storage_key, markdown)

    def _resolve_index_markdown(
        self,
        company_short_name: str,
        wiki: KnowledgeWiki,
        entries: list[dict],
    ) -> tuple[str, str]:
        authored_index_storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.INDEX_FILENAME,
        )
        authored_index_markdown = self.markdown_wiki_service.read_optional_markdown(
            company_short_name,
            authored_index_storage_key,
        )
        if authored_index_markdown:
            return authored_index_markdown, authored_index_storage_key

        generated_index_storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.GENERATED_FOLDER,
            self.INDEX_FILENAME,
        )
        return (
            self.markdown_wiki_service.render_generic_index(entries, title=wiki.name),
            generated_index_storage_key,
        )

    def _build_authored_index_entry(self, company_short_name: str, wiki: KnowledgeWiki) -> dict | None:
        authored_index_storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.INDEX_FILENAME,
        )
        authored_index_markdown = self.markdown_wiki_service.read_optional_markdown(
            company_short_name,
            authored_index_storage_key,
        )
        if not authored_index_markdown:
            return None
        page = self._build_virtual_index_page(
            wiki,
            markdown=authored_index_markdown,
            source_storage_key=authored_index_storage_key,
            path=self.INDEX_FILENAME,
        )
        return {
            key: value
            for key, value in page.items()
            if key not in {"body_text", "frontmatter", "markdown"}
        }

    def _build_virtual_index_page(
        self,
        wiki: KnowledgeWiki,
        *,
        markdown: str,
        source_storage_key: str,
        path: str,
    ) -> dict:
        parsed = self.markdown_wiki_service.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        body = str(parsed.get("body") or "").strip()
        summary_fallback = wiki.description or ""
        return {
            "id": None,
            "wiki_id": wiki.id,
            "path": path,
            "slug": "index",
            "title": str(frontmatter.get("title") or wiki.name or wiki.wiki_key).strip(),
            "summary": str(frontmatter.get("summary") or summary_fallback or "").strip(),
            "source_storage_key": source_storage_key,
            "status": str(frontmatter.get("status") or "active").strip() or "active",
            "tags": self._normalize_tags(frontmatter.get("tags")),
            "owner": str(frontmatter.get("owner") or "").strip() or None,
            "last_synced_at": wiki.last_synced_at.isoformat() if wiki.last_synced_at else None,
            "updated_at": wiki.updated_at.isoformat() if wiki.updated_at else None,
            "body_text": body,
            "frontmatter": frontmatter,
            "markdown": markdown,
            "is_root_index": True,
        }

    def _resolve_unique_slug(self, wiki_id: int, slug: str, path: str) -> str:
        candidate = self.markdown_wiki_service.slugify(slug)
        existing = self.knowledge_wiki_repo.get_page_by_slug(wiki_id, candidate)
        if existing is None or existing.path == path:
            return candidate
        path_slug = self.markdown_wiki_service.slugify(path.rsplit(".", 1)[0])
        existing = self.knowledge_wiki_repo.get_page_by_slug(wiki_id, path_slug)
        if existing is None or existing.path == path:
            return path_slug
        suffix = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
        return f"{path_slug[:70]}-{suffix}"

    def _index_source_display_path(self, wiki: KnowledgeWiki, source_storage_key: str) -> str:
        authored_index_storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.INDEX_FILENAME,
        )
        if source_storage_key == authored_index_storage_key:
            return self.INDEX_FILENAME
        return self.markdown_wiki_service.join_storage_path(self.GENERATED_FOLDER, self.INDEX_FILENAME)

    def _lint_wiki_pages(self, wiki: KnowledgeWiki, pages: list[KnowledgeWikiPage]) -> list[dict]:
        issues = []
        title_map: dict[str, list[KnowledgeWikiPage]] = {}
        targets = set()
        for page in pages:
            targets.add(self._normalize_page_path(page.path))
            targets.add(self.markdown_wiki_service.slugify(page.slug))
            targets.add(self._normalize_text(page.title))
            normalized_title = self._normalize_text(page.title)
            if normalized_title:
                title_map.setdefault(normalized_title, []).append(page)
            if not str(page.summary or "").strip():
                issues.append(self._lint_issue(wiki, page, "missing_summary", "Page has no summary."))
            if not (page.tags or []):
                issues.append(self._lint_issue(wiki, page, "missing_tags", "Page has no tags."))

        for title, candidates in title_map.items():
            if len(candidates) <= 1:
                continue
            for page in candidates:
                issues.append(
                    self._lint_issue(
                        wiki,
                        page,
                        "duplicate_title",
                        f"Page title duplicates another page: {title}.",
                    )
                )

        for page in pages:
            for target in self._extract_internal_link_targets(page.body_text or ""):
                resolved_target = self._resolve_internal_link_target(page.path, target)
                if self._link_target_exists(target, targets) or self._link_target_exists(resolved_target, targets):
                    continue
                issues.append(
                    self._lint_issue(
                        wiki,
                        page,
                        "broken_internal_link",
                        f"Internal link target not found: {target}.",
                    )
                )
        return issues

    @staticmethod
    def _lint_issue(wiki: KnowledgeWiki, page: KnowledgeWikiPage, issue_type: str, message: str) -> dict:
        return {
            "wiki_key": wiki.wiki_key,
            "page_id": page.id,
            "path": page.path,
            "issue_type": issue_type,
            "message": message,
        }

    def _extract_internal_link_targets(self, body: str) -> list[str]:
        targets = []
        for match in re.findall(r"\[\[([^\]]+)\]\]", str(body or "")):
            target = match.split("|", 1)[0].strip()
            if target:
                targets.append(target)
        for match in re.findall(r"\[[^\]]+\]\(([^)]+)\)", str(body or "")):
            target = match.split("#", 1)[0].split("?", 1)[0].strip()
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            if target.lower().endswith(".md"):
                targets.append(target)
        return targets

    def _resolve_internal_link_target(self, source_path: str, target: str) -> str:
        normalized_target = self._normalize_page_path(target)
        if not normalized_target or str(target or "").strip().startswith("/"):
            return self._collapse_relative_page_path(normalized_target)
        if "/" not in normalized_target and not normalized_target.lower().endswith(".md"):
            return normalized_target
        source_directory = PurePosixPath(self._normalize_page_path(source_path)).parent
        if str(source_directory) in {"", "."}:
            return self._collapse_relative_page_path(normalized_target)
        return self._collapse_relative_page_path(str(source_directory / normalized_target))

    def _link_target_exists(self, target: str, targets: set[str]) -> bool:
        normalized_path = self._normalize_page_path(target)
        if normalized_path in targets:
            return True
        if normalized_path and not normalized_path.endswith(".md") and f"{normalized_path}.md" in targets:
            return True
        slug = self.markdown_wiki_service.slugify(target.rsplit(".", 1)[0])
        if slug in targets:
            return True
        return self._normalize_text(target.rsplit(".", 1)[0]) in targets

    @classmethod
    def _normalize_allowed_wiki_keys(
        cls,
        allowed_wiki_keys: list[str] | set[str] | tuple[str, ...] | None,
    ) -> set[str] | None:
        if allowed_wiki_keys is None:
            return None
        if not isinstance(allowed_wiki_keys, (list, set, tuple)):
            return set()
        normalized = {
            cls.normalize_wiki_key(str(item or "").strip())
            for item in allowed_wiki_keys
        }
        return {item for item in normalized if item}

    def _score_page_match(self, normalized_query: str, query_tokens: set[str], page: KnowledgeWikiPage) -> float:
        if not normalized_query:
            return 1.0
        title = self._normalize_text(page.title)
        summary = self._normalize_text(page.summary)
        tags = self._normalize_text(" ".join(page.tags or []))
        body = self._normalize_text(page.body_text)
        haystack = f"{title} {summary} {tags} {body}".strip()
        if not haystack:
            return 0.0

        score = 0.0
        if normalized_query in title:
            score += 8.0
        if normalized_query in summary:
            score += 4.0
        if normalized_query in tags:
            score += 3.0
        if normalized_query in body:
            score += 1.0

        for token in query_tokens:
            if token in title:
                score += 3.0
            if token in summary:
                score += 2.0
            if token in tags:
                score += 2.0
            if token in body:
                score += 0.5
        return score

    @staticmethod
    def _normalize_root_storage_key(value: str) -> str:
        return str(value or "").strip().strip("/")

    @staticmethod
    def _normalize_page_path(value: str) -> str:
        path = str(value or "").strip().replace("\\", "/").strip("/")
        return str(PurePosixPath(path)) if path else ""

    @staticmethod
    def _has_unsafe_page_segments(value: str) -> bool:
        return any(
            part in {".", ".."}
            for part in str(value or "").replace("\\", "/").split("/")
        )

    @staticmethod
    def _collapse_relative_page_path(value: str) -> str:
        parts = []
        for part in str(value or "").strip().replace("\\", "/").strip("/").split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/".join(parts)

    def _relative_path(self, root_storage_key: str, storage_key: str) -> str:
        root = self._normalize_root_storage_key(root_storage_key)
        key = str(storage_key or "").strip().strip("/")
        if root and key.startswith(f"{root}/"):
            key = key[len(root) + 1:]
        return self._normalize_page_path(key)

    def _is_source_markdown_file(self, root_storage_key: str, storage_key: str) -> bool:
        path = self._relative_path(root_storage_key, storage_key)
        if not path.lower().endswith(".md"):
            return False
        parts = path.split("/")
        if not parts or parts[0].startswith("."):
            return False
        return path != self.INDEX_FILENAME

    @staticmethod
    def _normalize_tags(value: Any) -> list[str]:
        if isinstance(value, str):
            raw_tags = re.split(r"[,#]", value)
        elif isinstance(value, list):
            raw_tags = value
        else:
            raw_tags = []
        tags = []
        for tag in raw_tags:
            normalized = str(tag or "").strip().strip("#")
            if normalized and normalized not in tags:
                tags.append(normalized)
        return tags[:25]

    @staticmethod
    def _page_title(path: str, body: str, frontmatter: dict) -> str:
        title = str(frontmatter.get("title") or "").strip()
        if title:
            return title[:200]
        for line in body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()[:200] or "Untitled page"
        filename = os.path.splitext(os.path.basename(path))[0]
        return filename.replace("-", " ").replace("_", " ").strip().title() or "Untitled page"

    @staticmethod
    def _summary_from_body(body: str) -> str:
        lines = []
        for line in str(body or "").splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            lines.append(text)
            if len(" ".join(lines)) >= 220:
                break
        return " ".join(lines)[:500]

    @staticmethod
    def _normalize_wiki_status(value: str | None) -> KnowledgeWikiStatus:
        normalized = str(value or "").strip().lower()
        for status in KnowledgeWikiStatus:
            if normalized == status.value:
                return status
        return KnowledgeWikiStatus.PUBLISHED

    @staticmethod
    def _normalize_page_status(value: str | None) -> KnowledgeWikiPageStatus:
        normalized = str(value or "").strip().lower()
        for status in KnowledgeWikiPageStatus:
            if normalized == status.value:
                return status
        return KnowledgeWikiPageStatus.PUBLISHED

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @classmethod
    def _tokenize(cls, value: str | None) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", cls._normalize_text(value)))

    def _get_company(self, company_short_name: str) -> Company | None:
        return self.profile_repo.get_company_by_short_name(company_short_name)

    def serialize_wiki(self, wiki: KnowledgeWiki) -> dict:
        authoring_mode = self.wiki_authoring_mode(wiki)
        return {
            "id": wiki.id,
            "wiki_key": wiki.wiki_key,
            "name": wiki.name,
            "description": wiki.description,
            "root_storage_key": wiki.root_storage_key,
            "status": wiki.status.value if hasattr(wiki.status, "value") else str(wiki.status),
            "settings": self._normalize_wiki_settings(
                wiki.settings if isinstance(wiki.settings, dict) else {},
                existing_settings=None,
                default_authoring_mode=authoring_mode,
            ),
            "authoring_mode": authoring_mode,
            "editing_enabled": authoring_mode == self.AUTHORING_MODE_MANAGED,
            "storage_refresh_enabled": authoring_mode == self.AUTHORING_MODE_EXTERNAL_SYNC,
            "last_synced_at": wiki.last_synced_at.isoformat() if wiki.last_synced_at else None,
            "created_at": wiki.created_at.isoformat() if wiki.created_at else None,
            "updated_at": wiki.updated_at.isoformat() if wiki.updated_at else None,
        }

    @staticmethod
    def serialize_page(page: KnowledgeWikiPage, *, include_body: bool = False) -> dict:
        payload = {
            "id": page.id,
            "wiki_id": page.wiki_id,
            "path": page.path,
            "slug": page.slug,
            "title": page.title,
            "summary": page.summary or "",
            "source_storage_key": page.source_storage_key,
            "status": page.status.value if hasattr(page.status, "value") else str(page.status),
            "tags": page.tags or [],
            "owner": page.owner,
            "last_synced_at": page.last_synced_at.isoformat() if page.last_synced_at else None,
            "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        }
        if include_body:
            payload["body_text"] = page.body_text or ""
        return payload

    @staticmethod
    def serialize_page_revision(revision: KnowledgeWikiPageRevision) -> dict:
        markdown = str(revision.markdown or "")
        return {
            "id": revision.id,
            "wiki_id": revision.wiki_id,
            "page_id": revision.page_id,
            "action": revision.action,
            "path": revision.path,
            "previous_path": revision.previous_path,
            "title": revision.title,
            "checksum": revision.checksum,
            "edited_by": revision.edited_by,
            "change_summary": revision.change_summary,
            "metadata": revision.metadata_json or {},
            "markdown_size": len(markdown),
            "created_at": revision.created_at.isoformat() if revision.created_at else None,
        }

    @staticmethod
    def serialize_sync_run(run) -> dict:
        return {
            "id": run.id,
            "wiki_id": run.wiki_id,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "pages_seen": run.pages_seen,
            "pages_indexed": run.pages_indexed,
            "pages_failed": run.pages_failed,
            "errors": run.errors or [],
            "metadata": run.metadata_json or {},
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
