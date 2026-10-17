# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from collections import Counter
from datetime import datetime

from injector import inject
from sqlalchemy import case, func

from iatoolkit.common import memory_tools
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import MemoryUsageEvent


class MemoryUsageRepo:
    """iat_memory_usage_events: one row per use of the company's knowledge (Fase 2)."""

    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def add(self, event: MemoryUsageEvent) -> None:
        self.session.add(event)
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def summarize(self, company_id: int, start: datetime, end: datetime) -> dict:
        """What the company's knowledge was used for in [start, end), by tool, channel and day."""
        base = (
            self.session.query(MemoryUsageEvent)
            .filter(MemoryUsageEvent.company_id == company_id,
                    MemoryUsageEvent.created_at >= start, MemoryUsageEvent.created_at < end)
        )
        searches = found = 0
        by_channel: Counter = Counter()
        by_day: Counter = Counter()
        found_flag = case((MemoryUsageEvent.results > 0, 1), else_=0)
        day = func.date(MemoryUsageEvent.created_at)
        rows = (
            base.with_entities(MemoryUsageEvent.channel, day, found_flag, func.count(MemoryUsageEvent.id))
            .filter(MemoryUsageEvent.tool.in_(list(memory_tools.SEARCH_TOOLS)))
            .group_by(MemoryUsageEvent.channel, day, found_flag)
            .all()
        )
        for channel, event_day, was_found, count in rows:
            searches += count
            if was_found:
                found += count
            by_channel[channel] += count
            by_day[str(event_day)] += count
        page_reads = Counter({str(page_id): count for page_id, count in (
            base.with_entities(MemoryUsageEvent.page_id, func.count(MemoryUsageEvent.id))
            .filter(MemoryUsageEvent.tool == memory_tools.PAGE_READ_TOOL, MemoryUsageEvent.page_id.isnot(None))
            .group_by(MemoryUsageEvent.page_id).all()
        )})
        document_reads = Counter({str(document_id): count for document_id, count in (
            base.with_entities(MemoryUsageEvent.document_id, func.count(MemoryUsageEvent.id))
            .filter(MemoryUsageEvent.tool == memory_tools.DOCUMENT_READ_TOOL, MemoryUsageEvent.document_id.isnot(None))
            .group_by(MemoryUsageEvent.document_id).all()
        )})
        return {"searches": searches, "searches_found": found, "by_channel": dict(by_channel),
                "by_day": dict(by_day), "page_reads": page_reads, "document_reads": document_reads}
