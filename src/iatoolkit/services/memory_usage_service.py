# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Records each use of the company's knowledge (Fase 2): iat_memory_usage_events.

Called after a knowledge tool ran (the dispatcher for the chat; enterprise's
MCP backend for MCP clients). Best effort: a failed record never fails the tool.
"""

from __future__ import annotations

import logging

from injector import inject

from iatoolkit.common import memory_tools
from iatoolkit.repositories.memory_usage_repo import MemoryUsageRepo
from iatoolkit.repositories.models import MemoryUsageEvent
from iatoolkit.repositories.profile_repo import ProfileRepo


class MemoryUsageService:
    MAX_QUERY_CHARS = 300

    @inject
    def __init__(self, memory_usage_repo: MemoryUsageRepo, profile_repo: ProfileRepo):
        self.repo = memory_usage_repo
        self.profile_repo = profile_repo

    def record(self, company_short_name: str, tool: str, arguments: dict | None, result, *,
               user_identifier: str | None = None, channel: str = memory_tools.CHANNEL_CHAT) -> None:
        if tool not in memory_tools.KNOWLEDGE_TOOLS:
            return
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return
            arguments = arguments if isinstance(arguments, dict) else {}
            payload = result if isinstance(result, dict) else {}
            self.repo.add(MemoryUsageEvent(
                company_id=company.id,
                user_identifier=(str(user_identifier or "").strip() or None),
                channel=str(channel or memory_tools.CHANNEL_CHAT)[:16],
                tool=tool,
                query=(str(arguments.get("query") or "").strip()[:self.MAX_QUERY_CHARS] or None),
                results=self._results(payload),
                page_id=self._int(arguments.get("page_id")) if tool == memory_tools.PAGE_READ_TOOL else None,
                document_id=self._int(arguments.get("document_id")) if tool == memory_tools.DOCUMENT_READ_TOOL else None,
            ))
        except Exception as exc:
            try:
                self.repo.rollback()
            except Exception:
                pass
            logging.warning("Memoria usage event could not be recorded (%s, %s): %s", company_short_name, tool, exc)

    @staticmethod
    def _results(payload: dict) -> int:
        if payload.get("status") == "error":
            return 0
        for key in ("results", "chunks", "documents"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        if payload.get("count") is not None:
            try:
                return int(payload["count"])
            except (TypeError, ValueError):
                return 0
        return 1 if payload.get("page") or payload.get("text") else 0

    @staticmethod
    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
