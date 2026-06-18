# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from datetime import datetime

from injector import inject
from sqlalchemy import or_

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (
    KnowledgeWiki,
    KnowledgeWikiPage,
    KnowledgeWikiPageRevision,
    KnowledgeWikiPageStatus,
    KnowledgeWikiStatus,
    KnowledgeWikiSyncRun,
    KnowledgeWikiSyncStatus,
)


class KnowledgeWikiRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    def get_wiki_by_key(self, company_id: int, wiki_key: str) -> KnowledgeWiki | None:
        if not company_id or not wiki_key:
            return None
        return (
            self.session.query(KnowledgeWiki)
            .filter_by(company_id=company_id, wiki_key=wiki_key)
            .first()
        )

    def get_wiki(self, company_id: int, wiki_id: int) -> KnowledgeWiki | None:
        if not company_id or not wiki_id:
            return None
        return (
            self.session.query(KnowledgeWiki)
            .filter_by(company_id=company_id, id=wiki_id)
            .first()
        )

    def list_wikis(self, company_id: int, *, include_archived: bool = False) -> list[KnowledgeWiki]:
        if not company_id:
            return []
        query = self.session.query(KnowledgeWiki).filter_by(company_id=company_id)
        if not include_archived:
            query = query.filter(KnowledgeWiki.status != KnowledgeWikiStatus.ARCHIVED)
        return query.order_by(KnowledgeWiki.name.asc(), KnowledgeWiki.id.asc()).all()

    def create_or_update_wiki(
        self,
        *,
        company_id: int,
        wiki_key: str,
        name: str,
        root_storage_key: str,
        description: str | None = None,
        status: KnowledgeWikiStatus = KnowledgeWikiStatus.PUBLISHED,
        settings: dict | None = None,
    ) -> KnowledgeWiki:
        wiki = self.get_wiki_by_key(company_id, wiki_key)
        if wiki:
            wiki.name = name
            wiki.description = description
            wiki.root_storage_key = root_storage_key
            wiki.status = status
            wiki.settings = settings or {}
        else:
            wiki = KnowledgeWiki(
                company_id=company_id,
                wiki_key=wiki_key,
                name=name,
                description=description,
                root_storage_key=root_storage_key,
                status=status,
                settings=settings or {},
            )
            self.session.add(wiki)
        self.session.commit()
        return wiki

    def delete_wiki(self, company_id: int, wiki_key: str) -> KnowledgeWiki | None:
        wiki = self.get_wiki_by_key(company_id, wiki_key)
        if wiki is None:
            return None
        self.session.delete(wiki)
        self.session.commit()
        return wiki

    def get_page_by_path(self, wiki_id: int, path: str) -> KnowledgeWikiPage | None:
        if not wiki_id or not path:
            return None
        return (
            self.session.query(KnowledgeWikiPage)
            .filter_by(wiki_id=wiki_id, path=path)
            .first()
        )

    def get_page_by_slug(self, wiki_id: int, slug: str) -> KnowledgeWikiPage | None:
        if not wiki_id or not slug:
            return None
        return (
            self.session.query(KnowledgeWikiPage)
            .filter_by(wiki_id=wiki_id, slug=slug)
            .first()
        )

    def list_pages(
        self,
        wiki_id: int,
        *,
        include_archived: bool = False,
        limit: int = 500,
    ) -> list[KnowledgeWikiPage]:
        if not wiki_id:
            return []
        query = self.session.query(KnowledgeWikiPage).filter_by(wiki_id=wiki_id)
        if not include_archived:
            query = query.filter(KnowledgeWikiPage.status != KnowledgeWikiPageStatus.ARCHIVED)
        return (
            query
            .order_by(KnowledgeWikiPage.path.asc(), KnowledgeWikiPage.id.asc())
            .limit(limit)
            .all()
        )

    def create_or_update_page(
        self,
        *,
        company_id: int,
        wiki_id: int,
        path: str,
        slug: str,
        title: str,
        source_storage_key: str,
        summary: str | None = None,
        body_text: str | None = None,
        status: KnowledgeWikiPageStatus = KnowledgeWikiPageStatus.PUBLISHED,
        tags: list[str] | None = None,
        owner: str | None = None,
        source_meta: dict | None = None,
        last_synced_at: datetime | None = None,
    ) -> KnowledgeWikiPage:
        page = self.get_page_by_path(wiki_id, path)
        if page is None:
            page = self.get_page_by_slug(wiki_id, slug)

        if page:
            page.path = path
            page.slug = slug
            page.title = title
            page.summary = summary
            page.body_text = body_text
            page.source_storage_key = source_storage_key
            page.status = status
            page.tags = tags or []
            page.owner = owner
            page.source_meta = source_meta or {}
            page.last_synced_at = last_synced_at
        else:
            page = KnowledgeWikiPage(
                company_id=company_id,
                wiki_id=wiki_id,
                path=path,
                slug=slug,
                title=title,
                summary=summary,
                body_text=body_text,
                source_storage_key=source_storage_key,
                status=status,
                tags=tags or [],
                owner=owner,
                source_meta=source_meta or {},
                last_synced_at=last_synced_at,
            )
            self.session.add(page)
        self.session.commit()
        return page

    def save_page(self, page: KnowledgeWikiPage) -> KnowledgeWikiPage:
        self.session.add(page)
        self.session.commit()
        return page

    def delete_page(self, wiki_id: int, path: str) -> KnowledgeWikiPage | None:
        page = self.get_page_by_path(wiki_id, path)
        if page is None:
            return None
        self.session.delete(page)
        self.session.commit()
        return page

    def create_page_revision(
        self,
        *,
        company_id: int,
        wiki_id: int,
        page_id: int | None,
        action: str,
        path: str,
        previous_path: str | None = None,
        title: str | None = None,
        markdown: str | None = None,
        checksum: str | None = None,
        edited_by: str | None = None,
        change_summary: str | None = None,
        metadata_json: dict | None = None,
    ) -> KnowledgeWikiPageRevision:
        revision = KnowledgeWikiPageRevision(
            company_id=company_id,
            wiki_id=wiki_id,
            page_id=page_id,
            action=action,
            path=path,
            previous_path=previous_path,
            title=title,
            markdown=markdown,
            checksum=checksum,
            edited_by=edited_by,
            change_summary=change_summary,
            metadata_json=metadata_json or {},
        )
        self.session.add(revision)
        self.session.commit()
        return revision

    def list_page_revisions(
        self,
        wiki_id: int,
        *,
        path: str | None = None,
        page_id: int | None = None,
        limit: int = 50,
    ) -> list[KnowledgeWikiPageRevision]:
        if not wiki_id:
            return []
        query = self.session.query(KnowledgeWikiPageRevision).filter_by(wiki_id=wiki_id)
        filters = []
        if page_id:
            filters.append(KnowledgeWikiPageRevision.page_id == page_id)
        if path:
            filters.extend([
                KnowledgeWikiPageRevision.path == path,
                KnowledgeWikiPageRevision.previous_path == path,
            ])
        if filters:
            query = query.filter(or_(*filters))
        bounded_limit = min(max(int(limit or 50), 1), 200)
        return (
            query
            .order_by(KnowledgeWikiPageRevision.created_at.desc(), KnowledgeWikiPageRevision.id.desc())
            .limit(bounded_limit)
            .all()
        )

    def archive_pages_not_in_paths(self, wiki_id: int, paths: set[str]) -> int:
        if not wiki_id:
            return 0
        query = self.session.query(KnowledgeWikiPage).filter_by(wiki_id=wiki_id)
        if paths:
            query = query.filter(~KnowledgeWikiPage.path.in_(paths))
        rows = query.all()
        changed = 0
        for page in rows:
            if page.status != KnowledgeWikiPageStatus.ARCHIVED:
                page.status = KnowledgeWikiPageStatus.ARCHIVED
                changed += 1
        if changed:
            self.session.commit()
        return changed

    def create_sync_run(
        self,
        *,
        company_id: int,
        wiki_id: int,
        metadata_json: dict | None = None,
    ) -> KnowledgeWikiSyncRun:
        run = KnowledgeWikiSyncRun(
            company_id=company_id,
            wiki_id=wiki_id,
            status=KnowledgeWikiSyncStatus.RUNNING,
            metadata_json=metadata_json or {},
        )
        self.session.add(run)
        self.session.commit()
        return run

    def save_sync_run(self, run: KnowledgeWikiSyncRun) -> KnowledgeWikiSyncRun:
        self.session.add(run)
        self.session.commit()
        return run
