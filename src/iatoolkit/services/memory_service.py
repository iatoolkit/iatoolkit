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

import markdown2
import nh3
from injector import inject

from iatoolkit.common.interfaces.memory_compilation_trigger import MemoryCompilationTrigger
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
from iatoolkit.services.memory_wiki_service import MemoryWikiService
from iatoolkit.services.storage_service import StorageService


class MemoryService:
    """
    The company's Memoria: people save captures (notes, links, files, chat
    messages) and the compiler turns them into pages of the company's Memoria
    wiki, which everyone in the company reads.

    A capture belongs to the company and records its author. Users edit and
    delete only their own captures; deleting one unlinks it from its pages but
    never touches the pages, which other people may have edited since.
    """

    TOOL_NATIVE_ATTACHMENTS_KEY = "__native_attachments__"
    MAX_NATIVE_ATTACHMENTS_PER_PAGE = 10
    MAX_NATIVE_ATTACHMENT_BYTES = 20 * 1024 * 1024
    MAX_SOURCE_LABELS = 8
    # Who a document capture is attributed to when nobody uploaded it (a Drive sync).
    DOCUMENT_SOURCE_IDENTITY = "service:memory-documents"

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 memory_repo: MemoryRepo,
                 memory_wiki_service: MemoryWikiService,
                 memory_compiler_service: MemoryCompilerService,
                 memory_compilation_trigger: MemoryCompilationTrigger,
                 storage_service: StorageService,
                 util: Utility):
        self.profile_repo = profile_repo
        self.memory_repo = memory_repo
        self.memory_wiki_service = memory_wiki_service
        self.memory_compiler_service = memory_compiler_service
        self.memory_compilation_trigger = memory_compilation_trigger
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
                     title: str | None = None,
                     meta: dict | None = None) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        if not str(user_identifier or "").strip():
            return {"status": "error", "error_message": "an author is required to save in Memoria"}

        capture = MemoryCapture(
            company_id=company.id,
            user_identifier=user_identifier,
            title=(title or capture_text or "")[:200] or None,
            status=MemoryCaptureStatus.PENDING,
            meta=dict(meta or {}),
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

    def save_document_capture(self,
                              company_short_name: str,
                              *,
                              document_id: int,
                              label: str,
                              card: dict | None = None,
                              path: str = "",
                              author: str | None = None,
                              source_meta: dict | None = None) -> dict:
        """
        A RAG document that feeds the wiki (BL-014), queued as a capture so the
        compiler reads it whole, part by part (`memory_document_ingest`).

        The capture does not copy the document: its one item points at it
        (`source_meta.rag_document_id`) and carries no bytes, and the compiler
        reads the document's fragments from the RAG when it gets to it.
        """
        label = str(label or "").strip() or f"Documento {document_id}"
        return self.save_capture(
            company_short_name=company_short_name,
            user_identifier=author or self.DOCUMENT_SOURCE_IDENTITY,
            title=label,
            new_items=[{
                "item_type": "file",
                "title": label,
                "filename": label,
                "source_meta": {**dict(source_meta or {}), "origin": "memory_document", "rag_document_id": document_id},
            }],
            meta={
                "mode": MemoryCompilerService.DOCUMENT_MODE,
                "document_id": document_id,
                "label": label,
                "card": dict(card or {}),
                "path": path or "",
                **({"source": dict(source_meta)} if source_meta else {}),
            },
        )

    def save_document_removal_capture(self,
                                      company_short_name: str,
                                      *,
                                      document_id: int,
                                      label: str,
                                      removed_by: str | None = None) -> dict:
        """
        A document that fed the wiki was deleted (BL-014): queued so the compiler
        marks its facts as obsolete on the pages that cite it. Nothing is erased.
        Does nothing when no page cites the document.
        """
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        if not self.memory_repo.list_page_ids_for_document(company.id, document_id):
            return {"status": "skipped", "reason": "no page cites this document"}
        label = str(label or "").strip() or f"Documento {document_id}"
        return self.save_capture(
            company_short_name=company_short_name,
            user_identifier=removed_by or self.DOCUMENT_SOURCE_IDENTITY,
            title=label,
            new_items=[{
                "item_type": "note",
                "title": label,
                "content_text": f"Se eliminó el documento «{label}».",
                "source_meta": {"origin": "memory_document_removed", "rag_document_id": document_id},
            }],
            meta={"mode": MemoryCompilerService.DOCUMENT_REMOVED_MODE, "document_id": document_id, "label": label},
        )

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

        capture = self.memory_repo.get_capture(company.id, capture_id, user_identifier=user_identifier)
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
            self._delete_memory_item(company_short_name, item)

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
        """What the chat's Memoria panel shows: the user's own captures and the company's pages."""
        self._compile_on_demand(company_short_name)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        captures = self.memory_repo.list_recent_captures(company.id, user_identifier=user_identifier)
        serialized_captures = [
            self.serialize_capture(capture, company_short_name=company_short_name)
            for capture in captures
        ]
        return {
            "status": "success",
            "captures": serialized_captures,
            "recent_items": serialized_captures,
            "pages": self.list_pages(company_short_name),
        }

    def list_pages(self, company_short_name: str) -> list[dict]:
        return [self.serialize_page(entry) for entry in self.memory_wiki_service.list_pages(company_short_name)]

    def search_pages(self,
                     company_short_name: str,
                     user_identifier: str | None,
                     query: str,
                     limit: int = 5,
                     include_native_attachments: bool = False) -> dict:
        self._compile_on_demand(company_short_name)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "results": [], "error_message": "company not found"}

        results = []
        source_items_by_page_id = {}
        for entry in self.memory_wiki_service.search_pages(company_short_name, query, limit=limit):
            page_id = entry.get("id")
            source_items = self._load_page_source_items(company.id, page_id)
            source_items_by_page_id[page_id] = source_items
            result = self.serialize_page(entry)
            result["sources"] = self._source_labels(source_items)
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
            result["score"] = entry.get("score")
            results.append(result)

        normalized_query = self._normalize_text(query)
        raw_matches = self._search_raw_items(
            company_short_name=company_short_name,
            company_id=company.id,
            normalized_query=normalized_query,
            query_tokens=self._tokenize(query),
            limit=limit,
        )

        response = {
            "status": "success",
            "results": results,
            "raw_items": raw_matches,
        }
        if include_native_attachments:
            raw_native_items = self._load_raw_native_items_for_matches(
                company_id=company.id,
                raw_matches=raw_matches,
            )
            native_attachments = self._build_search_native_attachments(
                company_short_name=company_short_name,
                results=results,
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
                 user_identifier: str | None,
                 page_id: int,
                 include_native_attachments: bool = False) -> dict:
        self._compile_on_demand(company_short_name)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        page = self.memory_wiki_service.get_page(company_short_name, page_id)
        if not page:
            return {"status": "error", "error_message": "page not found"}

        source_items = self._load_page_source_items(company.id, page.get("id"))
        payload = self.serialize_page(page)
        body = self.memory_wiki_service.page_body(page)
        payload.update({
            "markdown": body,
            # Rendered here and sanitized, like chat answers: page content comes
            # from what people saved, so it must not reach the DOM as raw HTML.
            # Without its leading "# Title": every screen shows the title itself.
            "html": self.render_page_html(body),
            "source_items": [
                self.serialize_item(item, company_short_name=company_short_name)
                for item in source_items
            ],
            "sources": self._source_labels(source_items),
        })
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

    def request_page_correction(self,
                                company_short_name: str,
                                user_identifier: str,
                                page_id: int,
                                instruction: str) -> dict:
        """Asks the compiler to change one page as `instruction` says, attributed to the requester."""
        text = str(instruction or "").strip()
        if not text:
            return {"status": "error", "error_message": "write what to correct or add"}
        if not self.memory_wiki_service.get_page(company_short_name, page_id):
            return {"status": "error", "error_message": "page not found"}
        response = self.save_capture(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            capture_text=text,
            title=f"Corrección: {text}"[:200],
            new_items=[{"item_type": "note", "content_text": text, "source_meta": {"origin": "page_correction"}}],
            meta={
                "origin": "page_correction",
                "mode": MemoryCompilerService.CORRECTION_MODE,
                "wiki_page_id": page_id,
            },
        )
        if response.get("status") != "success":
            return response
        return {"status": "success", "correction_id": (response.get("capture") or {}).get("capture_id")}

    def get_page_correction(self, company_short_name: str, correction_id: int) -> dict:
        """Where a correction stands and, once applied, the page before and after it."""
        self._compile_on_demand(company_short_name)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        capture = self.memory_repo.get_capture(company.id, correction_id)
        meta = dict(capture.meta or {}) if capture is not None else {}
        if capture is None or meta.get("mode") != MemoryCompilerService.CORRECTION_MODE:
            return {"status": "error", "error_message": "correction not found"}

        if capture.status == MemoryCaptureStatus.PENDING:
            state = "pending"
        elif capture.status == MemoryCaptureStatus.FAILED:
            state = MemoryCompilerService.CORRECTION_FAILED
        else:
            state = str(meta.get("result") or MemoryCompilerService.CORRECTION_FAILED)
        payload = {
            "status": "success",
            "correction": {
                "id": capture.id,
                "page_id": meta.get("wiki_page_id"),
                "state": state,
                "reason": meta.get("reason") or capture.compile_error,
                "revision_before_id": meta.get("revision_before_id"),
                "revision_after_id": meta.get("revision_after_id"),
            },
        }
        if state == MemoryCompilerService.CORRECTION_APPLIED:
            payload["correction"]["before"] = self._revision_body(company_short_name, meta.get("revision_before_id"))
            payload["correction"]["after"] = self._revision_body(company_short_name, meta.get("revision_after_id"))
        return payload

    def _revision_body(self, company_short_name: str, revision_id) -> str:
        if not isinstance(revision_id, int):
            return ""
        revision = self.memory_wiki_service.get_revision(company_short_name, revision_id)
        return self.memory_wiki_service.page_body(revision) if revision else ""

    def delete_item(self, company_short_name: str, user_identifier: str, item_id: int) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        item = self.memory_repo.get_item(company.id, item_id, user_identifier=user_identifier)
        if not item:
            return {"status": "error", "error_message": "item not found"}

        capture_id = getattr(item, "capture_id", None)
        self._delete_memory_item(company_short_name, item)
        if capture_id:
            capture = self.memory_repo.get_capture(company.id, capture_id, user_identifier=user_identifier)
            if capture and not self.memory_repo.list_capture_items(capture.id):
                self.memory_repo.delete_capture(capture)
        return {"status": "success", "deleted_item_id": item_id}

    def delete_capture(self, company_short_name: str, user_identifier: str, capture_id: int) -> dict:
        """Deletes the author's capture. Its pages stay as they are, with their history."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}

        capture = self.memory_repo.get_capture(company.id, capture_id, user_identifier=user_identifier)
        if not capture:
            return {"status": "error", "error_message": "capture not found"}

        for item in list(self.memory_repo.list_capture_items(capture.id)):
            self._delete_memory_item(company_short_name, item)
        self.memory_repo.delete_capture(capture)
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
            "author": getattr(item, "user_identifier", None),
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
        meta = capture.meta if isinstance(capture.meta, dict) else {}
        return {
            "capture_id": capture.id,
            "title": capture.title or preview or f"Capture {capture.id}",
            "preview": preview,
            "status": capture.status.value if hasattr(capture.status, "value") else str(capture.status),
            "author": capture.user_identifier,
            "wiki_page_id": meta.get("wiki_page_id"),
            "created_at": capture.created_at.isoformat() if capture.created_at else None,
            "updated_at": capture.updated_at.isoformat() if capture.updated_at else None,
            "items": serialized_items,
        }

    @staticmethod
    def serialize_page(page: dict) -> dict:
        """A Memoria wiki page as the chat panel and the memory tools return it."""
        return {
            "page_id": page.get("id"),
            "title": page.get("title"),
            "summary": page.get("summary") or "",
            "slug": page.get("slug"),
            "path": page.get("path"),
            "last_updated_at": page.get("updated_at"),
        }

    @staticmethod
    def render_page_html(body: str) -> str:
        """A page body as sanitized HTML, without its leading "# Title"."""
        lines = str(body or "").strip().splitlines()
        if lines and re.match(r"^#\s+\S", lines[0]):
            lines = lines[1:]
        content = "\n".join(lines).strip()
        if not content:
            return ""
        return nh3.clean(markdown2.markdown(content, extras=["tables", "fenced-code-blocks"]))

    def _load_page_source_items(self, company_id: int, page_id: int | None) -> list[MemoryItem]:
        if not isinstance(page_id, int):
            return []
        item_ids = self.memory_repo.list_page_source_item_ids(page_id)
        if not item_ids:
            return []
        items_by_id = {item.id: item for item in self.memory_repo.list_items_by_ids(company_id, item_ids)}
        return [items_by_id[item_id] for item_id in item_ids if item_id in items_by_id]

    def _source_labels(self, source_items: list[MemoryItem]) -> list[str]:
        labels = []
        for item in source_items or []:
            label = self._memory_item_source_label(item)
            if label and label not in labels:
                labels.append(label)
        return labels[:self.MAX_SOURCE_LABELS]

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
        return self.memory_repo.list_items_by_ids(company_id, raw_item_ids)

    @staticmethod
    def _is_native_attachment_candidate(item: MemoryItem) -> bool:
        return (
            getattr(item, "item_type", None) == MemoryItemType.FILE
            and bool(str(getattr(item, "storage_key", "") or "").strip())
        )

    @staticmethod
    def _is_native_attachment_candidate(item: MemoryItem) -> bool:
        return (
            getattr(item, "item_type", None) == MemoryItemType.FILE
            and bool(str(getattr(item, "storage_key", "") or "").strip())
        )

    def _search_raw_items(self,
                          company_short_name: str,
                          company_id: int,
                          normalized_query: str,
                          query_tokens: list[str],
                          limit: int) -> list[dict]:
        items = self.memory_repo.list_recent_items(company_id, limit=max(limit * 12, 60))
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
            safe_filename = os.path.basename(filename or f"memory-{uuid.uuid4().hex}")
            storage_key = (
                f"companies/{company_short_name}/memory/raw/"
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

    def _delete_memory_item(self, company_short_name: str, item: MemoryItem) -> None:
        """Deletes the item and its stored file and unlinks it from its pages, which stay untouched."""
        storage_key = item.storage_key
        self.memory_repo.delete_item(item)
        if storage_key:
            try:
                self.storage_service.delete_file(company_short_name, storage_key)
            except Exception:
                pass

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

    def _compile_on_demand(self, company_short_name: str) -> None:
        if self.memory_compilation_trigger.is_async_enabled():
            return
        self.memory_compiler_service.compile_pending_for_company(company_short_name)

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
