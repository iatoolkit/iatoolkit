# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import re
import unicodedata

from injector import inject

from iatoolkit.repositories.memory_repo import MemoryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.memory_compiler_service import MemoryCompilerService
from iatoolkit.services.memory_wiki_service import MemoryWikiService


class MemoryLintService:
    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 memory_repo: MemoryRepo,
                 memory_wiki_service: MemoryWikiService,
                 memory_compiler_service: MemoryCompilerService):
        self.profile_repo = profile_repo
        self.memory_repo = memory_repo
        self.memory_wiki_service = memory_wiki_service
        self.memory_compiler_service = memory_compiler_service

    def run_memory_lint(self, company_short_name: str, user_identifier: str) -> dict:
        self.memory_compiler_service.compile_pending_for_user(company_short_name, user_identifier)
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        self.memory_wiki_service.ensure_wiki_bootstrap(company_short_name, user_identifier)

        pages = self.memory_repo.list_pages(company.id, user_identifier, limit=500)
        page_payloads = []
        for page in pages:
            payload = self._safe_read_page(company_short_name, page.wiki_path)
            payload.update({
                "page_id": page.id,
                "title": payload.get("title") or page.title,
                "slug": payload.get("slug") or page.slug,
                "summary": payload.get("summary") or page.summary or "",
                "wiki_path": page.wiki_path,
            })
            page_payloads.append((page, payload))

        incoming_refs = {}
        normalized_title_map = {}
        for _, payload in page_payloads:
            slug = str(payload.get("slug") or "")
            title = str(payload.get("title") or "")
            normalized_title = self._normalize_text(title)
            if normalized_title:
                normalized_title_map.setdefault(normalized_title, []).append(payload)
            for related in payload.get("related_pages") or []:
                related_slug = self.memory_wiki_service.slugify(related)
                incoming_refs[related_slug] = incoming_refs.get(related_slug, 0) + 1
                normalized_related = self._normalize_text(related)
                incoming_refs[normalized_related] = incoming_refs.get(normalized_related, 0) + 1
            if slug:
                incoming_refs.setdefault(slug, incoming_refs.get(slug, 0))
            if normalized_title:
                incoming_refs.setdefault(normalized_title, incoming_refs.get(normalized_title, 0))

        duplicate_candidates = []
        orphan_pages = []
        cleaned_pages = []
        for page, payload in page_payloads:
            linted_payload, changed = self._lint_page_payload(payload)
            if changed:
                self.memory_wiki_service.write_page(company_short_name, linted_payload)
                if page.summary != linted_payload.get("summary"):
                    page.summary = linted_payload.get("summary") or ""
                    self.memory_repo.commit()
                cleaned_pages.append({
                    "page_id": page.id,
                    "title": linted_payload.get("title") or page.title,
                })

            slug = str(linted_payload.get("slug") or "")
            normalized_title = self._normalize_text(linted_payload.get("title") or "")
            related_pages = linted_payload.get("related_pages") or []
            source_item_ids = linted_payload.get("source_item_ids") or []
            if not related_pages and not incoming_refs.get(slug) and not incoming_refs.get(normalized_title) and source_item_ids:
                orphan_pages.append({
                    "page_id": page.id,
                    "title": linted_payload.get("title") or page.title,
                })

        for normalized_title, candidates in normalized_title_map.items():
            if len(candidates) > 1:
                duplicate_candidates.append({
                    "title": candidates[0].get("title") or "Untitled memory",
                    "page_ids": [candidate.get("page_id") for candidate in candidates if candidate.get("page_id")],
                })

        self._rebuild_index(company_short_name, company.id, user_identifier)

        result = {
            "checked_pages": len(page_payloads),
            "cleaned_pages": cleaned_pages,
            "duplicate_candidates": duplicate_candidates[:10],
            "orphan_pages": orphan_pages[:10],
            "actions_applied": len(cleaned_pages),
        }

        self.memory_wiki_service.append_log_entry(
            company_short_name,
            user_identifier,
            entry_type="lint",
            title="Memory wiki health check",
            details=[
                f"Checked {result['checked_pages']} pages.",
                f"Applied {result['actions_applied']} conservative fixes.",
                f"Potential duplicates: {len(result['duplicate_candidates'])}.",
                f"Potential orphan pages: {len(result['orphan_pages'])}.",
            ],
            metadata={
                "checked_pages": result["checked_pages"],
                "actions_applied": result["actions_applied"],
                "duplicate_candidates": len(result["duplicate_candidates"]),
                "orphan_pages": len(result["orphan_pages"]),
            },
        )
        result["ran_at"] = self.get_last_lint_result(company_short_name, user_identifier).get("timestamp")
        return {"status": "success", "mode": "inline", "lint": result}

    def get_last_lint_result(self, company_short_name: str, user_identifier: str) -> dict:
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

    def _rebuild_index(self, company_short_name: str, company_id: int, user_identifier: str) -> None:
        pages = self.memory_repo.list_pages(company_id, user_identifier, limit=500)
        self.memory_wiki_service.rebuild_index(
            company_short_name,
            user_identifier,
            pages,
            page_reader=lambda page: self._safe_read_page(company_short_name, page.wiki_path),
        )

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()
