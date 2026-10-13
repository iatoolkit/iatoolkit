# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (
    MemoryCapture,
    MemoryCaptureStatus,
    MemoryItem,
    MemoryWikiPageSource,
)


class MemoryRepo:
    """
    Memoria is the company's memory: captures and items belong to the company,
    and `user_identifier` on them records who saved them (the author). Methods
    that take a `user_identifier` restrict to that author's own captures, which
    is what a user may edit or delete; the rest are company-wide.
    """

    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    def create_item(self, item: MemoryItem) -> MemoryItem:
        self.session.add(item)
        self.session.commit()
        return item

    def create_capture(self, capture: MemoryCapture) -> MemoryCapture:
        self.session.add(capture)
        self.session.commit()
        return capture

    def save_capture(self, capture: MemoryCapture) -> MemoryCapture:
        self.session.add(capture)
        self.session.commit()
        return capture

    def save_item(self, item: MemoryItem) -> MemoryItem:
        self.session.add(item)
        self.session.commit()
        return item

    def get_item(self, company_id: int, item_id: int, user_identifier: str | None = None) -> MemoryItem | None:
        if not company_id or not item_id:
            return None
        query = self.session.query(MemoryItem).filter_by(company_id=company_id, id=item_id)
        if user_identifier is not None:
            query = query.filter_by(user_identifier=user_identifier)
        return query.first()

    def get_capture(self, company_id: int, capture_id: int, user_identifier: str | None = None) -> MemoryCapture | None:
        if not company_id or not capture_id:
            return None
        query = self.session.query(MemoryCapture).filter_by(company_id=company_id, id=capture_id)
        if user_identifier is not None:
            query = query.filter_by(user_identifier=user_identifier)
        return query.first()

    def list_capture_items(self, capture_id: int) -> list[MemoryItem]:
        if not capture_id:
            return []
        return (
            self.session.query(MemoryItem)
            .filter_by(capture_id=capture_id)
            .order_by(MemoryItem.created_at.asc(), MemoryItem.id.asc())
            .all()
        )

    def list_items_by_ids(self, company_id: int, item_ids: list[int]) -> list[MemoryItem]:
        normalized_ids = [item_id for item_id in (item_ids or []) if isinstance(item_id, int)]
        if not company_id or not normalized_ids:
            return []
        return (
            self.session.query(MemoryItem)
            .filter(
                MemoryItem.company_id == company_id,
                MemoryItem.id.in_(normalized_ids),
            )
            .all()
        )

    def list_recent_captures(self,
                             company_id: int,
                             user_identifier: str | None = None,
                             limit: int = 25) -> list[MemoryCapture]:
        if not company_id:
            return []
        query = self.session.query(MemoryCapture).filter_by(company_id=company_id)
        if user_identifier is not None:
            query = query.filter_by(user_identifier=user_identifier)
        return (
            query
            .order_by(MemoryCapture.created_at.desc(), MemoryCapture.id.desc())
            .limit(limit)
            .all()
        )

    def list_recent_items(self, company_id: int, limit: int = 25) -> list[MemoryItem]:
        if not company_id:
            return []
        return (
            self.session.query(MemoryItem)
            .filter_by(company_id=company_id)
            .order_by(MemoryItem.created_at.desc(), MemoryItem.id.desc())
            .limit(limit)
            .all()
        )

    def get_pending_captures(self, company_id: int, limit: int = 25) -> list[MemoryCapture]:
        if not company_id:
            return []
        return (
            self.session.query(MemoryCapture)
            .filter_by(company_id=company_id, status=MemoryCaptureStatus.PENDING)
            .order_by(MemoryCapture.created_at.asc(), MemoryCapture.id.asc())
            .limit(limit)
            .all()
        )

    def add_page_sources(self, company_id: int, wiki_page_id: int, item_ids: list[int]) -> None:
        """Links items to a wiki page, keeping the links it already has."""
        if not company_id or not wiki_page_id:
            return
        existing = set(self.list_page_source_item_ids(wiki_page_id))
        for item_id in item_ids or []:
            if isinstance(item_id, int) and item_id not in existing:
                self.session.add(MemoryWikiPageSource(
                    company_id=company_id,
                    wiki_page_id=wiki_page_id,
                    memory_item_id=item_id,
                ))
                existing.add(item_id)
        self.session.commit()

    def list_page_source_item_ids(self, wiki_page_id: int) -> list[int]:
        if not wiki_page_id:
            return []
        rows = (
            self.session.query(MemoryWikiPageSource.memory_item_id)
            .filter_by(wiki_page_id=wiki_page_id)
            .order_by(MemoryWikiPageSource.id.asc())
            .all()
        )
        return [item_id for (item_id,) in rows]

    def list_page_ids_for_items(self, item_ids: list[int]) -> list[int]:
        normalized_ids = [item_id for item_id in (item_ids or []) if isinstance(item_id, int)]
        if not normalized_ids:
            return []
        rows = (
            self.session.query(MemoryWikiPageSource.wiki_page_id)
            .filter(MemoryWikiPageSource.memory_item_id.in_(normalized_ids))
            .distinct()
            .all()
        )
        return [page_id for (page_id,) in rows]

    def delete_page_sources_for_item(self, item_id: int) -> None:
        """Unlinks an item from every page. The pages themselves are never touched."""
        if not item_id:
            return
        (
            self.session.query(MemoryWikiPageSource)
            .filter_by(memory_item_id=item_id)
            .delete(synchronize_session=False)
        )
        self.session.commit()

    def delete_capture(self, capture: MemoryCapture) -> None:
        if not capture:
            return
        self.session.delete(capture)
        self.session.commit()

    def delete_item(self, item: MemoryItem) -> None:
        if not item:
            return
        self.delete_page_sources_for_item(item.id)
        self.session.delete(item)
        self.session.commit()
