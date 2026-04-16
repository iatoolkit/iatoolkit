# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import unicodedata
import uuid
from injector import inject

from iatoolkit.common.interfaces.memory_compilation_trigger import MemoryCompilationTrigger
from iatoolkit.common.interfaces.memory_lint_trigger import MemoryLintTrigger
from iatoolkit.common.util import Utility
from iatoolkit.repositories.memory_repo import MemoryRepo
from iatoolkit.repositories.models import (
    MemoryCapture,
    MemoryCaptureStatus,
    MemoryItem,
    MemoryItemStatus,
    MemoryItemType,
)
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.memory_compiler_service import MemoryCompilerService
from iatoolkit.services.memory_lint_service import MemoryLintService
from iatoolkit.services.memory_wiki_service import MemoryWikiService
from iatoolkit.services.storage_service import StorageService


class MemoryService:
    TOOL_NATIVE_ATTACHMENTS_KEY = "__native_attachments__"
    MAX_NATIVE_ATTACHMENTS_PER_PAGE = 10
    MAX_NATIVE_ATTACHMENT_BYTES = 20 * 1024 * 1024

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 memory_repo: MemoryRepo,
                 memory_wiki_service: MemoryWikiService,
                 memory_compiler_service: MemoryCompilerService,
                 memory_lint_service: MemoryLintService,
                 memory_compilation_trigger: MemoryCompilationTrigger,
                 memory_lint_trigger: MemoryLintTrigger,
                 storage_service: StorageService,
                 util: Utility):
        self.profile_repo = profile_repo
        self.memory_repo = memory_repo
        self.memory_wiki_service = memory_wiki_service
        self.memory_compiler_service = memory_compiler_service
        self.memory_lint_service = memory_lint_service
        self.memory_compilation_trigger = memory_compilation_trigger
        self.memory_lint_trigger = memory_lint_trigger
        self.storage_service = storage_service
        self.util = util

    def save_item(self,
                  company_short_name: str,
                  user_identifier: str,
                  item_type: str,
                  content_text: str | None = None,
                  title: str | None = None,
                  source_url: str | None = None,
                  filename: str | None = None,
                  mime_type: str | None = None,
                  file_base64: str | None = None,
                  source_meta: dict | None = None) -> dict:
        response = self.save_capture(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            capture_text=content_text if item_type != "link" else source_url,
            new_items=[{
                "item_type": item_type,
                "content_text": content_text,
                "title": title,
                "source_url": source_url,
                "filename": filename,
                "mime_type": mime_type,
                "file_base64": file_base64,
                "source_meta": source_meta,
            }],
        )
        if response.get("status") != "success":
            return response
        first_item = (response.get("capture") or {}).get("items") or []
        return {
            "status": "success",
            "item": first_item[0] if first_item else None,
            "capture": response.get("capture"),
        }

    def save_capture(self,
                     company_short_name: str,
                     user_identifier: str,
                     capture_text: str | None = None,
                     new_items: list[dict] | None = None,
                     title: str | None = None) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        self.memory_wiki_service.ensure_wiki_bootstrap(company_short_name, user_identifier)

        capture = MemoryCapture(
            company_id=company.id,
            user_identifier=user_identifier,
            title=(title or capture_text or "")[:200] or None,
            status=MemoryCaptureStatus.PENDING,
            meta={},
        )
        self.memory_repo.create_capture(capture)

        created_items = []
        for item_payload in new_items or []:
            item = self._build_memory_item(
                company_short_name=company_short_name,
                company_id=company.id,
                user_identifier=user_identifier,
                capture_id=capture.id,
                item_payload=item_payload,
            )
            self.memory_repo.create_item(item)
            created_items.append(item)

        if not created_items:
            self.memory_repo.delete_capture(capture)
            return {"status": "error", "error_message": "capture is empty"}

        if not capture.title:
            capture.title = self._capture_title_from_items(created_items) or None
            self.memory_repo.save_capture(capture)

        self.memory_compilation_trigger.trigger(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            trigger_item_id=created_items[0].id,
            reason="capture",
        )
        return {
            "status": "success",
            "capture": self.serialize_capture(capture, created_items, company_short_name=company_short_name),
        }

    def update_capture(self,
                       company_short_name: str,
                       user_identifier: str,
                       capture_id: int,
                       capture_text: str | None = None,
                       keep_item_ids: list[int] | None = None,
                       new_items: list[dict] | None = None,
                       title: str | None = None) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        self.memory_wiki_service.ensure_wiki_bootstrap(company_short_name, user_identifier)

        capture = self.memory_repo.get_capture(company.id, user_identifier, capture_id)
        if not capture:
            return {"status": "error", "error_message": "capture not found"}

        current_items = self.memory_repo.list_capture_items(capture.id)
        keep_set = {
            int(item_id) for item_id in (keep_item_ids or [])
            if isinstance(item_id, int) or (isinstance(item_id, str) and str(item_id).isdigit())
        }

        for item in current_items:
            if item.id in keep_set:
                continue
            self._delete_memory_item(
                company_short_name=company_short_name,
                company_id=company.id,
                user_identifier=user_identifier,
                item=item,
            )

        created_items = []
        for item_payload in new_items or []:
            item = self._build_memory_item(
                company_short_name=company_short_name,
                company_id=company.id,
                user_identifier=user_identifier,
                capture_id=capture.id,
                item_payload=item_payload,
            )
            self.memory_repo.create_item(item)
            created_items.append(item)

        refreshed_items = self.memory_repo.list_capture_items(capture.id)
        if not refreshed_items:
            self.memory_repo.delete_capture(capture)
            return {"status": "success", "deleted_capture_id": capture_id}

        capture.title = (title or capture_text or self._capture_title_from_items(refreshed_items) or "")[:200] or None
        capture.status = MemoryCaptureStatus.PENDING
        capture.compile_error = None
        self.memory_repo.save_capture(capture)
        self.memory_compilation_trigger.trigger(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            trigger_item_id=refreshed_items[0].id,
            reason="capture_update",
        )
        return {
            "status": "success",
            "capture": self.serialize_capture(capture, refreshed_items, company_short_name=company_short_name),
        }

    def get_memory_dashboard(self, company_short_name: str, user_identifier: str) -> dict:
        self._compile_on_demand(company_short_name, user_identifier)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        self.memory_wiki_service.ensure_wiki_bootstrap(company_short_name, user_identifier)

        captures = self.memory_repo.list_recent_captures(company.id, user_identifier)
        pages = self.memory_repo.list_pages(company.id, user_identifier)
        last_lint = self.memory_lint_service.get_last_lint_result(company_short_name, user_identifier)
        return {
            "status": "success",
            "captures": [self.serialize_capture(capture, company_short_name=company_short_name) for capture in captures],
            "recent_items": [self.serialize_capture(capture, company_short_name=company_short_name) for capture in captures],
            "pages": [self.serialize_page(page) for page in pages],
            "last_lint": last_lint,
        }

    def list_pages(self, company_short_name: str, user_identifier: str) -> list[dict]:
        self._compile_on_demand(company_short_name, user_identifier)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return []
        return [
            self.serialize_page(page)
            for page in self.memory_repo.list_pages(company.id, user_identifier)
        ]

    def search_pages(self,
                     company_short_name: str,
                     user_identifier: str,
                     query: str,
                     limit: int = 5,
                     include_native_attachments: bool = False) -> dict:
        self._compile_on_demand(company_short_name, user_identifier)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "results": [], "error_message": "company not found"}
        self.memory_wiki_service.ensure_wiki_bootstrap(company_short_name, user_identifier)

        candidate_limit = max(limit * 10, 50)
        pages = self.memory_repo.list_pages(company.id, user_identifier, limit=candidate_limit)
        index_payload = self.memory_wiki_service.read_index(company_short_name, user_identifier)
        if not isinstance(index_payload, dict):
            index_payload = {}
        index_entries = index_payload.get("entries") if isinstance(index_payload.get("entries"), list) else []
        index_map = {
            entry.get("page_id"): entry
            for entry in index_entries
            if isinstance(entry.get("page_id"), int)
        }
        normalized_query = self._normalize_text(query)
        query_tokens = self._tokenize(query)
        pages = sorted(
            pages,
            key=lambda page: (
                self._score_index_entry(normalized_query, query_tokens, index_map.get(getattr(page, "id", None))),
                getattr(page, "updated_at", None).isoformat() if getattr(page, "updated_at", None) else "",
            ),
            reverse=True,
        )
        serialized = []
        source_items_by_page_id = {}

        for page in pages:
            page_payload = self._safe_read_page(company_short_name, page.wiki_path)
            source_items = self._load_page_source_items(
                company_id=company.id,
                user_identifier=user_identifier,
                page_id=page.id,
                page_payload=page_payload,
            )
            score = self._score_page_match(normalized_query, query_tokens, page, page_payload, source_items)
            if normalized_query and score <= 0:
                continue
            source_items_by_page_id[page.id] = source_items

            result = self.serialize_page(page)
            if page_payload.get("summary"):
                result["summary"] = page_payload.get("summary")
            result["sources"] = self._build_search_result_sources(page_payload, source_items)
            result["source_urls"] = [
                item.source_url for item in source_items
                if getattr(item, "source_url", None)
            ][:5]
            result["has_native_files"] = any(
                self._is_native_attachment_candidate(item)
                for item in source_items
            )
            result["native_filenames"] = [
                str(getattr(item, "filename", "") or "").strip()
                for item in source_items
                if self._is_native_attachment_candidate(item) and str(getattr(item, "filename", "") or "").strip()
            ][:5]
            result["score"] = round(score if score > 0 else 1.0, 4)
            serialized.append(result)

        serialized.sort(
            key=lambda item: (
                float(item.get("score") or 0),
                item.get("last_updated_at") or "",
                int(item.get("page_id") or 0),
            ),
            reverse=True,
        )

        raw_matches = self._search_raw_items(
            company_short_name=company_short_name,
            company_id=company.id,
            user_identifier=user_identifier,
            normalized_query=normalized_query,
            query_tokens=query_tokens,
            limit=limit,
        )

        if str(query or "").strip():
            self.memory_wiki_service.append_log_entry(
                company_short_name,
                user_identifier,
                entry_type="query",
                title=str(query).strip()[:200],
                details=[
                    f"Matched {len(serialized[:limit])} memory pages.",
                    f"Matched {len(raw_matches)} raw items.",
                ],
                metadata={"limit": limit},
            )

        limited_results = serialized[:limit]
        response = {
            "status": "success",
            "results": limited_results,
            "raw_items": raw_matches,
        }
        if include_native_attachments:
            raw_native_items = self._load_raw_native_items_for_matches(
                company_id=company.id,
                user_identifier=user_identifier,
                raw_matches=raw_matches,
            )
            native_attachments = self._build_search_native_attachments(
                company_short_name=company_short_name,
                results=limited_results,
                source_items_by_page_id=source_items_by_page_id,
                raw_source_items=raw_native_items,
            )
            response[self.TOOL_NATIVE_ATTACHMENTS_KEY] = native_attachments
            response["native_attachment_delivery"] = {
                "status": "native_attached" if native_attachments else "none",
                "count": len(native_attachments),
                "filenames": [str(item.get("name") or "").strip() for item in native_attachments if item.get("name")],
                "note": (
                    "Attached files from the top memory search results are already available to the model as native files for direct inspection in this turn. "
                    "Use them to answer questions that require reading or extracting file contents."
                    if native_attachments else
                    "No native files were attached for these memory search results."
                ),
            }
        return response

    def get_page(self,
                 company_short_name: str,
                 user_identifier: str,
                 page_id: int,
                 include_native_attachments: bool = False) -> dict:
        self._compile_on_demand(company_short_name, user_identifier)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        page = self.memory_repo.get_page(company.id, user_identifier, page_id)
        if not page:
            return {"status": "error", "error_message": "page not found"}

        payload = self.memory_wiki_service.read_page(company_short_name, page.wiki_path)
        source_items = self._load_page_source_items(
            company_id=company.id,
            user_identifier=user_identifier,
            page_id=page.id,
            page_payload=payload,
        )
        payload.update({
            "page_id": page.id,
            "title": payload.get("title") or page.title,
            "slug": payload.get("slug") or page.slug,
            "summary": payload.get("summary") or page.summary or "",
            "last_updated_at": page.updated_at.isoformat() if page.updated_at else None,
            "source_items": [
                self.serialize_item(item, company_short_name=company_short_name)
                for item in source_items
            ],
        })
        payload["sources"] = payload.get("sources") or []
        response = {"status": "success", "page": payload}
        if include_native_attachments:
            native_attachments = self._build_page_native_attachments(
                company_short_name=company_short_name,
                source_items=source_items,
            )
            response[self.TOOL_NATIVE_ATTACHMENTS_KEY] = native_attachments
            response["native_attachment_delivery"] = {
                "status": "native_attached" if native_attachments else "none",
                "count": len(native_attachments),
                "filenames": [str(item.get("name") or "").strip() for item in native_attachments if item.get("name")],
                "note": (
                    "Attached files are already available to the model as native files for direct inspection in this turn. "
                    "Use access_url only when the user explicitly asks for a download link."
                    if native_attachments else
                    "No native files were attached for this page."
                ),
            }
        return response

    def lint_memory_wiki(self, company_short_name: str, user_identifier: str) -> dict:
        trigger_result = self.memory_lint_trigger.trigger(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            reason="manual",
        )
        if trigger_result.triggered:
            return {
                "status": "success",
                "mode": trigger_result.mode,
                "lint": None,
                "task": trigger_result.metadata,
            }
        return self.run_memory_lint(company_short_name, user_identifier)

    def run_memory_lint(self, company_short_name: str, user_identifier: str) -> dict:
        return self.memory_lint_service.run_memory_lint(company_short_name, user_identifier)

    def delete_item(self, company_short_name: str, user_identifier: str, item_id: int) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        item = self.memory_repo.get_item(company.id, user_identifier, item_id)
        if not item:
            return {"status": "error", "error_message": "item not found"}

        capture_id = getattr(item, "capture_id", None)
        self._delete_memory_item(
            company_short_name=company_short_name,
            company_id=company.id,
            user_identifier=user_identifier,
            item=item,
        )
        if capture_id:
            capture = self.memory_repo.get_capture(company.id, user_identifier, capture_id)
            if capture and not self.memory_repo.list_capture_items(capture.id):
                self.memory_repo.delete_capture(capture)
        return {"status": "success", "deleted_item_id": item_id}

    def delete_capture(self, company_short_name: str, user_identifier: str, capture_id: int) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        capture = self.memory_repo.get_capture(company.id, user_identifier, capture_id)
        if not capture:
            return {"status": "error", "error_message": "capture not found"}

        for item in list(self.memory_repo.list_capture_items(capture.id)):
            self._delete_memory_item(
                company_short_name=company_short_name,
                company_id=company.id,
                user_identifier=user_identifier,
                item=item,
            )
        self.memory_repo.delete_capture(capture)
        self._rebuild_index(company_short_name, company.id, user_identifier)
        self.memory_wiki_service.append_log_entry(
            company_short_name,
            user_identifier,
            entry_type="ingest",
            title=f"Capture {capture_id} deleted",
            details=["A saved capture was removed from Memory."],
            metadata={"capture_id": capture_id},
        )
        return {"status": "success", "deleted_capture_id": capture_id}

    def serialize_item(self, item: MemoryItem, company_short_name: str | None = None) -> dict:
        access_url = item.source_url
        if not access_url and company_short_name and item.storage_key:
            try:
                access_url = self.storage_service.generate_presigned_url(company_short_name, item.storage_key)
            except Exception:
                access_url = None
        raw_source_meta = getattr(item, "source_meta", None)
        source_meta = raw_source_meta if isinstance(raw_source_meta, dict) else {}

        return {
            "id": item.id,
            "item_type": item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type),
            "status": item.status.value if hasattr(item.status, "value") else str(item.status),
            "title": item.title,
            "content_text": item.content_text,
            "content_preview": (item.content_text or "")[:220],
            "source_url": item.source_url,
            "filename": item.filename,
            "mime_type": item.mime_type,
            "access_url": access_url,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "capture_group_id": source_meta.get("capture_group_id"),
            "capture_id": getattr(item, "capture_id", None),
        }

    def serialize_capture(self,
                          capture: MemoryCapture,
                          items: list[MemoryItem] | None = None,
                          company_short_name: str | None = None) -> dict:
        capture_items = items if items is not None else self.memory_repo.list_capture_items(capture.id)
        serialized_items = [
            self.serialize_item(item, company_short_name=company_short_name)
            for item in capture_items
        ]
        preview = self._capture_preview(serialized_items)
        return {
            "capture_id": capture.id,
            "title": capture.title or preview or f"Capture {capture.id}",
            "preview": preview,
            "status": capture.status.value if hasattr(capture.status, "value") else str(capture.status),
            "created_at": capture.created_at.isoformat() if capture.created_at else None,
            "updated_at": capture.updated_at.isoformat() if capture.updated_at else None,
            "items": serialized_items,
        }

    def serialize_page(self, page) -> dict:
        return {
            "page_id": page.id,
            "title": page.title,
            "summary": page.summary or "",
            "slug": page.slug,
            "wiki_path": page.wiki_path,
            "last_updated_at": page.updated_at.isoformat() if page.updated_at else None,
        }

    def _safe_read_page(self, company_short_name: str, wiki_path: str | None) -> dict:
        if not wiki_path:
            return {}
        try:
            return self.memory_wiki_service.read_page(company_short_name, wiki_path) or {}
        except Exception:
            return {}

    def _lint_page_payload(self, payload: dict) -> tuple[dict, bool]:
        linted = dict(payload or {})
        changed = False

        def _dedupe_entries(values):
            deduped = []
            seen = set()
            for value in values or []:
                text = str(value or "").strip()
                if not text:
                    continue
                key = self._normalize_text(text)
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(text)
            return deduped

        for key in ("key_points", "decisions", "open_questions", "next_steps", "related_pages", "sources"):
            original = linted.get(key) or []
            deduped = _dedupe_entries(original)
            if list(original) != deduped:
                linted[key] = deduped
                changed = True

        summary = str(linted.get("summary") or "").strip()
        title = str(linted.get("title") or "").strip()
        if summary and title and self._normalize_text(summary) == self._normalize_text(title):
            linted["summary"] = title

        source_item_ids = []
        seen_item_ids = set()
        for item_id in linted.get("source_item_ids") or []:
            if isinstance(item_id, int) and item_id not in seen_item_ids:
                seen_item_ids.add(item_id)
                source_item_ids.append(item_id)
        if list(linted.get("source_item_ids") or []) != source_item_ids:
            linted["source_item_ids"] = source_item_ids
            changed = True

        return linted, changed

    def _get_last_lint_result(self, company_short_name: str, user_identifier: str) -> dict:
        entries = self.memory_wiki_service.read_log(company_short_name, user_identifier)
        if not isinstance(entries, list):
            return {}
        for entry in reversed(entries or []):
            if str(entry.get("entry_type") or "").strip().lower() != "lint":
                continue
            metadata = entry.get("metadata") or {}
            return {
                "title": entry.get("title") or "Memory wiki health check",
                "timestamp": entry.get("timestamp"),
                "checked_pages": int(metadata.get("checked_pages") or 0),
                "actions_applied": int(metadata.get("actions_applied") or 0),
                "duplicate_candidates": int(metadata.get("duplicate_candidates") or 0),
                "orphan_pages": int(metadata.get("orphan_pages") or 0),
                "details": entry.get("details") or [],
            }
        return {}

    def _load_page_source_items(self, company_id: int, user_identifier: str, page_id: int, page_payload: dict) -> list[MemoryItem]:
        source_item_ids = [
            item_id for item_id in (page_payload.get("source_item_ids") or [])
            if isinstance(item_id, int)
        ]
        if not source_item_ids and page_id:
            links = self.memory_repo.list_page_sources(page_id)
            source_item_ids = [
                link.memory_item_id for link in links
                if isinstance(link.memory_item_id, int)
            ]

        if not source_item_ids:
            return []
        return self.memory_repo.list_items_by_ids(company_id, user_identifier, source_item_ids)

    def _build_page_native_attachments(self,
                                       company_short_name: str,
                                       source_items: list[MemoryItem]) -> list[dict]:
        attachments = []
        seen_storage_keys = set()

        for item in source_items or []:
            if len(attachments) >= self.MAX_NATIVE_ATTACHMENTS_PER_PAGE:
                break
            if getattr(item, "item_type", None) != MemoryItemType.FILE:
                continue

            storage_key = str(getattr(item, "storage_key", "") or "").strip()
            if not storage_key or storage_key in seen_storage_keys:
                continue

            try:
                file_bytes = self.storage_service.get_document_content(company_short_name, storage_key)
            except Exception as exc:
                logging.warning("Could not load memory attachment '%s': %s", storage_key, exc)
                continue

            if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
                continue
            if len(file_bytes) > self.MAX_NATIVE_ATTACHMENT_BYTES:
                logging.info(
                    "Skipping memory attachment '%s' because it exceeds %s bytes.",
                    storage_key,
                    self.MAX_NATIVE_ATTACHMENT_BYTES,
                )
                continue

            filename = str(getattr(item, "filename", None) or os.path.basename(storage_key) or "attachment").strip()
            mime_type = str(
                getattr(item, "mime_type", None)
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            ).strip().lower()

            seen_storage_keys.add(storage_key)
            attachments.append({
                "name": filename,
                "mime_type": mime_type,
                "base64": base64.b64encode(file_bytes).decode("ascii"),
                "size_bytes": len(file_bytes),
            })

        return attachments

    def _build_search_native_attachments(self,
                                         company_short_name: str,
                                         results: list[dict],
                                         source_items_by_page_id: dict[int, list[MemoryItem]],
                                         raw_source_items: list[MemoryItem] | None = None) -> list[dict]:
        native_source_items = []
        seen_storage_keys = set()

        def add_native_item(item):
            if len(native_source_items) >= self.MAX_NATIVE_ATTACHMENTS_PER_PAGE:
                return
            if not self._is_native_attachment_candidate(item):
                return
            storage_key = str(getattr(item, "storage_key", "") or "").strip()
            if storage_key in seen_storage_keys:
                return
            seen_storage_keys.add(storage_key)
            native_source_items.append(item)

        for result in results or []:
            if not result.get("has_native_files"):
                continue
            page_id = result.get("page_id")
            for item in source_items_by_page_id.get(page_id, []):
                add_native_item(item)
                if len(native_source_items) >= self.MAX_NATIVE_ATTACHMENTS_PER_PAGE:
                    break
            if len(native_source_items) >= self.MAX_NATIVE_ATTACHMENTS_PER_PAGE:
                break

        for item in raw_source_items or []:
            add_native_item(item)
            if len(native_source_items) >= self.MAX_NATIVE_ATTACHMENTS_PER_PAGE:
                break

        return self._build_page_native_attachments(company_short_name, native_source_items)

    def _load_raw_native_items_for_matches(self,
                                           company_id: int,
                                           user_identifier: str,
                                           raw_matches: list[dict]) -> list[MemoryItem]:
        raw_item_ids = []
        for item in raw_matches or []:
            if item.get("item_type") != MemoryItemType.FILE.value:
                continue
            try:
                raw_item_ids.append(int(item.get("id")))
            except (TypeError, ValueError):
                continue

        if not raw_item_ids:
            return []
        return self.memory_repo.list_items_by_ids(company_id, user_identifier, raw_item_ids)

    @staticmethod
    def _is_native_attachment_candidate(item: MemoryItem) -> bool:
        return (
            getattr(item, "item_type", None) == MemoryItemType.FILE
            and bool(str(getattr(item, "storage_key", "") or "").strip())
        )

    def _score_page_match(self,
                          normalized_query: str,
                          query_tokens: list[str],
                          page,
                          page_payload: dict,
                          source_items: list[MemoryItem]) -> float:
        if not normalized_query and not query_tokens:
            return 1.0

        title_text = self._normalize_text(getattr(page, "title", "") or page_payload.get("title") or "")
        summary_text = self._normalize_text(page_payload.get("summary") or getattr(page, "summary", "") or "")
        detail_parts = []
        for key in ("key_points", "decisions", "open_questions", "next_steps", "sources", "related_pages"):
            values = page_payload.get(key) or []
            if isinstance(values, list):
                detail_parts.extend(str(value or "") for value in values)
        details_text = self._normalize_text(" ".join(detail_parts))
        source_parts = []
        for item in source_items or []:
            source_parts.extend([
                str(getattr(item, "title", "") or ""),
                str(getattr(item, "content_text", "") or ""),
                str(getattr(item, "source_url", "") or ""),
                str(getattr(item, "filename", "") or ""),
            ])
        source_text = self._normalize_text(" ".join(source_parts))
        full_text = " ".join(part for part in (title_text, summary_text, details_text, source_text) if part).strip()

        if not full_text:
            return 0.0

        score = 0.0
        if normalized_query and normalized_query in full_text:
            score += 6.0
        if normalized_query and normalized_query in title_text:
            score += 4.0
        if normalized_query and normalized_query in summary_text:
            score += 3.0

        for token in query_tokens:
            variants = self._token_variants(token)
            if any(variant in title_text for variant in variants):
                score += 2.5
            if any(variant in summary_text for variant in variants):
                score += 1.7
            if any(variant in details_text for variant in variants):
                score += 1.0
            if any(variant in source_text for variant in variants):
                score += 2.2

        unique_hits = len({
            token for token in query_tokens
            if any(variant in full_text for variant in self._token_variants(token))
        })
        score += unique_hits * 0.3
        return score

    def _score_index_entry(self, normalized_query: str, query_tokens: list[str], entry: dict | None) -> float:
        if not entry:
            return 0.0
        title_text = self._normalize_text(entry.get("title") or "")
        summary_text = self._normalize_text(entry.get("summary") or "")
        full_text = " ".join(part for part in (title_text, summary_text) if part).strip()
        if not full_text:
            return 0.0

        score = 0.0
        if normalized_query and normalized_query in full_text:
            score += 4.0
        if normalized_query and normalized_query in title_text:
            score += 2.5
        if normalized_query and normalized_query in summary_text:
            score += 1.8

        for token in query_tokens:
            variants = self._token_variants(token)
            if any(variant in title_text for variant in variants):
                score += 1.8
            if any(variant in summary_text for variant in variants):
                score += 1.1

        return score

    def _build_search_result_sources(self, page_payload: dict, source_items: list[MemoryItem]) -> list[str]:
        entries = []
        for item in page_payload.get("sources") or []:
            text = str(item or "").strip()
            if text and text not in entries:
                entries.append(text)

        for item in source_items or []:
            for candidate in (
                getattr(item, "source_url", None),
                getattr(item, "filename", None),
                getattr(item, "title", None),
            ):
                text = str(candidate or "").strip()
                if text and text not in entries:
                    entries.append(text)

        return entries[:8]

    def _search_raw_items(self,
                          company_short_name: str,
                          company_id: int,
                          user_identifier: str,
                          normalized_query: str,
                          query_tokens: list[str],
                          limit: int) -> list[dict]:
        items = self.memory_repo.list_recent_items(company_id, user_identifier, limit=max(limit * 12, 60))
        ranked = []
        for item in items:
            score = self._score_memory_item_match(normalized_query, query_tokens, item)
            if normalized_query and score <= 0:
                continue
            payload = self.serialize_item(item, company_short_name=company_short_name)
            payload["score"] = round(score if score > 0 else 1.0, 4)
            ranked.append(payload)

        ranked.sort(
            key=lambda item: (
                float(item.get("score") or 0),
                item.get("created_at") or "",
                int(item.get("id") or 0),
            ),
            reverse=True,
        )
        return ranked[:limit]

    def _score_memory_item_match(self, normalized_query: str, query_tokens: list[str], item: MemoryItem) -> float:
        title_text = self._normalize_text(getattr(item, "title", "") or "")
        content_text = self._normalize_text(getattr(item, "content_text", "") or "")
        source_url_text = self._normalize_text(getattr(item, "source_url", "") or "")
        filename_text = self._normalize_text(getattr(item, "filename", "") or "")
        full_text = " ".join(part for part in (title_text, content_text, source_url_text, filename_text) if part).strip()

        if not full_text:
            return 0.0

        score = 0.0
        if normalized_query and normalized_query in full_text:
            score += 6.0
        if normalized_query and normalized_query in title_text:
            score += 4.0
        if normalized_query and normalized_query in content_text:
            score += 3.0

        for token in query_tokens:
            variants = self._token_variants(token)
            if any(variant in title_text for variant in variants):
                score += 2.8
            if any(variant in content_text for variant in variants):
                score += 2.1
            if any(variant in source_url_text for variant in variants):
                score += 1.8
            if any(variant in filename_text for variant in variants):
                score += 1.3

        unique_hits = len({
            token for token in query_tokens
            if any(variant in full_text for variant in self._token_variants(token))
        })
        score += unique_hits * 0.35
        return score

    def _build_memory_item(self,
                           company_short_name: str,
                           company_id: int,
                           user_identifier: str,
                           capture_id: int,
                           item_payload: dict) -> MemoryItem:
        item_type = item_payload.get("item_type")
        mime_type = item_payload.get("mime_type")
        normalized_type = self._normalize_item_type(item_type, mime_type=mime_type)
        content_text = item_payload.get("content_text")
        title = item_payload.get("title")
        source_url = item_payload.get("source_url")
        filename = item_payload.get("filename")
        file_base64 = item_payload.get("file_base64")
        raw_source_meta = item_payload.get("source_meta") if isinstance(item_payload, dict) else None
        source_meta = raw_source_meta if isinstance(raw_source_meta, dict) else {}

        storage_key = None
        raw_text = content_text

        if file_base64:
            file_bytes = self.util.normalize_base64_payload(file_base64)
            safe_user = self.memory_wiki_service.sanitize_user_identifier(user_identifier)
            safe_filename = os.path.basename(filename or f"memory-{uuid.uuid4().hex}")
            storage_key = (
                f"companies/{company_short_name}/users/{safe_user}/memory/raw/"
                f"{uuid.uuid4().hex}/{safe_filename}"
            )
            mime_type = mime_type or mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"
            self.storage_service.upload_bytes(
                company_short_name=company_short_name,
                storage_key=storage_key,
                file_content=file_bytes,
                mime_type=mime_type,
            )

            if self._is_probably_text(mime_type):
                try:
                    raw_text = file_bytes.decode("utf-8", errors="replace")[:8000]
                except Exception:
                    raw_text = None

        return MemoryItem(
            company_id=company_id,
            capture_id=capture_id,
            user_identifier=user_identifier,
            item_type=normalized_type,
            status=MemoryItemStatus.PENDING,
            title=(title or "")[:200] or None,
            content_text=raw_text,
            source_url=source_url,
            filename=filename,
            mime_type=mime_type,
            storage_key=storage_key,
            source_meta=source_meta,
        )

    def _delete_memory_item(self,
                            company_short_name: str,
                            company_id: int,
                            user_identifier: str,
                            item: MemoryItem) -> None:
        affected_pages = self.memory_repo.list_pages_for_item(item.id)
        storage_key = item.storage_key
        self.memory_repo.delete_item(item)

        if storage_key:
            try:
                self.storage_service.delete_file(company_short_name, storage_key)
            except Exception:
                pass

        for page in affected_pages:
            self._repair_page_after_item_delete(
                company_short_name=company_short_name,
                company_id=company_id,
                user_identifier=user_identifier,
                page_id=page.id,
            )

    def _capture_title_from_items(self, items: list[MemoryItem]) -> str:
        for item in items or []:
            if getattr(item, "title", None):
                return str(item.title)[:200]
            if getattr(item, "filename", None):
                return str(item.filename)[:200]
            if getattr(item, "source_url", None):
                return str(item.source_url)[:200]
            if getattr(item, "content_text", None):
                return str(item.content_text).strip().splitlines()[0][:200]
        return ""

    def _capture_preview(self, items: list[dict]) -> str:
        if not items:
            return ""
        priority = ["note", "chat_user_message", "chat_assistant_message", "link", "image", "file"]
        for item_type in priority:
            candidate = next((item for item in items if item.get("item_type") == item_type), None)
            if candidate:
                return (
                    candidate.get("content_preview")
                    or candidate.get("title")
                    or candidate.get("filename")
                    or candidate.get("source_url")
                    or ""
                )
        candidate = items[0]
        return (
            candidate.get("content_preview")
            or candidate.get("title")
            or candidate.get("filename")
            or candidate.get("source_url")
            or ""
        )

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _tokenize(self, value: str | None) -> list[str]:
        normalized = self._normalize_text(value)
        return [
            token for token in re.findall(r"[a-z0-9_]+", normalized)
            if len(token) >= 3
        ]

    @staticmethod
    def _token_variants(token: str) -> list[str]:
        normalized = str(token or "").strip()
        if len(normalized) < 3:
            return []
        variants = [normalized]
        if normalized.endswith("es") and len(normalized) > 4:
            variants.append(normalized[:-2])
        if normalized.endswith("s") and len(normalized) > 4:
            variants.append(normalized[:-1])
        deduped = []
        for variant in variants:
            if variant and variant not in deduped:
                deduped.append(variant)
        return deduped

    def _compile_on_demand(self, company_short_name: str, user_identifier: str) -> None:
        if self.memory_compilation_trigger.is_async_enabled():
            return
        self.memory_compiler_service.compile_pending_for_user(company_short_name, user_identifier)

    def _repair_page_after_item_delete(self,
                                       company_short_name: str,
                                       company_id: int,
                                       user_identifier: str,
                                       page_id: int) -> None:
        page = self.memory_repo.get_page(company_id, user_identifier, page_id)
        if not page:
            return

        source_links = self.memory_repo.list_page_sources(page.id)
        remaining_ids = []
        for link in source_links:
            if isinstance(link.memory_item_id, int) and link.memory_item_id not in remaining_ids:
                remaining_ids.append(link.memory_item_id)

        if not remaining_ids:
            try:
                self.memory_wiki_service.delete_page(company_short_name, page.wiki_path)
            except Exception:
                pass
            self.memory_repo.delete_page(page)
            self._rebuild_index(company_short_name, company_id, user_identifier)
            return

        items = self.memory_repo.list_items_by_ids(company_id, user_identifier, remaining_ids)
        source_map = {item.id: self._memory_item_source_label(item) for item in items}

        try:
            page_payload = self.memory_wiki_service.read_page(company_short_name, page.wiki_path)
        except Exception:
            page_payload = {}

        page_payload.update({
            "page_id": page.id,
            "user_identifier": user_identifier,
            "title": page_payload.get("title") or page.title,
            "slug": page_payload.get("slug") or page.slug,
            "summary": page_payload.get("summary") or page.summary or "",
            "source_item_ids": remaining_ids,
            "sources": [source_map[item_id] for item_id in remaining_ids if source_map.get(item_id)],
            "wiki_path": page.wiki_path,
        })
        self.memory_wiki_service.write_page(company_short_name, page_payload)
        self._rebuild_index(company_short_name, company_id, user_identifier)

    @staticmethod
    def _memory_item_source_label(item: MemoryItem) -> str:
        if item.source_url:
            return item.source_url
        if item.filename:
            return item.filename
        if item.title:
            return item.title[:180]
        if item.content_text:
            return item.content_text.strip().replace("\n", " ")[:180]
        return f"Memory item {item.id}"

    @staticmethod
    def _normalize_item_type(item_type: str, mime_type: str | None = None) -> MemoryItemType:
        candidate = str(item_type or "").strip().lower()
        mapping = {
            "chat_user_message": MemoryItemType.CHAT_USER_MESSAGE,
            "chat_assistant_message": MemoryItemType.CHAT_ASSISTANT_MESSAGE,
            "note": MemoryItemType.NOTE,
            "link": MemoryItemType.LINK,
            "file": MemoryItemType.FILE,
            "image": MemoryItemType.IMAGE,
        }
        if candidate in mapping:
            return mapping[candidate]
        if mime_type and str(mime_type).startswith("image/"):
            return MemoryItemType.IMAGE
        return MemoryItemType.NOTE

    @staticmethod
    def _is_probably_text(mime_type: str | None) -> bool:
        candidate = str(mime_type or "").lower()
        return candidate.startswith("text/") or candidate in {
            "application/json",
            "application/xml",
            "application/javascript",
        }

    def _rebuild_index(self, company_short_name: str, company_id: int, user_identifier: str) -> None:
        pages = self.memory_repo.list_pages(company_id, user_identifier, limit=500)
        self.memory_wiki_service.rebuild_index(
            company_short_name,
            user_identifier,
            pages,
            page_reader=lambda page: self._safe_read_page(company_short_name, page.wiki_path),
        )
