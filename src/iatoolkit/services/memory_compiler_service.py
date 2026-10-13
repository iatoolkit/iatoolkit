# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from contextlib import contextmanager
from datetime import datetime
from html import unescape

import requests
from injector import inject
from sqlalchemy import text

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.memory_repo import MemoryRepo
from iatoolkit.repositories.models import Company, MemoryCapture, MemoryCaptureStatus, MemoryItem, MemoryItemStatus, MemoryItemType
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.memory_wiki_service import MemoryWikiService
from iatoolkit.services.storage_service import StorageService
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
    MAX_SAVE_ATTEMPTS = 3
    COMPILER_SOURCE = "memory_compiler"
    # A capture that asks to change one page (Memoria → "¿Qué hay que corregir?").
    CORRECTION_MODE = "correction"
    CORRECTION_APPLIED = "applied"
    CORRECTION_NOT_APPLIED = "not_applied"
    CORRECTION_FAILED = "failed"
    # First key of the two-key Postgres advisory lock; the second is the company id.
    ADVISORY_LOCK_NAMESPACE = 734001

    PAGE_SCHEMA = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update", "skip"]},
            "target_page_id": {
                "anyOf": [
                    {"type": "integer"},
                    {"type": "null"},
                ]
            },
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "markdown": {"type": "string"},
            "change_summary": {"type": "string"},
        },
        # Only what a page cannot do without: models often drop the optional
        # fields, and a near miss is repaired by _normalize_compiled_output.
        "required": [
            "action",
            "target_page_id",
            "title",
            "markdown",
        ],
        "additionalProperties": False,
    }

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 memory_repo: MemoryRepo,
                 memory_wiki_service: MemoryWikiService,
                 llm_client: llmClient,
                 configuration_service: ConfigurationService,
                 storage_service: StorageService,
                 db_manager: DatabaseManager):
        self.profile_repo = profile_repo
        self.memory_repo = memory_repo
        self.memory_wiki_service = memory_wiki_service
        self.llm_client = llm_client
        self.configuration_service = configuration_service
        self.storage_service = storage_service
        self.db_manager = db_manager

    def compile_pending_for_company(self, company_short_name: str, limit: int = 12) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "compiled_count": 0, "error_message": "company not found"}
        wiki = self.memory_wiki_service.ensure_wiki(company_short_name)
        if wiki.get("status") != "success":
            return {"status": "error", "compiled_count": 0, "error_message": wiki.get("error_message")}

        compiled_count = 0
        processed_count = 0
        with self._company_lock(company.id):
            # Keep draining: a capture saved while this run held the lock waited
            # for it instead of compiling concurrently, and must not be left behind.
            for _ in range(self.MAX_BATCHES_PER_RUN):
                pending_captures = self.memory_repo.get_pending_captures(company.id, limit=limit)
                if not pending_captures:
                    break
                for capture in pending_captures:
                    processed_count += 1
                    if self._compile_capture_safely(company, capture):
                        compiled_count += 1

        return {
            "status": "success",
            "compiled_count": compiled_count,
            "processed_count": processed_count,
            "pending_count": len(self.memory_repo.get_pending_captures(company.id, limit=limit)),
        }

    def compile_pending_for_user(self, company_short_name: str, user_identifier: str | None = None, limit: int = 12) -> dict:
        """Kept for callers of the per-user Memoria; compiles the whole company."""
        return self.compile_pending_for_company(company_short_name, limit=limit)

    @contextmanager
    def _company_lock(self, company_id: int):
        """
        Serializes compilation per company across workers and web processes.

        Uses a session-level Postgres advisory lock on a dedicated connection,
        so the many commits made while compiling cannot release it early. Other
        databases (SQLite in tests and local runs) have no concurrent compilers.
        """
        if self.db_manager.get_dialect() not in ("postgresql", "postgres"):
            yield
            return
        connection = self.db_manager.get_connection()
        try:
            connection.execute(
                text("SELECT pg_advisory_lock(:namespace, :company_id)"),
                {"namespace": self.ADVISORY_LOCK_NAMESPACE, "company_id": int(company_id)},
            )
            try:
                yield
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :company_id)"),
                    {"namespace": self.ADVISORY_LOCK_NAMESPACE, "company_id": int(company_id)},
                )
        finally:
            connection.close()

    def _compile_capture_safely(self, company: Company, capture: MemoryCapture) -> bool:
        items = self.memory_repo.list_capture_items(capture.id)
        if not items:
            self._mark_capture_compiled(capture, items)
            return False
        try:
            for item in items:
                self._enrich_item(company.short_name, item)
            return self._compile_single_capture(company, capture, items)
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
        if dict(capture.meta or {}).get("mode") == self.CORRECTION_MODE:
            return self._apply_correction(company, capture, items)
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

            target = self._resolve_target(compiled, candidates)
            title = str(compiled.get("title") or (target or {}).get("title") or self._default_page_title(capture, items)).strip()
            summary = str(compiled.get("summary") or "").strip()
            body = str(compiled.get("markdown") or "").strip() or f"# {title}\n"
            change_summary = str(compiled.get("change_summary") or "").strip() or None
            revision_metadata = {
                "source": self.COMPILER_SOURCE,
                "capture_id": capture.id,
                "author": capture.user_identifier,
            }

            if target is None:
                response = self.memory_wiki_service.create_page(
                    company.short_name,
                    title=title,
                    summary=summary,
                    body=body,
                    edited_by=capture.user_identifier,
                    change_summary=change_summary,
                    revision_metadata=revision_metadata,
                )
            else:
                response = self.memory_wiki_service.update_page(
                    company.short_name,
                    page=target,
                    title=title,
                    summary=summary,
                    body=body,
                    edited_by=capture.user_identifier,
                    change_summary=change_summary,
                    revision_metadata=revision_metadata,
                )

            if response.get("status") == "success":
                page = response.get("page") or {}
                page_id = page.get("id")
                self.memory_repo.add_page_sources(company.id, page_id, [item.id for item in items])
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
        model, _ = self.configuration_service.get_llm_configuration(company.short_name)
        if not model:
            return None
        request = "\n".join(str(item.content_text or "").strip() for item in items if str(item.content_text or "").strip())
        prompt = (
            "You maintain the company's memory wiki. A person asked for ONE change to one page.\n"
            "Apply only that change. Keep every other line of the page exactly as it is, word for word, "
            "including other people's attributions, headings and order. Do not rephrase, reorganize or summarize.\n"
            f"Attribute the line you change or add as ({author}, {captured_on}), replacing the attribution "
            "the old statement had on that line.\n"
            "If the request does not apply to this page or you cannot tell what to change, return action "
            "\"skip\" and explain why in change_summary, in the language of the request.\n"
            "Otherwise return action \"update\" with the COMPLETE new page body in `markdown` (without "
            "frontmatter, starting with `# Title`) and a one-sentence `change_summary` in the language of the page.\n\n"
            f"REQUEST (from {author}, {captured_on}):\n{request}\n\n"
            f"PAGE (id {page.get('id')}, title {json.dumps(page.get('title') or '', ensure_ascii=False)}):\n"
            f"{self.memory_wiki_service.page_body(page)}"
        )
        try:
            response = self.llm_client.invoke(
                company=company,
                user_identifier=capture.user_identifier,
                previous_response_id=None,
                question=f"Apply memory correction {capture.id}",
                context=prompt,
                tools=[],
                text={},
                model=model,
                images=[],
                attachments=[],
                response_contract={
                    "schema": self.PAGE_SCHEMA,
                    "schema_mode": "best_effort",
                    "response_mode": "structured_only",
                },
            )
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
        model, _ = self.configuration_service.get_llm_configuration(company.short_name)
        if not model:
            return None

        prompt = self._build_compiler_prompt(
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
            response = self.llm_client.invoke(
                company=company,
                user_identifier=capture.user_identifier,
                previous_response_id=None,
                question=f"Compile memory capture {capture.id}",
                context=prompt,
                tools=[],
                text={},
                model=model,
                images=[],
                attachments=native_pdf_attachments,
                response_contract={
                    "schema": self.PAGE_SCHEMA,
                    "schema_mode": "best_effort",
                    "response_mode": "structured_only",
                },
            )
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

    def _build_compiler_prompt(self,
                               capture: MemoryCapture,
                               items: list[MemoryItem],
                               candidates: list[dict],
                               *,
                               author: str,
                               captured_on: str,
                               wiki_schema: str = "",
                               index_entries: list[dict] | None = None) -> str:
        capture_payload = {
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
        }
        index_payload = [
            {"page_id": entry.get("id"), "title": entry.get("title"), "summary": entry.get("summary")}
            for entry in (index_entries or [])[:self.MAX_INDEX_ENTRIES_IN_PROMPT]
        ]
        candidate_payload = [
            {
                "page_id": page.get("id"),
                "title": page.get("title"),
                "markdown": self.memory_wiki_service.page_body(page),
            }
            for page in candidates or []
        ]
        return (
            "You maintain the company's memory wiki: how things are actually done in this company.\n"
            "Follow the wiki schema. Decide whether the new capture updates one candidate page, "
            "creates a new page, or should be skipped (nothing durable to keep).\n"
            "When you update a page, return its COMPLETE new markdown: keep everything already on it, "
            "including other people's attributions, and change only what the capture changes.\n"
            f"Attribute every fact you add as ({author}, {captured_on}).\n"
            "Return JSON only, following the provided schema. `markdown` is the page body without "
            "frontmatter, starting with `# Title`. `change_summary` is one short sentence for the page history.\n\n"
            f"WIKI_SCHEMA:\n{wiki_schema[:7000]}\n\n"
            f"PAGE_INDEX:\n{json.dumps(index_payload, ensure_ascii=False)}\n\n"
            f"NEW_CAPTURE:\n{json.dumps(capture_payload, ensure_ascii=False)}\n\n"
            f"CANDIDATE_PAGES:\n{json.dumps(candidate_payload, ensure_ascii=False)}\n\n"
            "If you update a page, set target_page_id to its page_id. "
            "If you create a page, set target_page_id to null."
        )

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
            response = requests.get(item.source_url, timeout=8, headers={"User-Agent": "IAToolkit Memory/1.0"})
            response.raise_for_status()
            html = response.text
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
