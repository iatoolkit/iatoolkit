# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The meaning half of the wiki page search index (iat_knowledge_wiki_page_index).

KnowledgeWikiRepo writes each page's search text when the page is written; a
changed text clears its embedding. This service computes the missing ones, in
batches, with the company's embedding model (the RAG's), and backfills the
pages written before the index existed. Enterprise runs it from a platform job;
until a page has its embedding it is found by its words only.
"""

from __future__ import annotations

import logging

from injector import inject

from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.embedding_service import EmbeddingService


class WikiPageIndexService:
    BATCH = 100
    BACKFILL_BATCH = 500
    # What is embedded of a page: the start of its text (title, summary, body).
    EMBED_CHARS = 8000

    @inject
    def __init__(self, knowledge_wiki_repo: KnowledgeWikiRepo, embedding_service: EmbeddingService,
                 profile_repo: ProfileRepo):
        self.repo = knowledge_wiki_repo
        self.embedding_service = embedding_service
        self.profile_repo = profile_repo

    def refresh(self, limit: int | None = None) -> dict:
        """Backfills the pages without an index row, then embeds the pages whose text changed."""
        backfilled = 0
        for page in self.repo.list_unindexed_pages(limit=self.BACKFILL_BATCH):
            self.repo.index_page(page)
            backfilled += 1
        embedded, failed = 0, []
        companies: dict[int, str | None] = {}
        for row in self.repo.list_pages_to_embed(limit=limit or self.BATCH):
            if row.company_id not in companies:
                company = self.profile_repo.get_company_by_id(row.company_id)
                companies[row.company_id] = getattr(company, "short_name", None)
            short_name = companies[row.company_id]
            if not short_name or not row.search_text:
                continue
            try:
                embedding = self.embedding_service.embed_text(short_name, row.search_text[:self.EMBED_CHARS])
                self.repo.set_page_embedding(row, list(embedding), row.content_hash)
                embedded += 1
            except Exception as exc:
                self.repo.rollback()
                logging.warning("Wiki page %s could not be embedded: %s", row.page_id, exc)
                failed.append({"page_id": row.page_id, "error": str(exc)[:300]})
        return {"status": "completed", "backfilled": backfilled, "embedded": embedded, "failed": failed}

    def query_embedding(self, company_short_name: str, query: str) -> list[float] | None:
        """The query's embedding for the meaning branch, or None (the search goes by words only)."""
        if not str(query or "").strip():
            return None
        try:
            return list(self.embedding_service.embed_text(company_short_name, query))
        except Exception as exc:
            logging.warning("Wiki search query could not be embedded for %s: %s", company_short_name, exc)
            return None
