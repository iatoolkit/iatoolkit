# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from sqlalchemy import or_, func

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (
    MemoryCapture,
    MemoryCaptureStatus,
    MemoryItem,
    MemoryItemStatus,
    MemoryPage,
    MemoryPageSource,
)


class MemoryRepo:
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

    def get_item(self, company_id: int, user_identifier: str, item_id: int) -> MemoryItem | None:
        if not company_id or not user_identifier or not item_id:
            return None
        return (
            self.session.query(MemoryItem)
            .filter_by(company_id=company_id, user_identifier=user_identifier, id=item_id)
            .first()
        )

    def get_capture(self, company_id: int, user_identifier: str, capture_id: int) -> MemoryCapture | None:
        if not company_id or not user_identifier or not capture_id:
            return None
        return (
            self.session.query(MemoryCapture)
            .filter_by(company_id=company_id, user_identifier=user_identifier, id=capture_id)
            .first()
        )

    def list_capture_items(self, capture_id: int) -> list[MemoryItem]:
        if not capture_id:
            return []
        return (
            self.session.query(MemoryItem)
            .filter_by(capture_id=capture_id)
            .order_by(MemoryItem.created_at.asc(), MemoryItem.id.asc())
            .all()
        )

    def list_items_by_ids(self, company_id: int, user_identifier: str, item_ids: list[int]) -> list[MemoryItem]:
        normalized_ids = [item_id for item_id in (item_ids or []) if isinstance(item_id, int)]
        if not company_id or not user_identifier or not normalized_ids:
            return []
        return (
            self.session.query(MemoryItem)
            .filter(
                MemoryItem.company_id == company_id,
                MemoryItem.user_identifier == user_identifier,
                MemoryItem.id.in_(normalized_ids),
            )
            .all()
        )

    def list_recent_captures(self, company_id: int, user_identifier: str, limit: int = 25) -> list[MemoryCapture]:
        if not company_id or not user_identifier:
            return []
        return (
            self.session.query(MemoryCapture)
            .filter_by(company_id=company_id, user_identifier=user_identifier)
            .order_by(MemoryCapture.created_at.desc(), MemoryCapture.id.desc())
            .limit(limit)
            .all()
        )

    def list_recent_items(self, company_id: int, user_identifier: str, limit: int = 25) -> list[MemoryItem]:
        if not company_id or not user_identifier:
            return []
        return (
            self.session.query(MemoryItem)
            .filter_by(company_id=company_id, user_identifier=user_identifier)
            .order_by(MemoryItem.created_at.desc(), MemoryItem.id.desc())
            .limit(limit)
            .all()
        )

    def list_memory_user_identifiers(self, company_id: int) -> list[str]:
        if not company_id:
            return []

        identifiers = set()
        for model in (MemoryCapture, MemoryPage, MemoryItem):
            rows = (
                self.session.query(model.user_identifier)
                .filter(model.company_id == company_id)
                .distinct()
                .all()
            )
            for (user_identifier,) in rows:
                normalized = str(user_identifier or "").strip()
                if normalized:
                    identifiers.add(normalized)
        return sorted(identifiers)

    def get_pending_captures(self, company_id: int, user_identifier: str, limit: int = 25) -> list[MemoryCapture]:
        if not company_id or not user_identifier:
            return []
        return (
            self.session.query(MemoryCapture)
            .filter_by(
                company_id=company_id,
                user_identifier=user_identifier,
                status=MemoryCaptureStatus.PENDING,
            )
            .order_by(MemoryCapture.created_at.asc(), MemoryCapture.id.asc())
            .limit(limit)
            .all()
        )

    def get_pending_items(self, company_id: int, user_identifier: str, limit: int = 25) -> list[MemoryItem]:
        if not company_id or not user_identifier:
            return []
        return (
            self.session.query(MemoryItem)
            .filter_by(
                company_id=company_id,
                user_identifier=user_identifier,
                status=MemoryItemStatus.PENDING,
            )
            .order_by(MemoryItem.created_at.asc(), MemoryItem.id.asc())
            .limit(limit)
            .all()
        )

    def get_page(self, company_id: int, user_identifier: str, page_id: int) -> MemoryPage | None:
        if not company_id or not user_identifier or not page_id:
            return None
        return (
            self.session.query(MemoryPage)
            .filter_by(company_id=company_id, user_identifier=user_identifier, id=page_id)
            .first()
        )

    def get_page_by_slug(self, company_id: int, user_identifier: str, slug: str) -> MemoryPage | None:
        if not company_id or not user_identifier or not slug:
            return None
        return (
            self.session.query(MemoryPage)
            .filter_by(company_id=company_id, user_identifier=user_identifier, slug=slug)
            .first()
        )

    def list_pages(self, company_id: int, user_identifier: str, limit: int = 50) -> list[MemoryPage]:
        if not company_id or not user_identifier:
            return []
        return (
            self.session.query(MemoryPage)
            .filter_by(company_id=company_id, user_identifier=user_identifier)
            .order_by(MemoryPage.updated_at.desc(), MemoryPage.id.desc())
            .limit(limit)
            .all()
        )

    def search_pages(self, company_id: int, user_identifier: str, query: str, limit: int = 5) -> list[MemoryPage]:
        if not company_id or not user_identifier:
            return []

        base_query = (
            self.session.query(MemoryPage)
            .filter_by(company_id=company_id, user_identifier=user_identifier)
        )

        normalized_query = str(query or "").strip().lower()
        if normalized_query:
            like_query = f"%{normalized_query[:180]}%"
            base_query = base_query.filter(
                or_(
                    func.lower(MemoryPage.title).like(like_query),
                    func.lower(MemoryPage.summary).like(like_query),
                )
            )

        return (
            base_query
            .order_by(MemoryPage.updated_at.desc(), MemoryPage.id.desc())
            .limit(limit)
            .all()
        )

    def create_or_update_page(self,
                              company_id: int,
                              user_identifier: str,
                              title: str,
                              slug: str,
                              wiki_path: str,
                              summary: str | None = None,
                              page_id: int | None = None) -> MemoryPage:
        page = None
        if page_id:
            page = self.get_page(company_id, user_identifier, page_id)
        if page is None:
            page = self.get_page_by_slug(company_id, user_identifier, slug)

        if page:
            page.title = title
            page.slug = slug
            page.summary = summary
            page.wiki_path = wiki_path
        else:
            page = MemoryPage(
                company_id=company_id,
                user_identifier=user_identifier,
                title=title,
                slug=slug,
                summary=summary,
                wiki_path=wiki_path,
            )
            self.session.add(page)

        self.session.commit()
        return page

    def replace_page_sources(self, page_id: int, item_ids: list[int]) -> None:
        if not page_id:
            return

        normalized_ids = []
        for item_id in item_ids or []:
            if isinstance(item_id, int) and item_id not in normalized_ids:
                normalized_ids.append(item_id)

        self.session.query(MemoryPageSource).filter_by(memory_page_id=page_id).delete(synchronize_session=False)

        for item_id in normalized_ids:
            self.session.add(MemoryPageSource(memory_page_id=page_id, memory_item_id=item_id))

        self.session.commit()

    def list_page_sources(self, page_id: int) -> list[MemoryPageSource]:
        if not page_id:
            return []
        return (
            self.session.query(MemoryPageSource)
            .filter_by(memory_page_id=page_id)
            .order_by(MemoryPageSource.id.asc())
            .all()
        )

    def list_pages_for_item(self, item_id: int) -> list[MemoryPage]:
        if not item_id:
            return []
        return (
            self.session.query(MemoryPage)
            .join(MemoryPageSource, MemoryPageSource.memory_page_id == MemoryPage.id)
            .filter(MemoryPageSource.memory_item_id == item_id)
            .order_by(MemoryPage.updated_at.desc(), MemoryPage.id.desc())
            .all()
        )

    def list_pages_for_items(self, item_ids: list[int]) -> list[MemoryPage]:
        normalized_ids = [item_id for item_id in (item_ids or []) if isinstance(item_id, int)]
        if not normalized_ids:
            return []
        return (
            self.session.query(MemoryPage)
            .join(MemoryPageSource, MemoryPageSource.memory_page_id == MemoryPage.id)
            .filter(MemoryPageSource.memory_item_id.in_(normalized_ids))
            .distinct()
            .order_by(MemoryPage.updated_at.desc(), MemoryPage.id.desc())
            .all()
        )

    def delete_page(self, page: MemoryPage) -> None:
        if not page:
            return
        self.session.delete(page)
        self.session.commit()

    def delete_capture(self, capture: MemoryCapture) -> None:
        if not capture:
            return
        self.session.delete(capture)
        self.session.commit()

    def delete_item(self, item: MemoryItem) -> None:
        if not item:
            return
        self.session.delete(item)
        self.session.commit()
