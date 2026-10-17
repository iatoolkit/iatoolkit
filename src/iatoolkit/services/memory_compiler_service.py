# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import base64
import logging
import mimetypes
import re
import time
from contextlib import contextmanager
from datetime import datetime
from html import unescape

import requests
from injector import inject

from iatoolkit.common.url_safety import fetch_with_safe_redirects
from iatoolkit.repositories.advisory_lock import advisory_lock
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.memory_repo import MemoryRepo
from iatoolkit.repositories.models import (
    Company, MemoryCapture, MemoryCaptureStatus, MemoryConflict, MemoryItem, MemoryItemStatus, MemoryItemType, VSDoc,
)
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.memory_sources import MemorySourceRegistry, register_core_sources
from iatoolkit.services.memory_wiki_service import MemoryWikiService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.system_agent_runner import SystemAgentDisabled, SystemAgentRunner
from iatoolkit.services.tenant_wiki_service import TenantWikiService


class MemoryCompilerService:
    """
    Turns the captures people save into pages of the company's Memoria wiki.

    The model receives the full markdown of the candidate pages and returns the
    full markdown of the page it creates or updates, attributing each new fact
    to the capture's author and date. Pages are saved through the wiki, so each
    change is a revision that can be undone, and a page someone edited while the
    model was working is re-read instead of overwritten.

    Compilation runs one capture at a time per company (see `_company_lock`):
    two captures on the same topic must not rewrite the same page concurrently.
    """

    MAX_NATIVE_PDF_ATTACHMENTS_PER_CAPTURE = 3
    MAX_NATIVE_PDF_ATTACHMENT_BYTES = 20 * 1024 * 1024
    MAX_CANDIDATE_PAGES = 3
    MAX_INDEX_ENTRIES_IN_PROMPT = 80
    MAX_BATCHES_PER_RUN = 20
    # A run gives its worker back after this long and the rest goes to a new task.
    MAX_RUN_SECONDS = 15 * 60
    # Times a run takes the lock again for captures saved as it was releasing it.
    MAX_LOCK_ROUNDS = 3
    MAX_SAVE_ATTEMPTS = 3
    COMPILER_SOURCE = "memory_compiler"
    # A capture that asks to change one page (Memoria → "¿Qué hay que corregir?").
    CORRECTION_MODE = "correction"
    CORRECTION_APPLIED = "applied"
    CORRECTION_NOT_APPLIED = "not_applied"
    CORRECTION_FAILED = "failed"
    # First key of the two-key Postgres advisory lock; the second is the company id.
    ADVISORY_LOCK_NAMESPACE = 734001

    # System agents (config/system_agents_pack.yaml) that write the pages.
    COMPILER_AGENT = "memory_compiler"
    # A document of the RAG that feeds the wiki (BL-014): read whole, part by part.
    DOCUMENT_MODE = "document"
    DOCUMENT_AGENT = "memory_document_ingest"
    # A saved link is read up to this much (its title and the start of its text).
    LINK_FETCH_MAX_BYTES = 512 * 1024
    # A meeting transcript (BL-015): decisions, procedures and owners, not the conversation.
    MEETING_AGENT = "memory_meeting_ingest"
    MEETING_KIND = "meeting"
    DOCUMENT_PART_CHARS = 12000
    MAX_PAGES_PER_PART = 5
    # An image of the RAG (no text) is looked at by its own agent, with vision.
    IMAGE_AGENT = "memory_image_ingest"
    MAX_IMAGES_PER_SOURCE = 5
    MAX_IMAGE_BYTES = 10 * 1024 * 1024
    # A document that fed the wiki was deleted: its facts are marked, never erased.
    DOCUMENT_REMOVED_MODE = "document_removed"
    OBSOLETE_MARK = "obsoleto: se eliminó el documento"
    # A new version of the document replaced the one these lines came from (BL-016, Fase 3).
    OBSOLETE_REPLACED_MARK = "obsoleto: hay una versión nueva del documento"
    # Any obsolete mark, whatever its reason: a line is marked once.
    OBSOLETE_PREFIX = "**[obsoleto"
    CORRECTION_AGENT = "memory_correction"

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 memory_repo: MemoryRepo,
                 memory_wiki_service: MemoryWikiService,
                 system_agent_runner: SystemAgentRunner,
                 storage_service: StorageService,
                 db_manager: DatabaseManager,
                 document_repo: DocumentRepo):
        self.profile_repo = profile_repo
        self.memory_repo = memory_repo
        self.memory_wiki_service = memory_wiki_service
        self.system_agent_runner = system_agent_runner
        self.storage_service = storage_service
        self.db_manager = db_manager
        self.document_repo = document_repo

    def compile_pending_for_company(self, company_short_name: str, limit: int = 12) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "compiled_count": 0, "error_message": "company not found"}
        wiki = self.memory_wiki_service.ensure_wiki(company_short_name)
        if wiki.get("status") != "success":
            return {"status": "error", "compiled_count": 0, "error_message": wiki.get("error_message")}

        compiled_count = 0
        processed_count = 0
        waiting_count = 0
        stopped = None
        started = time.monotonic()
        for _ in range(self.MAX_LOCK_ROUNDS):
            with self._company_lock(company.id) as held:
                if not held:
                    # Another run of this company holds the lock and drains every
                    # pending capture, including this one; this task ends now
                    # instead of keeping a worker waiting (BL-016, Fase 3).
                    return {"status": "success", "absorbed": True, "compiled_count": 0, "processed_count": 0,
                            "waiting_count": 0, "pending_count": None}
                waiting_count = 0
                for _batch in range(self.MAX_BATCHES_PER_RUN):
                    pending_captures = self.memory_repo.get_pending_captures(company.id, limit=limit)
                    if not pending_captures:
                        break
                    batch_waiting = 0
                    for capture in pending_captures:
                        agent_key = self._agent_for(capture)
                        if agent_key and not SystemAgentRunner.is_enabled(agent_key):
                            # Its agent is turned off by the platform: the capture stays
                            # pending and is compiled when the agent is turned on again.
                            batch_waiting += 1
                            continue
                        processed_count += 1
                        compiled = self._compile_capture_safely(company, capture)
                        if compiled is None:
                            batch_waiting += 1
                        elif compiled:
                            compiled_count += 1
                        if time.monotonic() - started > self.MAX_RUN_SECONDS:
                            stopped = "time_limit"
                            break
                    waiting_count += batch_waiting
                    if stopped or batch_waiting == len(pending_captures):
                        # Out of time, or nothing in this batch could move.
                        break
            if stopped:
                break
            # A capture saved just as the lock was released found it taken and was
            # absorbed: it is pending now, and this run takes it.
            if len(self.memory_repo.get_pending_captures(company.id, limit=limit)) <= waiting_count:
                break

        return {
            "status": "success",
            "compiled_count": compiled_count,
            "processed_count": processed_count,
            "waiting_count": waiting_count,
            "pending_count": len(self.memory_repo.get_pending_captures(company.id, limit=limit)),
            # The task stopped to free its worker; the caller queues the rest.
            "stopped": stopped,
        }

    def compile_pending_for_user(self, company_short_name: str, user_identifier: str | None = None, limit: int = 12) -> dict:
        """Kept for callers of the per-user Memoria; compiles the whole company."""
        return self.compile_pending_for_company(company_short_name, limit=limit)

    @contextmanager
    def _company_lock(self, company_id: int):
        """
        One compilation run per company at a time, across workers and web
        processes; yields whether this run holds it. It does not wait: a run that
        finds it taken leaves (the holder drains what is pending), so no worker
        is kept waiting (BL-016, Fase 3). Postgres advisory lock on a dedicated
        connection; on SQLite (tests) it is always held.
        """
        with advisory_lock(self.db_manager, self.ADVISORY_LOCK_NAMESPACE, company_id, wait=False) as held:
            yield held

    def _agent_for(self, capture: MemoryCapture) -> str | None:
        """The system agent that reads the capture, as its source declares (memory_sources)."""
        meta = dict(capture.meta or {})
        return MemorySourceRegistry.for_capture(meta).agent_for(meta)

    def _compile_capture_safely(self, company: Company, capture: MemoryCapture) -> bool | None:
        """Whether the capture became a page; None when it stays pending (its agent was turned off)."""
        items = self.memory_repo.list_capture_items(capture.id)
        if not items:
            self._mark_capture_compiled(capture, items)
            return False
        try:
            for item in items:
                self._enrich_item(company.short_name, item)
            return self._compile_single_capture(company, capture, items)
        except SystemAgentDisabled:
            # Turned off while this run was going: leave it pending, untouched.
            self.memory_repo.rollback()
            return None
        except Exception as exc:
            logging.exception("Memory compilation failed for capture %s: %s", capture.id, exc)
            self.memory_repo.rollback()
            capture.status = MemoryCaptureStatus.FAILED
            capture.compile_error = str(exc)
            self.memory_repo.save_capture(capture)
            for item in items:
                item.status = MemoryItemStatus.FAILED
                item.compile_error = str(exc)
                self.memory_repo.save_item(item)
            return False

    def _compile_single_capture(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> bool:
        """Reads the capture with the step its source declares (memory_sources)."""
        source = MemorySourceRegistry.for_capture(dict(capture.meta or {}))
        return getattr(self, source.handler)(company, capture, items)

    def _compile_person_capture(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> bool:
        """What a person explained, filed into the pages it belongs to."""
        author = self._author_label(capture.user_identifier)
        captured_on = (capture.created_at or datetime.now()).date().isoformat()

        for attempt in range(1, self.MAX_SAVE_ATTEMPTS + 1):
            candidates = self._load_candidate_pages(company, capture, items)
            compiled = self._compile_with_llm(company, capture, items, candidates, author, captured_on)
            if not compiled:
                compiled = self._compile_with_fallback(capture, items, candidates, author, captured_on)

            if compiled.get("action") == "skip":
                self._mark_capture_compiled(capture, items)
                return False

            response = self._write_page(
                company,
                compiled,
                candidates,
                edited_by=capture.user_identifier,
                default_title=self._default_page_title(capture, items),
                revision_metadata={
                    "source": self.COMPILER_SOURCE,
                    "capture_id": capture.id,
                    "author": capture.user_identifier,
                },
            )

            if response.get("status") == "success":
                page = response.get("page") or {}
                page_id = page.get("id")
                self.memory_repo.add_page_sources(company.id, page_id, [item.id for item in items])
                self._record_conflicts(company, page_id, capture, compiled.get("conflicts"))
                capture.meta = {**dict(capture.meta or {}), "wiki_page_id": page_id}
                self._mark_capture_compiled(capture, items)
                return True

            if response.get("error_code") == TenantWikiService.ERROR_PAGE_CHANGED:
                # Someone saved the page while the model worked on it: start over
                # from what is there now rather than overwrite their change.
                logging.info(
                    "Memory page changed while compiling capture %s (attempt %s); recompiling.",
                    capture.id,
                    attempt,
                )
                continue

            raise RuntimeError(response.get("error_message") or "could not save memory page")

        raise RuntimeError("memory page kept changing while compiling; retry later")

    def _write_page(self,
                    company: Company,
                    compiled: dict,
                    candidates: list[dict],
                    *,
                    edited_by: str,
                    default_title: str,
                    revision_metadata: dict) -> dict:
        """Creates or updates the page the model returned; the wiki's response (it may say the page changed)."""
        target = self._resolve_target(compiled, candidates)
        title = str(compiled.get("title") or (target or {}).get("title") or default_title).strip()
        summary = str(compiled.get("summary") or "").strip()
        body = str(compiled.get("markdown") or "").strip() or f"# {title}\n"
        change_summary = str(compiled.get("change_summary") or "").strip() or None
        if target is None:
            return self.memory_wiki_service.create_page(
                company.short_name,
                title=title,
                summary=summary,
                body=body,
                edited_by=edited_by,
                change_summary=change_summary,
                revision_metadata=revision_metadata,
            )
        return self.memory_wiki_service.update_page(
            company.short_name,
            page=target,
            title=title,
            summary=summary,
            body=body,
            edited_by=edited_by,
            change_summary=change_summary,
            revision_metadata=revision_metadata,
        )

    # =====================================================================
    # Documents (BL-014): a RAG document read whole, part by part
    # =====================================================================

    def _ingest_document(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> bool:
        """
        Brings what a document teaches into the wiki. The document is read whole,
        one part at a time; each part sees the pages the previous parts wrote.
        Every fact is attributed to the document, and each page it touches
        records that it cites it (iat_memory_page_documents).
        """
        meta = dict(capture.meta or {})
        document_id = self._as_int(meta.get("document_id"))
        label = str(meta.get("label") or capture.title or f"Documento {document_id}").strip()
        parts = self._document_parts(document_id) if document_id else []
        images = [] if parts or not document_id else self._document_images(company, document_id)
        if not parts and not images:
            capture.meta = {**meta, "result": "empty"}
            self._mark_capture_compiled(capture, items)
            return False

        captured_on = (capture.created_at or datetime.now()).date().isoformat()
        source = {"label": label, "card": meta.get("card") or {}, "path": meta.get("path") or ""}
        if meta.get("kind"):
            source["kind"] = meta["kind"]
        # What reads each step: a part of the text, or the document's images (it had no text).
        if parts:
            readers = [
                (part_text, lambda candidates, index=index, part_text=part_text: self._ingest_part_with_llm(
                    company, capture, source, {"index": index, "total": len(parts), "text": part_text},
                    candidates, captured_on))
                for index, part_text in enumerate(parts, start=1)
            ]
        else:
            readers = [("", lambda candidates: self._ingest_image_with_llm(
                company, capture, source, images, candidates, captured_on))]
        revision_metadata = {
            "source": self.COMPILER_SOURCE,
            "capture_id": capture.id,
            "author": capture.user_identifier,
            "mode": self.DOCUMENT_MODE,
            "document_id": document_id,
        }
        touched: list[int] = []
        for index, (part_text, read) in enumerate(readers, start=1):
            for attempt in range(1, self.MAX_SAVE_ATTEMPTS + 1):
                candidates = self._document_candidates(company, source, part_text, touched)
                answer = read(candidates)
                if answer is None:
                    raise RuntimeError(f"the model could not read part {index} of {len(readers)}")
                pages, conflicts = answer
                written: dict[str, int] = {}
                page_changed = False
                for compiled in pages[:self.MAX_PAGES_PER_PART]:
                    response = self._write_page(
                        company, compiled, candidates,
                        edited_by=capture.user_identifier,
                        default_title=label,
                        revision_metadata=revision_metadata,
                    )
                    if response.get("status") == "success":
                        page_id = (response.get("page") or {}).get("id")
                        self.memory_repo.add_page_sources(company.id, page_id, [item.id for item in items])
                        self.memory_repo.add_page_document(company.id, page_id, document_id, label)
                        written[str(compiled.get("title") or "").strip().lower()] = page_id
                        if page_id not in touched:
                            touched.append(page_id)
                        continue
                    if response.get("error_code") == TenantWikiService.ERROR_PAGE_CHANGED:
                        logging.info("Memory page changed while reading part %s of document %s (attempt %s); rereading.",
                                     index, document_id, attempt)
                        page_changed = True
                        break
                    raise RuntimeError(response.get("error_message") or "could not save memory page")
                if not page_changed:
                    for conflict in conflicts:
                        # Placed on the page of this part it names; a part that wrote one page gets them all.
                        title = str(conflict.get("page_title") or "").strip().lower()
                        page_id = written.get(title) or (next(iter(written.values())) if len(written) == 1 else None)
                        if page_id:
                            self._record_conflicts(company, page_id, capture, [conflict])
                    break
            else:
                raise RuntimeError("memory page kept changing while reading the document; retry later")

        capture.meta = {**meta, "wiki_page_ids": touched, "parts": len(readers), "images": len(images),
                        "wiki_page_id": touched[0] if touched else None}
        self._mark_capture_compiled(capture, items)
        return bool(touched)

    def _mark_document_obsolete(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> bool:
        """
        A document that fed the wiki was deleted (BL-014). On every page that cites
        it, each line attributed to it — "(<label>, YYYY-MM-DD)", as the reader
        writes them — gets an obsolete mark; nothing is erased, and the page waits
        for someone to review it. Done without the model: the attribution says
        exactly which lines came from the document.
        """
        meta = dict(capture.meta or {})
        document_id = self._as_int(meta.get("document_id"))
        today = (capture.created_at or datetime.now()).date().isoformat()
        replaced = meta.get("reason") == "replaced"
        mark = self.OBSOLETE_REPLACED_MARK if replaced else self.OBSOLETE_MARK
        why = "hay una versión nueva del documento" if replaced else "se eliminó el documento"
        # A replaced version marks only lines from before this capture: if the new
        # version was already read (a retry that ran late), its lines stay.
        before = today if replaced else None
        marked_pages = []
        for link in self.memory_repo.list_document_links(company.id, document_id):
            labels = {label for label in (link.label, meta.get("label")) if label}
            for _ in range(self.MAX_SAVE_ATTEMPTS):
                page = self.memory_wiki_service.get_page(company.short_name, link.wiki_page_id)
                if not page:
                    break
                body = self.memory_wiki_service.page_body(page)
                marked = self._mark_obsolete_lines(body, labels, today, mark=mark, before=before)
                if marked == body:
                    break
                response = self.memory_wiki_service.update_page(
                    company.short_name,
                    page=page,
                    title=str(page.get("title") or "").strip(),
                    summary=str(page.get("summary") or "").strip(),
                    body=marked,
                    edited_by=capture.user_identifier,
                    change_summary=f"Datos de «{sorted(labels)[0] if labels else document_id}» marcados como obsoletos: {why}.",
                    revision_metadata={
                        "source": self.COMPILER_SOURCE,
                        "capture_id": capture.id,
                        "author": capture.user_identifier,
                        "mode": self.DOCUMENT_REMOVED_MODE,
                        "document_id": document_id,
                    },
                )
                if response.get("status") == "success":
                    marked_pages.append(link.wiki_page_id)
                    break
                if response.get("error_code") != TenantWikiService.ERROR_PAGE_CHANGED:
                    raise RuntimeError(response.get("error_message") or "could not save memory page")
            link.removed_at = datetime.now()
            self.memory_repo.commit()
        capture.meta = {**meta, "result": "obsolete_marked", "wiki_page_ids": marked_pages}
        self._mark_capture_compiled(capture, items)
        return bool(marked_pages)

    @classmethod
    def _mark_obsolete_lines(cls, body: str, labels: set[str], day: str, *, mark: str | None = None,
                             before: str | None = None) -> str:
        """Marks each line attributed to the document; with `before`, only those dated earlier."""
        mark = mark or cls.OBSOLETE_MARK
        patterns = [re.compile(r"\(\s*" + re.escape(label) + r"\s*,\s*(\d{4}-\d{2}-\d{2})\s*\)") for label in labels]
        lines = []
        for line in str(body or "").split("\n"):
            if cls.OBSOLETE_PREFIX not in line:
                dates = [match.group(1) for pattern in patterns for match in pattern.finditer(line)]
                if dates and (before is None or min(dates) < before):
                    line = f"{line.rstrip()} **[{mark}, {day}]**"
            lines.append(line)
        return "\n".join(lines)

    def _document_images(self, company: Company, document_id: int) -> list[dict]:
        """The images of a document that has no text (an image loaded as a document), to look at."""
        images = []
        for image in self.document_repo.get_document_images(document_id, limit=self.MAX_IMAGES_PER_SOURCE) or []:
            image_dict = self._image_payload(company.short_name, getattr(image, "storage_key", None))
            if image_dict:
                images.append(image_dict)
        return images

    def _image_payload(self, company_short_name: str, storage_key: str | None, filename: str | None = None,
                       mime_type: str | None = None) -> dict | None:
        storage_key = str(storage_key or "").strip()
        if not storage_key:
            return None
        try:
            content = self.storage_service.get_document_content(company_short_name, storage_key)
        except Exception as exc:
            logging.warning("Memory image '%s' could not be read: %s", storage_key, exc)
            return None
        if not isinstance(content, (bytes, bytearray)) or not content or len(content) > self.MAX_IMAGE_BYTES:
            return None
        name = str(filename or storage_key.rsplit("/", 1)[-1] or "image").strip()
        return {
            "name": name,
            "mime_type": str(mime_type or mimetypes.guess_type(name)[0] or "image/png").lower(),
            "base64": base64.b64encode(content).decode("ascii"),
        }

    def _build_capture_images(self, company_short_name: str, items: list[MemoryItem]) -> list[dict]:
        """Images people attached to a capture, for the compiler to look at when its model can."""
        images = []
        for item in items or []:
            if len(images) >= self.MAX_IMAGES_PER_SOURCE:
                break
            mime_type = str(getattr(item, "mime_type", None) or "").lower()
            if item.item_type != MemoryItemType.IMAGE and not mime_type.startswith("image/"):
                continue
            payload = self._image_payload(company_short_name, item.storage_key, item.filename, mime_type or None)
            if payload:
                images.append(payload)
        return images

    def _document_parts(self, document_id: int) -> list[str]:
        """The document's text, from its RAG fragments in order, in parts of at most DOCUMENT_PART_CHARS."""
        rows = (
            self.document_repo.session.query(VSDoc.text)
            .filter(VSDoc.document_id == document_id)
            .order_by(VSDoc.id.asc())
            .all()
        )
        parts, current, size = [], [], 0
        for (chunk,) in rows:
            chunk = str(chunk or "").strip()
            while chunk:
                room = self.DOCUMENT_PART_CHARS - size
                piece, chunk = chunk[:room], chunk[room:]
                current.append(piece)
                size += len(piece)
                if size >= self.DOCUMENT_PART_CHARS:
                    parts.append("\n\n".join(current))
                    current, size = [], 0
        if current:
            parts.append("\n\n".join(current))
        return parts

    def _document_candidates(self, company: Company, source: dict, part_text: str, touched: list[int]) -> list[dict]:
        """The pages this document already wrote first, then the ones its part is most likely about."""
        ordered: list[int] = list(touched)
        card = source.get("card") or {}
        query = " ".join(part for part in (
            str(source.get("label") or ""), str(card.get("summary") or ""), part_text[:300],
        ) if part).strip()
        if query:
            for result in self.memory_wiki_service.search_pages(company.short_name, query, limit=self.MAX_CANDIDATE_PAGES):
                if result.get("id") not in ordered:
                    ordered.append(result.get("id"))
        candidates = []
        for page_id in ordered[:self.MAX_CANDIDATE_PAGES + len(touched)]:
            page = self.memory_wiki_service.get_page(company.short_name, page_id)
            if page:
                candidates.append(page)
        return candidates

    def _wiki_context(self, company: Company, candidates: list[dict]) -> dict:
        return {
            "wiki_schema": str(self.memory_wiki_service.read_schema() or "")[:7000],
            "page_index": [
                {"page_id": entry.get("id"), "title": entry.get("title"), "summary": entry.get("summary")}
                for entry in (self.memory_wiki_service.list_pages(company.short_name) or [])[:self.MAX_INDEX_ENTRIES_IN_PROMPT]
            ],
            "candidate_pages": [
                {"page_id": page.get("id"), "title": page.get("title"),
                 "markdown": self.memory_wiki_service.page_body(page)}
                for page in candidates
            ],
        }

    def _ingest_part_with_llm(self,
                              company: Company,
                              capture: MemoryCapture,
                              source: dict,
                              part: dict,
                              candidates: list[dict],
                              captured_on: str):
        return self._ingest_with_llm(
            company, capture, self._agent_for(capture) or self.DOCUMENT_AGENT,
            {"source": source, "part": part, "captured_on": captured_on, **self._wiki_context(company, candidates)},
            question=f"Read memory document {source.get('label')} (part {part['index']} of {part['total']})",
        )

    def _ingest_image_with_llm(self,
                               company: Company,
                               capture: MemoryCapture,
                               source: dict,
                               images: list[dict],
                               candidates: list[dict],
                               captured_on: str):
        return self._ingest_with_llm(
            company, capture, self.IMAGE_AGENT,
            {"source": source, "captured_on": captured_on, **self._wiki_context(company, candidates)},
            question=f"Look at memory image {source.get('label')}",
            images=images,
        )

    def _ingest_with_llm(self, company: Company, capture: MemoryCapture, agent_key: str, inputs: dict, *,
                         question: str, images: list | None = None):
        """The pages and the contradictions a reader agent returned, or None when it could not be reached."""
        try:
            response = self.system_agent_runner.run(
                company, agent_key, inputs,
                user_identifier=capture.user_identifier,
                question=question,
                images=images,
            )
        except SystemAgentDisabled:
            raise
        except Exception as exc:
            logging.warning("Memory capture %s (%s): the model could not be reached: %s", capture.id, agent_key, exc)
            return None
        structured = response.get("structured_output") or response.get("parsed_output")
        if not isinstance(structured, dict):
            return None
        conflicts = [c for c in (structured.get("conflicts") or []) if isinstance(c, dict)]
        raw_pages = structured.get("pages")
        if not isinstance(raw_pages, list):
            # A single page answered without the list around it.
            raw_pages = [structured] if structured.get("markdown") or structured.get("action") else []
        pages = []
        for raw in raw_pages:
            page = self._normalize_compiled_output(raw)
            if not isinstance(page, dict):
                continue
            if page.get("action") not in {"create", "update"} or not str(page.get("markdown") or "").strip():
                continue
            pages.append(page)
        return pages, conflicts

    def _record_conflicts(self, company: Company, page_id: int | None, capture: MemoryCapture, conflicts) -> int:
        """Contradictions the model found while writing a page, for "Necesita atención" (BL-014)."""
        if not page_id or not isinstance(conflicts, list):
            return 0
        recorded = 0
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            existing = str(conflict.get("existing_statement") or "").strip()
            new = str(conflict.get("new_statement") or "").strip()
            if not existing or not new:
                continue
            self.memory_repo.add_conflict(MemoryConflict(
                company_id=company.id,
                wiki_page_id=page_id,
                capture_id=capture.id,
                existing_statement=existing[:2000],
                existing_source=str(conflict.get("existing_source") or "").strip()[:300] or None,
                new_statement=new[:2000],
                new_source=str(conflict.get("new_source") or "").strip()[:300] or None,
                status=MemoryConflict.STATUS_OPEN,
            ))
            recorded += 1
        return recorded

    @staticmethod
    def _as_int(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _apply_correction(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> bool:
        """
        Applies a correction someone asked for on one page, and only that change.

        Never falls back to appending the text: a correction the model could not
        apply is reported as not applied, with the reason, instead of being
        written as a new fact. The outcome and the revisions before and after
        go to the capture's meta, which is what the screen shows as the diff and
        what "undo" restores.
        """
        meta = dict(capture.meta or {})
        author = self._author_label(capture.user_identifier)
        captured_on = (capture.created_at or datetime.now()).date().isoformat()

        def finish(result: str, reason: str | None = None, **extra) -> bool:
            capture.meta = {**meta, "result": result, "reason": reason, **extra}
            self._mark_capture_compiled(capture, items)
            return result == self.CORRECTION_APPLIED

        for _ in range(self.MAX_SAVE_ATTEMPTS):
            page = self.memory_wiki_service.get_page(company.short_name, meta.get("wiki_page_id"))
            if not page:
                return finish(self.CORRECTION_NOT_APPLIED, "La página ya no existe.")
            compiled = self._compile_correction_with_llm(company, capture, items, page, author, captured_on)
            if not compiled:
                return finish(self.CORRECTION_FAILED, "No se pudo consultar al modelo. Intenta de nuevo.")
            if compiled.get("action") == "skip":
                return finish(
                    self.CORRECTION_NOT_APPLIED,
                    str(compiled.get("change_summary") or "").strip() or "No encontré en la página qué cambiar.",
                )

            revisions = self.memory_wiki_service.list_revisions(company.short_name, path=page.get("path"), limit=1)
            before_revision_id = revisions[0].get("id") if revisions else None
            response = self.memory_wiki_service.update_page(
                company.short_name,
                page=page,
                title=str(compiled.get("title") or page.get("title") or "").strip(),
                summary=str(compiled.get("summary") or page.get("summary") or "").strip(),
                body=str(compiled.get("markdown") or "").strip(),
                edited_by=capture.user_identifier,
                change_summary=str(compiled.get("change_summary") or "").strip() or "Corrección pedida a la IA",
                revision_metadata={
                    "source": self.COMPILER_SOURCE,
                    "capture_id": capture.id,
                    "author": capture.user_identifier,
                    "mode": self.CORRECTION_MODE,
                },
            )
            if response.get("status") == "success":
                self.memory_repo.add_page_sources(company.id, page.get("id"), [item.id for item in items])
                after = self.memory_wiki_service.list_revisions(company.short_name, path=page.get("path"), limit=1)
                return finish(
                    self.CORRECTION_APPLIED,
                    str(compiled.get("change_summary") or "").strip() or None,
                    revision_before_id=before_revision_id,
                    revision_after_id=after[0].get("id") if after else None,
                )
            if response.get("error_code") != TenantWikiService.ERROR_PAGE_CHANGED:
                return finish(self.CORRECTION_FAILED, response.get("error_message") or "No se pudo guardar la página.")
            # Someone saved the page meanwhile: apply the correction to what is there now.
        return finish(self.CORRECTION_FAILED, "La página cambió varias veces mientras se corregía. Intenta de nuevo.")

    def _compile_correction_with_llm(self,
                                     company: Company,
                                     capture: MemoryCapture,
                                     items: list[MemoryItem],
                                     page: dict,
                                     author: str,
                                     captured_on: str) -> dict | None:
        request = "\n".join(str(item.content_text or "").strip() for item in items if str(item.content_text or "").strip())
        try:
            response = self.system_agent_runner.run(
                company,
                self.CORRECTION_AGENT,
                {
                    "author": author,
                    "captured_on": captured_on,
                    "request": request,
                    "page": {
                        "id": page.get("id"),
                        "title": page.get("title") or "",
                        "markdown": self.memory_wiki_service.page_body(page),
                    },
                },
                user_identifier=capture.user_identifier,
                question=f"Apply memory correction {capture.id}",
            )
        except SystemAgentDisabled:
            raise
        except Exception as exc:
            logging.warning("Memory correction %s could not reach the model: %s", capture.id, exc)
            return None
        structured = self._normalize_compiled_output(
            response.get("structured_output") or response.get("parsed_output")
        )
        if not isinstance(structured, dict):
            return None
        if structured.get("action") in {"create", "update"}:
            structured["action"] = "update"
        if structured.get("action") not in {"update", "skip"}:
            return None
        if structured.get("action") == "update" and not str(structured.get("markdown") or "").strip():
            return None
        return structured

    def _mark_capture_compiled(self, capture: MemoryCapture, items: list[MemoryItem]) -> None:
        for item in items:
            item.status = MemoryItemStatus.COMPILED
            item.compile_error = None
            item.last_compiled_at = datetime.now()
            self.memory_repo.save_item(item)
        capture.status = MemoryCaptureStatus.COMPILED
        capture.compile_error = None
        capture.last_compiled_at = datetime.now()
        self.memory_repo.save_capture(capture)

    def _load_candidate_pages(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> list[dict]:
        """Pages the capture most likely belongs to, read in full (markdown and checksum)."""
        ordered_ids: list[int] = []

        def add(page_id):
            if isinstance(page_id, int) and page_id not in ordered_ids:
                ordered_ids.append(page_id)

        add(dict(capture.meta or {}).get("wiki_page_id"))
        for page_id in self.memory_repo.list_page_ids_for_items([item.id for item in items if getattr(item, "id", None)]):
            add(page_id)
        query = self._memory_capture_query(capture, items)
        if query:
            for result in self.memory_wiki_service.search_pages(company.short_name, query, limit=self.MAX_CANDIDATE_PAGES):
                add(result.get("id"))

        candidates = []
        for page_id in ordered_ids:
            if len(candidates) >= self.MAX_CANDIDATE_PAGES:
                break
            page = self.memory_wiki_service.get_page(company.short_name, page_id)
            if page:
                candidates.append(page)
        return candidates

    @staticmethod
    def _resolve_target(compiled: dict, candidates: list[dict]) -> dict | None:
        if compiled.get("action") != "update":
            return None
        target_page_id = compiled.get("target_page_id")
        for candidate in candidates:
            if candidate.get("id") == target_page_id:
                return candidate
        # The model asked to update a page it was not shown: the best candidate
        # is the only page whose current content it may have taken into account.
        return candidates[0] if candidates else None

    def _compile_with_llm(self,
                          company: Company,
                          capture: MemoryCapture,
                          items: list[MemoryItem],
                          candidates: list[dict],
                          author: str,
                          captured_on: str) -> dict | None:
        inputs = self._compiler_inputs(
            capture,
            items,
            candidates,
            author=author,
            captured_on=captured_on,
            wiki_schema=self.memory_wiki_service.read_schema(),
            index_entries=self.memory_wiki_service.list_pages(company.short_name),
        )
        native_pdf_attachments = self._build_capture_native_pdf_attachments(company.short_name, items)
        try:
            response = self.system_agent_runner.run(
                company,
                self.COMPILER_AGENT,
                inputs,
                user_identifier=capture.user_identifier,
                question=f"Compile memory capture {capture.id}",
                attachments=native_pdf_attachments,
                images=self._build_capture_images(company.short_name, items),
            )
        except SystemAgentDisabled:
            raise
        except Exception as exc:
            logging.warning("Memory compiler LLM fallback activated for capture %s: %s", capture.id, exc)
            return None

        structured = self._normalize_compiled_output(
            response.get("structured_output") or response.get("parsed_output")
        )
        if not isinstance(structured, dict) or structured.get("action") not in {"create", "update", "skip"}:
            return None
        if structured.get("action") != "skip" and not str(structured.get("markdown") or "").strip():
            return None
        return structured

    @staticmethod
    def _normalize_compiled_output(structured) -> dict | None:
        """
        The schema is best effort, so models sometimes nest the page under
        `page`, name the body `content_markdown` or the action `decision`.
        Accept those shapes instead of discarding a good page for the fallback.
        """
        if not isinstance(structured, dict):
            return None
        normalized = dict(structured)
        if "action" not in normalized and "decision" in normalized:
            normalized["action"] = normalized.get("decision")
        normalized["action"] = str(normalized.get("action") or "").strip().lower()
        nested = normalized.pop("page", None)
        if isinstance(nested, dict):
            for key, value in nested.items():
                normalized.setdefault(key, value)
        if not str(normalized.get("markdown") or "").strip():
            for alias in ("content_markdown", "body", "content"):
                if str(normalized.get(alias) or "").strip():
                    normalized["markdown"] = normalized[alias]
                    break
        return normalized

    def _compile_with_fallback(self,
                               capture: MemoryCapture,
                               items: list[MemoryItem],
                               candidates: list[dict],
                               author: str,
                               captured_on: str) -> dict:
        """Without a model: append the capture's main fact, attributed, to the best page."""
        fact = f"- {self._primary_fact(items)} ({author}, {captured_on})"
        target = candidates[0] if candidates else None
        if target:
            body = self.memory_wiki_service.page_body(target)
            return {
                "action": "update",
                "target_page_id": target.get("id"),
                "title": target.get("title") or self._default_page_title(capture, items),
                "summary": target.get("summary") or "",
                "markdown": f"{body}\n{fact}".strip(),
                "change_summary": "Agregado sin modelo de lenguaje.",
            }
        title = self._default_page_title(capture, items)
        return {
            "action": "create",
            "target_page_id": None,
            "title": title,
            "summary": self._primary_fact(items)[:240],
            "markdown": f"# {title}\n\n{fact}",
            "change_summary": "Creada sin modelo de lenguaje.",
        }

    def _compiler_inputs(self,
                         capture: MemoryCapture,
                         items: list[MemoryItem],
                         candidates: list[dict],
                         *,
                         author: str,
                         captured_on: str,
                         wiki_schema: str = "",
                         index_entries: list[dict] | None = None) -> dict:
        """What the memory_compiler agent receives (see its prompt)."""
        return {
            "author": author,
            "captured_on": captured_on,
            "wiki_schema": str(wiki_schema or "")[:7000],
            "page_index": [
                {"page_id": entry.get("id"), "title": entry.get("title"), "summary": entry.get("summary")}
                for entry in (index_entries or [])[:self.MAX_INDEX_ENTRIES_IN_PROMPT]
            ],
            "capture": {
                "capture_id": capture.id,
                "author": author,
                "date": captured_on,
                "title": capture.title,
                "items": [
                    {
                        "id": item.id,
                        "item_type": item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type),
                        "title": item.title,
                        "content_text": item.content_text,
                        "source_url": item.source_url,
                        "filename": item.filename,
                        "mime_type": item.mime_type,
                    }
                    for item in items
                ],
            },
            "candidate_pages": [
                {
                    "page_id": page.get("id"),
                    "title": page.get("title"),
                    "markdown": self.memory_wiki_service.page_body(page),
                }
                for page in candidates or []
            ],
        }

    def _author_label(self, user_identifier: str | None) -> str:
        identifier = str(user_identifier or "").strip()
        if not identifier:
            return "alguien"
        try:
            user = self.profile_repo.get_user_by_email(identifier) if "@" in identifier else None
        except Exception:
            user = None
        if user is not None:
            name = " ".join(
                part for part in (str(getattr(user, "first_name", "") or "").strip(),
                                  str(getattr(user, "last_name", "") or "").strip())
                if part
            )
            if name:
                return name
        return identifier

    def _build_capture_native_pdf_attachments(self, company_short_name: str, items: list[MemoryItem]) -> list[dict]:
        attachments = []
        seen_storage_keys = set()

        for item in items or []:
            if len(attachments) >= self.MAX_NATIVE_PDF_ATTACHMENTS_PER_CAPTURE:
                break
            if not self._is_pdf_item(item):
                continue

            storage_key = str(getattr(item, "storage_key", "") or "").strip()
            if not storage_key or storage_key in seen_storage_keys:
                continue

            try:
                file_bytes = self.storage_service.get_document_content(company_short_name, storage_key)
            except Exception as exc:
                logging.warning("Could not load memory PDF attachment '%s' for compilation: %s", storage_key, exc)
                continue

            if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
                continue
            if len(file_bytes) > self.MAX_NATIVE_PDF_ATTACHMENT_BYTES:
                logging.info(
                    "Skipping memory PDF attachment '%s' during compilation because it exceeds %s bytes.",
                    storage_key,
                    self.MAX_NATIVE_PDF_ATTACHMENT_BYTES,
                )
                continue

            filename = str(getattr(item, "filename", None) or "attachment.pdf").strip()
            mime_type = str(
                getattr(item, "mime_type", None)
                or mimetypes.guess_type(filename)[0]
                or "application/pdf"
            ).strip().lower()

            seen_storage_keys.add(storage_key)
            attachments.append({
                "name": filename,
                "mime_type": mime_type,
                "base64": base64.b64encode(file_bytes).decode("ascii"),
                "size_bytes": len(file_bytes),
            })

        return attachments

    @staticmethod
    def _is_pdf_item(item: MemoryItem) -> bool:
        mime_type = str(getattr(item, "mime_type", None) or "").strip().lower()
        filename = str(getattr(item, "filename", None) or "").strip().lower()
        item_type = getattr(item, "item_type", None)
        return (
            item_type == MemoryItemType.FILE
            and (
                mime_type == "application/pdf"
                or filename.endswith(".pdf")
            )
        )

    def _enrich_item(self, company_short_name: str, item: MemoryItem) -> None:
        if item.item_type != MemoryItemType.LINK or item.content_text:
            return
        if not item.source_url:
            return

        try:
            # A link a person saved: never a private, loopback or metadata address,
            # and every redirect checked the same way (SSRF).
            response = fetch_with_safe_redirects(
                item.source_url, allowed_schemes=("http", "https"), label="Memory link",
                timeout=8, stream=True, headers={"User-Agent": "IAToolkit Memory/1.0"})
            response.raise_for_status()
            raw = response.raw.read(self.LINK_FETCH_MAX_BYTES, decode_content=True)
            response.close()
            html = raw.decode(response.encoding or "utf-8", errors="replace")
        except Exception as exc:
            logging.warning("Could not fetch memory link %s: %s", item.source_url, exc)
            return

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = unescape(title_match.group(1).strip()) if title_match else item.title or item.source_url

        stripped = re.sub(r"(?is)<script.*?>.*?</script>|<style.*?>.*?</style>", " ", html)
        stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
        stripped = re.sub(r"\s+", " ", unescape(stripped)).strip()
        snapshot = stripped[:4000]

        item.title = item.title or title[:200]
        item.content_text = f"{title}\n\n{snapshot}".strip()
        item.source_meta = dict(item.source_meta or {})
        item.source_meta["link_title"] = title[:200]
        self.memory_repo.save_item(item)

    def _memory_capture_query(self, capture: MemoryCapture, items: list[MemoryItem]) -> str:
        parts = [str(capture.title or "").strip()]
        for item in items:
            parts.extend([
                str(item.title or "").strip(),
                str(item.content_text or "").strip()[:180],
                str(item.filename or "").strip(),
            ])
        return " ".join(part for part in parts if part).strip()

    def _default_page_title(self, capture: MemoryCapture, items: list[MemoryItem]) -> str:
        if capture.title:
            return capture.title[:120]
        for item in items:
            if item.title:
                return item.title[:120]
            if item.item_type == MemoryItemType.LINK and item.source_url:
                return item.source_url
            if item.filename:
                return item.filename
        return f"Memoria {capture.id}"

    def _primary_fact(self, items: list[MemoryItem]) -> str:
        for item in items:
            if item.content_text:
                first_line = str(item.content_text).strip().splitlines()[0]
                return first_line[:240]
        for item in items:
            if item.source_url:
                return f"Link: {item.source_url}"
            if item.filename:
                return f"Archivo: {item.filename}"
        item = items[0]
        return f"{item.item_type.value if hasattr(item.item_type, 'value') else item.item_type}"


register_core_sources(
    compiler_agent=MemoryCompilerService.COMPILER_AGENT,
    correction_agent=MemoryCompilerService.CORRECTION_AGENT,
    document_agent=MemoryCompilerService.DOCUMENT_AGENT,
    meeting_agent=MemoryCompilerService.MEETING_AGENT,
    correction_mode=MemoryCompilerService.CORRECTION_MODE,
    document_mode=MemoryCompilerService.DOCUMENT_MODE,
    document_removed_mode=MemoryCompilerService.DOCUMENT_REMOVED_MODE,
    meeting_kind=MemoryCompilerService.MEETING_KIND,
)
