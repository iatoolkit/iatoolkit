# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import unescape

import requests
from injector import inject

from iatoolkit.repositories.memory_repo import MemoryRepo
from iatoolkit.repositories.models import Company, MemoryCapture, MemoryCaptureStatus, MemoryItem, MemoryItemStatus, MemoryItemType
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.memory_wiki_service import MemoryWikiService


class MemoryCompilerService:
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
            "key_points": {"type": "array", "items": {"type": "string"}},
            "decisions": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "next_steps": {"type": "array", "items": {"type": "string"}},
            "related_pages": {"type": "array", "items": {"type": "string"}},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "action",
            "target_page_id",
            "title",
            "summary",
            "key_points",
            "decisions",
            "open_questions",
            "next_steps",
            "related_pages",
            "sources",
        ],
        "additionalProperties": False,
    }

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 memory_repo: MemoryRepo,
                 memory_wiki_service: MemoryWikiService,
                 llm_client: llmClient,
                 configuration_service: ConfigurationService):
        self.profile_repo = profile_repo
        self.memory_repo = memory_repo
        self.memory_wiki_service = memory_wiki_service
        self.llm_client = llm_client
        self.configuration_service = configuration_service

    def compile_pending_for_user(self,
                                 company_short_name: str,
                                 user_identifier: str,
                                 limit: int = 12) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "compiled_count": 0, "error_message": "company not found"}
        self.memory_wiki_service.ensure_wiki_bootstrap(company_short_name, user_identifier)

        pending_captures = self.memory_repo.get_pending_captures(company.id, user_identifier, limit=limit)
        compiled_count = 0

        for capture in pending_captures:
            items = self.memory_repo.list_capture_items(capture.id)
            if not items:
                capture.status = MemoryCaptureStatus.COMPILED
                capture.compile_error = None
                capture.last_compiled_at = datetime.now()
                self.memory_repo.save_capture(capture)
                continue
            try:
                for item in items:
                    self._enrich_item(company_short_name, item)
                compiled = self._compile_single_capture(company, capture, items)
                if compiled:
                    compiled_count += 1
            except Exception as exc:
                logging.exception("Memory compilation failed for capture %s: %s", capture.id, exc)
                capture.status = MemoryCaptureStatus.FAILED
                capture.compile_error = str(exc)
                self.memory_repo.save_capture(capture)
                for item in items:
                    item.status = MemoryItemStatus.FAILED
                    item.compile_error = str(exc)
                    self.memory_repo.save_item(item)

        return {
            "status": "success",
            "compiled_count": compiled_count,
            "pending_count": max(0, len(pending_captures) - compiled_count),
        }

    def _compile_single_capture(self, company: Company, capture: MemoryCapture, items: list[MemoryItem]) -> bool:
        query = self._memory_capture_query(capture, items)
        meta = dict(capture.meta or {})
        preferred_page_id = meta.get("page_id")
        preferred_page = None
        if isinstance(preferred_page_id, int):
            preferred_page = self.memory_repo.get_page(company.id, capture.user_identifier, preferred_page_id)
        linked_pages = self.memory_repo.list_pages_for_items([item.id for item in items if getattr(item, "id", None)])
        search_candidates = self.memory_repo.search_pages(
            company_id=company.id,
            user_identifier=capture.user_identifier,
            query=query,
            limit=3,
        )
        candidates = self._merge_candidate_pages(
            [preferred_page] if preferred_page else [],
            linked_pages,
            search_candidates,
            limit=3,
        )
        compiled_payload = self._compile_with_llm(company, capture, items, candidates)
        if not compiled_payload:
            compiled_payload = self._compile_with_fallback(capture, items, candidates)

        if compiled_payload.get("action") == "skip":
            for item in items:
                item.status = MemoryItemStatus.COMPILED
                item.compile_error = None
                self.memory_repo.save_item(item)
            capture.status = MemoryCaptureStatus.COMPILED
            capture.compile_error = None
            capture.last_compiled_at = datetime.now()
            self.memory_repo.save_capture(capture)
            return False

        target_page_id = compiled_payload.get("target_page_id")
        if not isinstance(target_page_id, int):
            target_page_id = candidates[0].id if candidates else None

        title = str(compiled_payload.get("title") or self._default_page_title(capture, items)).strip()
        slug = self.memory_wiki_service.slugify(title)
        wiki_path = self.memory_wiki_service.build_page_storage_key(
            company.short_name,
            capture.user_identifier,
            slug,
        )

        page = self.memory_repo.create_or_update_page(
            company_id=company.id,
            user_identifier=capture.user_identifier,
            page_id=target_page_id,
            title=title,
            slug=slug,
            wiki_path=wiki_path,
            summary=compiled_payload.get("summary") or "",
        )

        existing_source_ids = []
        for link in self.memory_repo.list_page_sources(page.id):
            if link.memory_item_id not in existing_source_ids:
                existing_source_ids.append(link.memory_item_id)
        for item in items:
            if item.id not in existing_source_ids:
                existing_source_ids.append(item.id)

        page_payload = {
            "page_id": page.id,
            "user_identifier": capture.user_identifier,
            "title": title,
            "slug": slug,
            "summary": compiled_payload.get("summary") or "",
            "key_points": compiled_payload.get("key_points") or [],
            "decisions": compiled_payload.get("decisions") or [],
            "open_questions": compiled_payload.get("open_questions") or [],
            "next_steps": compiled_payload.get("next_steps") or [],
            "sources": self._canonical_sources(items, compiled_payload.get("sources") or []),
            "related_pages": compiled_payload.get("related_pages") or [],
            "source_item_ids": existing_source_ids,
            "wiki_path": wiki_path,
        }

        self.memory_wiki_service.write_page(company.short_name, page_payload)
        page.summary = page_payload["summary"]
        page.wiki_path = wiki_path
        self.memory_repo.commit()
        self.memory_repo.replace_page_sources(page.id, existing_source_ids)
        self._refresh_wiki_indexes(company.short_name, capture.user_identifier)

        for item in items:
            item.status = MemoryItemStatus.COMPILED
            item.compile_error = None
            self.memory_repo.save_item(item)
        capture.status = MemoryCaptureStatus.COMPILED
        capture.compile_error = None
        capture.last_compiled_at = datetime.now()
        capture.meta = {**meta, "page_id": page.id}
        self.memory_repo.save_capture(capture)
        self.memory_wiki_service.append_log_entry(
            company.short_name,
            capture.user_identifier,
            entry_type="ingest",
            title=title,
            details=[
                f"Capture {capture.id} compiled into memory page {page.id}.",
                f"Items processed: {len(items)}",
            ],
            metadata={
                "page_id": page.id,
                "capture_id": capture.id,
                "action": compiled_payload.get("action") or "update",
            },
        )
        return True

    @staticmethod
    def _merge_candidate_pages(*candidate_lists: list, limit: int = 3) -> list:
        ordered = []
        seen_ids = set()
        for candidate_list in candidate_lists:
            for candidate in (candidate_list or []):
                candidate_id = getattr(candidate, "id", None)
                if not candidate_id or candidate_id in seen_ids:
                    continue
                ordered.append(candidate)
                seen_ids.add(candidate_id)
                if len(ordered) >= limit:
                    return ordered
        return ordered

    def _compile_with_llm(self, company: Company, capture: MemoryCapture, items: list[MemoryItem], candidates: list) -> dict | None:
        model, _ = self.configuration_service.get_llm_configuration(company.short_name)
        if not model:
            return None
        wiki_schema = self.memory_wiki_service.read_schema(company.short_name, capture.user_identifier)
        if not isinstance(wiki_schema, str):
            wiki_schema = str(wiki_schema or "")
        wiki_index = self.memory_wiki_service.read_index(company.short_name, capture.user_identifier)
        if not isinstance(wiki_index, dict):
            wiki_index = {}

        candidate_payloads = []
        for page in candidates or []:
            try:
                page_data = self.memory_wiki_service.read_page(company.short_name, page.wiki_path)
            except Exception:
                page_data = {"summary": page.summary or "", "key_points": [], "decisions": []}
            candidate_payloads.append({
                "page_id": page.id,
                "title": page.title,
                "summary": page.summary or page_data.get("summary") or "",
                "key_points": page_data.get("key_points") or [],
                "decisions": page_data.get("decisions") or [],
            })

        prompt = self._build_compiler_prompt(capture, items, candidate_payloads, wiki_schema=wiki_schema, wiki_index=wiki_index)
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
                attachments=[],
                response_contract={
                    "schema": self.PAGE_SCHEMA,
                    "schema_mode": "best_effort",
                    "response_mode": "structured_only",
                },
            )
        except Exception as exc:
            logging.warning("Memory compiler LLM fallback activated for capture %s: %s", capture.id, exc)
            return None

        structured = response.get("structured_output")
        return structured if isinstance(structured, dict) else None

    def _compile_with_fallback(self, capture: MemoryCapture, items: list[MemoryItem], candidates: list) -> dict:
        target_page = candidates[0] if candidates else None
        return {
            "action": "update" if target_page else "create",
            "target_page_id": target_page.id if target_page else None,
            "title": target_page.title if target_page else self._default_page_title(capture, items),
            "summary": self._fallback_summary(items),
            "key_points": [self._primary_fact(items)],
            "decisions": [],
            "open_questions": [],
            "next_steps": [],
            "related_pages": [],
            "sources": self._default_sources(items),
        }

    def _build_compiler_prompt(self,
                               capture: MemoryCapture,
                               items: list[MemoryItem],
                               candidates: list[dict],
                               wiki_schema: str = "",
                               wiki_index: dict | None = None) -> str:
        capture_payload = {
            "capture_id": capture.id,
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
                    "source_meta": item.source_meta or {},
                }
                for item in items
            ],
        }
        index_entries = wiki_index.get("entries") if isinstance(wiki_index.get("entries"), list) else []
        return (
            "You maintain a personal memory wiki for a chat user.\n"
            "Follow the wiki schema and use the current index to avoid duplicates.\n"
            "Decide whether the new saved capture should create a new page, update one candidate page, or be skipped.\n"
            "Return JSON only, following the provided schema.\n"
            "Prefer concise, practical pages. Do not invent facts not grounded in the capture.\n\n"
            f"WIKI_SCHEMA:\n{wiki_schema[:7000]}\n\n"
            f"CURRENT_INDEX:\n{json.dumps(index_entries[:80], ensure_ascii=False)}\n\n"
            f"NEW_CAPTURE:\n{json.dumps(capture_payload, ensure_ascii=False)}\n\n"
            f"CANDIDATE_PAGES:\n{json.dumps(candidates or [], ensure_ascii=False)}\n\n"
            "If you update an existing page, keep the same target_page_id. "
            "If you create a page, set target_page_id to null."
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
                str(item.source_url or "").strip(),
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
        return f"Memory capture {capture.id}"

    def _fallback_summary(self, items: list[MemoryItem]) -> str:
        base = self._primary_fact(items)
        return base[:400]

    def _primary_fact(self, items: list[MemoryItem]) -> str:
        for item in items:
            if item.content_text:
                first_line = str(item.content_text).strip().splitlines()[0]
                return first_line[:240]
        for item in items:
            if item.source_url:
                return f"Saved link: {item.source_url}"
            if item.filename:
                return f"Saved file: {item.filename}"
        item = items[0]
        return f"Saved {item.item_type.value if hasattr(item.item_type, 'value') else item.item_type}"

    def _default_sources(self, items: list[MemoryItem]) -> list[str]:
        sources = []
        for item in items:
            if item.source_url and item.source_url not in sources:
                sources.append(item.source_url)
            if item.filename and item.filename not in sources:
                sources.append(item.filename)
            if item.title and item.title not in sources and item.title != item.filename and item.title != item.source_url:
                sources.append(item.title[:180])
        return sources[:5]

    def _canonical_sources(self, items: list[MemoryItem], llm_sources: list[str]) -> list[str]:
        sources = self._default_sources(items)
        for value in llm_sources or []:
            candidate = str(value or "").strip()
            if not candidate:
                continue
            if len(candidate) > 220 and not candidate.startswith("http"):
                continue
            if candidate not in sources:
                sources.append(candidate)
        return sources[:5]

    def _refresh_wiki_indexes(self, company_short_name: str, user_identifier: str) -> None:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return
        pages = self.memory_repo.list_pages(company.id, user_identifier, limit=500)
        self.memory_wiki_service.rebuild_index(
            company_short_name,
            user_identifier,
            pages,
            page_reader=lambda page: self._safe_read_page(company_short_name, page),
        )

    def _safe_read_page(self, company_short_name: str, page) -> dict:
        try:
            return self.memory_wiki_service.read_page(company_short_name, page.wiki_path)
        except Exception:
            return {"summary": getattr(page, "summary", "") or "", "source_item_ids": []}
