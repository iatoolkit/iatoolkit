# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from injector import inject
import yaml

from iatoolkit.services.markdown_wiki_service import MarkdownWikiService
from iatoolkit.services.storage_service import StorageService


class MemoryWikiService(MarkdownWikiService):
    SCHEMA_FILENAME = "wiki_schema.md"
    INDEX_FILENAME = "index.md"
    LOG_FILENAME = "log.md"
    SCHEMA_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "memory" / "wiki_schema.md"

    @inject
    def __init__(self, storage_service: StorageService):
        super().__init__(storage_service=storage_service)

    @staticmethod
    def slugify(value: str) -> str:
        candidate = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        return candidate[:80] or "memory-page"

    @staticmethod
    def sanitize_user_identifier(user_identifier: str) -> str:
        candidate = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(user_identifier or "").strip())
        return candidate[:120] or "user"

    def build_page_storage_key(self, company_short_name: str, user_identifier: str, slug: str) -> str:
        safe_user = self.sanitize_user_identifier(user_identifier)
        safe_slug = self.slugify(slug)
        return f"companies/{company_short_name}/users/{safe_user}/memory/wiki/{safe_slug}.md"

    def build_special_storage_key(self, company_short_name: str, user_identifier: str, filename: str) -> str:
        safe_user = self.sanitize_user_identifier(user_identifier)
        safe_name = str(filename or "").strip() or "memory.md"
        return f"companies/{company_short_name}/users/{safe_user}/memory/wiki/{safe_name}"

    def ensure_wiki_bootstrap(self, company_short_name: str, user_identifier: str) -> None:
        self.ensure_schema(company_short_name, user_identifier)
        index_key = self.build_special_storage_key(company_short_name, user_identifier, self.INDEX_FILENAME)
        if self.read_optional_markdown(company_short_name, index_key) is None:
            self.write_index(company_short_name, user_identifier, [])
        log_key = self.build_special_storage_key(company_short_name, user_identifier, self.LOG_FILENAME)
        if self.read_optional_markdown(company_short_name, log_key) is None:
            self.write_markdown(company_short_name, log_key, self.render_log([]))

    def ensure_schema(self, company_short_name: str, user_identifier: str) -> str:
        storage_key = self.build_special_storage_key(company_short_name, user_identifier, self.SCHEMA_FILENAME)
        existing = self.read_optional_markdown(company_short_name, storage_key)
        if existing is not None:
            return existing
        template = self.SCHEMA_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.write_markdown(company_short_name, storage_key, template)
        return template

    def read_schema(self, company_short_name: str, user_identifier: str) -> str:
        self.ensure_schema(company_short_name, user_identifier)
        storage_key = self.build_special_storage_key(company_short_name, user_identifier, self.SCHEMA_FILENAME)
        return self.read_optional_markdown(company_short_name, storage_key) or ""

    def write_index(self, company_short_name: str, user_identifier: str, entries: list[dict]) -> str:
        storage_key = self.build_special_storage_key(company_short_name, user_identifier, self.INDEX_FILENAME)
        markdown = self.render_index(entries)
        self.write_markdown(company_short_name, storage_key, markdown)
        return storage_key

    def read_index(self, company_short_name: str, user_identifier: str) -> dict:
        storage_key = self.build_special_storage_key(company_short_name, user_identifier, self.INDEX_FILENAME)
        markdown = self.read_optional_markdown(company_short_name, storage_key)
        if markdown is None:
            return {"entries": [], "generated_at": None, "wiki_path": storage_key}
        parsed = self.parse_index(markdown)
        parsed["wiki_path"] = storage_key
        return parsed

    def append_log_entry(self,
                         company_short_name: str,
                         user_identifier: str,
                         entry_type: str,
                         title: str,
                         details: list[str] | None = None,
                         metadata: dict | None = None) -> str:
        storage_key = self.build_special_storage_key(company_short_name, user_identifier, self.LOG_FILENAME)
        markdown = self.read_optional_markdown(company_short_name, storage_key)
        parsed = self.parse_log(markdown or "")
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_type": str(entry_type or "event").strip().lower() or "event",
            "title": str(title or "").strip()[:200] or "Memory event",
            "details": [str(detail).strip() for detail in (details or []) if str(detail or "").strip()],
            "metadata": {str(key): str(value) for key, value in (metadata or {}).items() if str(value or "").strip()},
        }
        parsed.append(entry)
        self.write_markdown(company_short_name, storage_key, self.render_log(parsed))
        return storage_key

    def read_log(self, company_short_name: str, user_identifier: str) -> list[dict]:
        storage_key = self.build_special_storage_key(company_short_name, user_identifier, self.LOG_FILENAME)
        markdown = self.read_optional_markdown(company_short_name, storage_key)
        return self.parse_log(markdown or "")

    def rebuild_index(self, company_short_name: str, user_identifier: str, pages: list, page_reader=None) -> str:
        entries = []
        for page in pages or []:
            payload = {}
            if page_reader:
                payload = page_reader(page) or {}
            entry = {
                "page_id": getattr(page, "id", None),
                "title": payload.get("title") or getattr(page, "title", "") or "Untitled memory",
                "summary": payload.get("summary") or getattr(page, "summary", "") or "",
                "slug": payload.get("slug") or getattr(page, "slug", "") or "",
                "wiki_path": getattr(page, "wiki_path", "") or payload.get("wiki_path") or "",
                "source_count": len(payload.get("source_item_ids") or []),
                "last_updated_at": getattr(page, "updated_at", None).isoformat() if getattr(page, "updated_at", None) else None,
            }
            entries.append(entry)
        return self.write_index(company_short_name, user_identifier, entries)

    def write_page(self, company_short_name: str, payload: dict) -> str:
        storage_key = payload.get("wiki_path") or self.build_page_storage_key(
            company_short_name,
            payload.get("user_identifier"),
            payload.get("slug") or payload.get("title"),
        )
        markdown = self.render_page(payload)
        return self.write_markdown(company_short_name, storage_key, markdown)

    def read_page(self, company_short_name: str, storage_key: str) -> dict:
        markdown = self.read_markdown(company_short_name, storage_key)
        parsed = self.parse_page(markdown)
        parsed["wiki_path"] = storage_key
        return parsed

    def delete_page(self, company_short_name: str, storage_key: str | None) -> None:
        self.delete_markdown(company_short_name, storage_key)

    def render_page(self, payload: dict) -> str:
        frontmatter = {
            "page_id": payload.get("page_id"),
            "title": payload.get("title"),
            "slug": payload.get("slug"),
            "summary": payload.get("summary") or "",
            "source_item_ids": payload.get("source_item_ids") or [],
            "related_pages": payload.get("related_pages") or [],
        }

        sections = [
            ("Summary", payload.get("summary") or ""),
            ("Key Points", self._render_list(payload.get("key_points"))),
            ("Decisions", self._render_list(payload.get("decisions"))),
            ("Open Questions", self._render_list(payload.get("open_questions"))),
            ("Next Steps", self._render_list(payload.get("next_steps"))),
            ("Sources", self._render_sources(payload.get("sources"))),
            ("Related", self._render_list(payload.get("related_pages"))),
        ]

        body_lines = ["---", yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(), "---", ""]
        for title, content in sections:
            body_lines.append(f"## {title}")
            body_lines.append(content.strip() if isinstance(content, str) else "")
            body_lines.append("")
        return "\n".join(body_lines).strip() + "\n"

    def parse_page(self, markdown: str) -> dict:
        parsed = self.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        body = parsed.get("body") or ""

        sections = self._parse_sections(body)
        derived_title = frontmatter.get("title")
        if not derived_title:
            summary_text = sections.get("Summary", "").strip()
            derived_title = summary_text.splitlines()[0][:120] if summary_text else "Memory Page"
        return {
            "page_id": frontmatter.get("page_id"),
            "title": derived_title,
            "slug": frontmatter.get("slug"),
            "summary": frontmatter.get("summary") or sections.get("Summary", "").strip(),
            "key_points": self._parse_list(sections.get("Key Points")),
            "decisions": self._parse_list(sections.get("Decisions")),
            "open_questions": self._parse_list(sections.get("Open Questions")),
            "next_steps": self._parse_list(sections.get("Next Steps")),
            "sources": self._parse_list(sections.get("Sources")),
            "related_pages": frontmatter.get("related_pages") or self._parse_list(sections.get("Related")),
            "source_item_ids": frontmatter.get("source_item_ids") or [],
        }

    def render_index(self, entries: list[dict]) -> str:
        normalized_entries = []
        for entry in entries or []:
            page_id = entry.get("page_id")
            if not isinstance(page_id, int):
                continue
            normalized_entries.append({
                "page_id": page_id,
                "title": str(entry.get("title") or "Untitled memory").strip(),
                "summary": str(entry.get("summary") or "").strip(),
                "slug": str(entry.get("slug") or "").strip(),
                "wiki_path": str(entry.get("wiki_path") or "").strip(),
                "source_count": int(entry.get("source_count") or 0),
                "last_updated_at": entry.get("last_updated_at"),
            })

        frontmatter = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entry_count": len(normalized_entries),
            "entries": normalized_entries,
        }
        lines = ["---", yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(), "---", "", "# Memory Index", ""]
        if not normalized_entries:
            lines.append("No memory pages yet.")
        else:
            for entry in normalized_entries:
                target = entry.get("wiki_path") or f"{entry.get('slug')}.md"
                summary = entry.get("summary") or "No summary yet."
                source_count = entry.get("source_count") or 0
                lines.append(f"- [{entry['title']}]({target}) — {summary} ({source_count} sources)")
        return "\n".join(lines).strip() + "\n"

    def parse_index(self, markdown: str) -> dict:
        parsed = self.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        if not frontmatter:
            return {"generated_at": None, "entries": []}
        entries = frontmatter.get("entries") or []
        normalized = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            page_id = entry.get("page_id")
            if not isinstance(page_id, int):
                continue
            normalized.append({
                "page_id": page_id,
                "title": str(entry.get("title") or "").strip(),
                "summary": str(entry.get("summary") or "").strip(),
                "slug": str(entry.get("slug") or "").strip(),
                "wiki_path": str(entry.get("wiki_path") or "").strip(),
                "source_count": int(entry.get("source_count") or 0),
                "last_updated_at": entry.get("last_updated_at"),
            })
        return {
            "generated_at": frontmatter.get("generated_at"),
            "entries": normalized,
        }

    def render_log(self, entries: list[dict]) -> str:
        lines = ["# Memory Log", ""]
        if not entries:
            lines.append("No activity yet.")
            return "\n".join(lines).strip() + "\n"

        for entry in entries:
            timestamp = str(entry.get("timestamp") or "").strip()
            title = str(entry.get("title") or "Memory event").strip()
            entry_type = str(entry.get("entry_type") or "event").strip().lower()
            date_label = timestamp[:10] if len(timestamp) >= 10 else "unknown-date"
            lines.append(f"## [{date_label}] {entry_type} | {title}")
            if timestamp:
                lines.append(f"- Timestamp: {timestamp}")
            for detail in entry.get("details") or []:
                lines.append(f"- {detail}")
            metadata = entry.get("metadata") or {}
            for key, value in metadata.items():
                lines.append(f"- {key}: {value}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def parse_log(self, markdown: str) -> list[dict]:
        entries = []
        current = None
        for line in str(markdown or "").splitlines():
            if line.startswith("## ["):
                if current:
                    entries.append(current)
                header = line[3:].strip()
                current = {
                    "timestamp": "",
                    "entry_type": "event",
                    "title": header,
                    "details": [],
                    "metadata": {},
                }
                match = re.match(r"\[(?P<date>[^\]]+)\]\s+(?P<entry_type>[^|]+)\|\s*(?P<title>.+)$", header)
                if match:
                    current["entry_type"] = match.group("entry_type").strip().lower()
                    current["title"] = match.group("title").strip()
            elif current and line.startswith("- Timestamp: "):
                current["timestamp"] = line.replace("- Timestamp: ", "", 1).strip()
            elif current and line.startswith("- "):
                payload = line[2:].strip()
                if ": " in payload:
                    key, value = payload.split(": ", 1)
                    if key and value and key.lower() not in {"timestamp"}:
                        current["metadata"][key] = value
                    else:
                        current["details"].append(payload)
                elif payload:
                    current["details"].append(payload)
        if current:
            entries.append(current)
        return entries

    @staticmethod
    def _render_list(items) -> str:
        return MarkdownWikiService.render_markdown_list(items, empty_label="No entries yet.")

    @staticmethod
    def _render_sources(items) -> str:
        return MarkdownWikiService.render_markdown_list(items, empty_label="No sources yet.")

    @staticmethod
    def _parse_sections(body: str) -> dict[str, str]:
        return MarkdownWikiService.parse_sections(body)

    @staticmethod
    def _parse_list(content: str | None) -> list[str]:
        return MarkdownWikiService.parse_markdown_list(content)
