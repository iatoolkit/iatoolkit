# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from injector import inject

from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo
from iatoolkit.repositories.models import (
    Company,
    KnowledgeWiki,
    KnowledgeWikiPage,
    KnowledgeWikiPageStatus,
    KnowledgeWikiStatus,
    KnowledgeWikiSyncStatus,
)
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.storage_service import StorageService


class TenantKnowledgeWikiService:
    GENERATED_FOLDER = ".iatoolkit"
    INDEX_FILENAME = "index.md"

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
        wiki = self.knowledge_wiki_repo.create_or_update_wiki(
            company_id=company.id,
            wiki_key=normalized_key,
            name=str(name or normalized_key).strip(),
            description=str(description or "").strip() or None,
            root_storage_key=self._normalize_root_storage_key(
                root_storage_key or self.default_root_storage_key(company_short_name, normalized_key)
            ),
            status=wiki_status,
            settings=settings if isinstance(settings, dict) else {},
        )
        return {"status": "success", "wiki": self.serialize_wiki(wiki)}

    def list_wikis(self, company_short_name: str, *, include_archived: bool = False) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "wikis": [], "error_message": "company not found"}
        wikis = self.knowledge_wiki_repo.list_wikis(company.id, include_archived=include_archived)
        return {"status": "success", "wikis": [self.serialize_wiki(wiki) for wiki in wikis]}

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
        pages = self.knowledge_wiki_repo.list_pages(wiki.id, include_archived=False, limit=1000)
        entries = [self.serialize_page(page, include_body=False) for page in pages]
        return {
            "status": "success",
            "wiki": self.serialize_wiki(wiki),
            "entries": entries,
            "markdown": self.markdown_wiki_service.render_generic_index(entries, title=wiki.name),
        }

    def get_page(self, company_short_name: str, *, wiki_key: str, path: str) -> dict:
        company = self._get_company(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        wiki = self.knowledge_wiki_repo.get_wiki_by_key(company.id, self.normalize_wiki_key(wiki_key))
        if not wiki:
            return {"status": "error", "error_message": "wiki not found"}

        normalized_path = self._normalize_page_path(path)
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
                    settings=existing.settings or {},
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
            settings={},
        )

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
            "source_meta": source_meta,
        }

    def _write_generated_index(self, company_short_name: str, wiki: KnowledgeWiki) -> str:
        index_payload = self.get_index(company_short_name, wiki_key=wiki.wiki_key)
        markdown = index_payload.get("markdown") or ""
        storage_key = self.markdown_wiki_service.join_storage_path(
            wiki.root_storage_key,
            self.GENERATED_FOLDER,
            self.INDEX_FILENAME,
        )
        return self.markdown_wiki_service.write_markdown(company_short_name, storage_key, markdown)

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

    @staticmethod
    def _normalize_root_storage_key(value: str) -> str:
        return str(value or "").strip().strip("/")

    @staticmethod
    def _normalize_page_path(value: str) -> str:
        path = str(value or "").strip().replace("\\", "/").strip("/")
        return str(PurePosixPath(path)) if path else ""

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

    def _get_company(self, company_short_name: str) -> Company | None:
        return self.profile_repo.get_company_by_short_name(company_short_name)

    @staticmethod
    def serialize_wiki(wiki: KnowledgeWiki) -> dict:
        return {
            "id": wiki.id,
            "wiki_key": wiki.wiki_key,
            "name": wiki.name,
            "description": wiki.description,
            "root_storage_key": wiki.root_storage_key,
            "status": wiki.status.value if hasattr(wiki.status, "value") else str(wiki.status),
            "settings": wiki.settings or {},
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
