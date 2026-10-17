# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import hashlib
from datetime import datetime

from injector import inject
from sqlalchemy import or_, text

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (
    KnowledgeWiki,
    KnowledgeWikiPage,
    KnowledgeWikiPageIndex,
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

    def get_page_by_id(self, wiki_id: int, page_id: int) -> KnowledgeWikiPage | None:
        if not wiki_id or not page_id:
            return None
        return (
            self.session.query(KnowledgeWikiPage)
            .filter_by(wiki_id=wiki_id, id=page_id)
            .first()
        )

    def get_pages_by_ids(self, wiki_ids: list[int], page_ids: list[int]) -> dict[int, KnowledgeWikiPage]:
        if not wiki_ids or not page_ids:
            return {}
        pages = (
            self.session.query(KnowledgeWikiPage)
            .filter(KnowledgeWikiPage.wiki_id.in_(list(wiki_ids)), KnowledgeWikiPage.id.in_(list(page_ids)))
            .all()
        )
        return {page.id: page for page in pages}

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
        access_tags: list[str] | None = None,
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
            # None means "leave the stored labels alone": a wiki with no access
            # manifest must not lose its labels because a page's markdown changed.
            # An empty list is a real value and does clear them.
            if access_tags is not None:
                page.access_tags = list(access_tags)
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
                access_tags=list(access_tags or []),
                owner=owner,
                source_meta=source_meta or {},
                last_synced_at=last_synced_at,
            )
            self.session.add(page)
        self.session.commit()
        self.index_page(page)
        return page

    def save_page(self, page: KnowledgeWikiPage) -> KnowledgeWikiPage:
        self.session.add(page)
        self.session.commit()
        self.index_page(page)
        return page

    def delete_page(self, wiki_id: int, path: str) -> KnowledgeWikiPage | None:
        page = self.get_page_by_path(wiki_id, path)
        if page is None:
            return None
        self.session.query(KnowledgeWikiPageIndex).filter(KnowledgeWikiPageIndex.page_id == page.id).delete()
        self.session.delete(page)
        self.session.commit()
        return page

    # =====================================================================
    # Search index (iat_knowledge_wiki_page_index)
    # =====================================================================

    # What the word branch searches; the meaning branch embeds the same text, cut.
    INDEX_TEXT_CHARS = 60000

    @classmethod
    def page_search_text(cls, page: KnowledgeWikiPage) -> str:
        parts = [page.title or "", page.summary or "", " ".join(str(t) for t in (page.tags or [])), page.body_text or ""]
        return "\n".join(part.strip() for part in parts if str(part or "").strip())[:cls.INDEX_TEXT_CHARS]

    def index_page(self, page: KnowledgeWikiPage) -> KnowledgeWikiPageIndex:
        """Writes the page's search text; a changed text clears the embedding so it is computed again."""
        search_text = self.page_search_text(page)
        content_hash = hashlib.sha256(search_text.encode("utf-8")).hexdigest()
        row = self.session.query(KnowledgeWikiPageIndex).filter(KnowledgeWikiPageIndex.page_id == page.id).first()
        if row is None:
            row = KnowledgeWikiPageIndex(page_id=page.id, wiki_id=page.wiki_id, company_id=page.company_id)
            self.session.add(row)
        elif row.content_hash == content_hash and row.wiki_id == page.wiki_id:
            return row
        row.wiki_id = page.wiki_id
        row.search_text = search_text
        row.content_hash = content_hash
        if row.embedded_hash != content_hash:
            row.embedding = None
            row.embedded_hash = None
        self.session.commit()
        return row

    def list_pages_to_embed(self, limit: int = 100, company_id: int | None = None) -> list[KnowledgeWikiPageIndex]:
        query = (
            self.session.query(KnowledgeWikiPageIndex)
            .join(KnowledgeWikiPage, KnowledgeWikiPage.id == KnowledgeWikiPageIndex.page_id)
            .filter(KnowledgeWikiPage.status != KnowledgeWikiPageStatus.ARCHIVED)
            .filter(or_(KnowledgeWikiPageIndex.embedded_hash.is_(None),
                        KnowledgeWikiPageIndex.embedded_hash != KnowledgeWikiPageIndex.content_hash))
        )
        if company_id:
            query = query.filter(KnowledgeWikiPageIndex.company_id == company_id)
        return query.order_by(KnowledgeWikiPageIndex.updated_at.asc()).limit(limit).all()

    def list_unindexed_pages(self, limit: int = 500) -> list[KnowledgeWikiPage]:
        """Pages written before the index existed (the backfill)."""
        return (
            self.session.query(KnowledgeWikiPage)
            .outerjoin(KnowledgeWikiPageIndex, KnowledgeWikiPageIndex.page_id == KnowledgeWikiPage.id)
            .filter(KnowledgeWikiPageIndex.id.is_(None))
            .filter(KnowledgeWikiPage.status != KnowledgeWikiPageStatus.ARCHIVED)
            .limit(limit)
            .all()
        )

    def set_page_embedding(self, row: KnowledgeWikiPageIndex, embedding: list[float], embedded_hash: str) -> None:
        row.embedding = embedding
        row.embedded_hash = embedded_hash
        self.session.commit()

    def is_postgres(self) -> bool:
        bind = self.session.get_bind()
        return getattr(getattr(bind, "dialect", None), "name", "") == "postgresql"

    RRF_K = 60

    def hybrid_search_pages(self, wiki_ids: list[int], query_text: str, query_embedding: list[float] | None,
                            candidates: int = 40) -> list[tuple[int, float]]:
        """
        (page_id, rrf_score) of the best pages of these wikis, best first: by
        words (Postgres full text, 'simple', terms OR'ed, the GIN index) and, when
        there is a query embedding, by meaning (pages whose embedding has its
        size), fused by Reciprocal Rank Fusion. Archived pages are left out.
        Postgres only.
        """
        if not wiki_ids:
            return []
        tsvector = "to_tsvector('simple'::regconfig, i.search_text)"
        tsquery = "replace(plainto_tsquery('simple'::regconfig, :text_terms)::text, ' & ', ' | ')::tsquery"
        params = {"wiki_ids": list(wiki_ids), "text_terms": query_text or "", "candidates": int(candidates),
                  "archived": KnowledgeWikiPageStatus.ARCHIVED.name}
        branches = [f"""
                SELECT page_id, ROW_NUMBER() OVER (ORDER BY text_rank DESC, page_id ASC) AS rank
                FROM (
                    SELECT i.page_id, ts_rank_cd({tsvector}, terms.q) AS text_rank
                    FROM iat_knowledge_wiki_page_index i
                    JOIN iat_knowledge_wiki_pages p ON p.id = i.page_id,
                         (SELECT {tsquery} AS q) terms
                    WHERE i.wiki_id = ANY(:wiki_ids) AND p.status::text <> :archived
                      AND {tsvector} @@ terms.q
                    ORDER BY text_rank DESC
                    LIMIT :candidates
                ) words"""]
        if query_embedding:
            dims = len(query_embedding)
            if 0 < dims <= 2000:
                params["query_embedding"] = str(list(query_embedding))
                branches.append(f"""
                SELECT page_id, ROW_NUMBER() OVER (ORDER BY distance ASC, page_id ASC) AS rank
                FROM (
                    SELECT i.page_id,
                           i.embedding::vector({dims}) <=> CAST(:query_embedding AS vector({dims})) AS distance
                    FROM iat_knowledge_wiki_page_index i
                    JOIN iat_knowledge_wiki_pages p ON p.id = i.page_id
                    WHERE i.wiki_id = ANY(:wiki_ids) AND p.status::text <> :archived
                      AND i.embedding IS NOT NULL AND vector_dims(i.embedding) = {dims}
                    ORDER BY distance ASC
                    LIMIT :candidates
                ) meaning""")
        union = " UNION ALL ".join(f"({branch})" for branch in branches)
        sql = f"""
            SELECT page_id, SUM(1.0 / ({self.RRF_K} + rank)) AS rrf_score
            FROM ({union}) hits
            GROUP BY page_id
            ORDER BY rrf_score DESC, page_id ASC
            LIMIT :candidates
        """
        rows = self.session.execute(text(sql), params).fetchall()
        return [(int(row[0]), float(row[1])) for row in rows]

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

    def get_page_revision(self, wiki_id: int, revision_id: int) -> KnowledgeWikiPageRevision | None:
        if not wiki_id or not revision_id:
            return None
        return (
            self.session.query(KnowledgeWikiPageRevision)
            .filter_by(wiki_id=wiki_id, id=revision_id)
            .first()
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
