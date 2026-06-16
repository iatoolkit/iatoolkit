# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import yaml
from injector import inject

from iatoolkit.services.storage_service import StorageService


class MarkdownWikiService:
    """Storage-backed helpers for markdown wiki documents."""

    @inject
    def __init__(self, storage_service: StorageService):
        self.storage_service = storage_service

    @staticmethod
    def slugify(value: str) -> str:
        candidate = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        return candidate[:80] or "wiki-page"

    @staticmethod
    def sanitize_storage_segment(value: str, *, fallback: str = "wiki") -> str:
        candidate = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip())
        return candidate[:120] or fallback

    @staticmethod
    def join_storage_path(*parts: str) -> str:
        normalized = []
        for part in parts:
            text = str(part or "").strip().strip("/")
            if text:
                normalized.append(text)
        return "/".join(normalized)

    def build_page_storage_key(self, root_storage_key: str, slug: str) -> str:
        safe_slug = self.slugify(slug)
        return self.join_storage_path(root_storage_key, f"{safe_slug}.md")

    def build_special_storage_key(self, root_storage_key: str, filename: str) -> str:
        safe_name = str(filename or "").strip() or "wiki.md"
        return self.join_storage_path(root_storage_key, safe_name)

    def write_markdown(self, company_short_name: str, storage_key: str, markdown: str) -> str:
        self.storage_service.upload_bytes(
            company_short_name=company_short_name,
            storage_key=storage_key,
            file_content=str(markdown or "").encode("utf-8"),
            mime_type="text/markdown",
        )
        return storage_key

    def read_optional_markdown(self, company_short_name: str, storage_key: str) -> str | None:
        try:
            raw = self.storage_service.get_document_content(company_short_name, storage_key)
        except Exception:
            return None
        return raw.decode("utf-8", errors="replace")

    def read_markdown(self, company_short_name: str, storage_key: str) -> str:
        raw = self.storage_service.get_document_content(company_short_name, storage_key)
        return raw.decode("utf-8", errors="replace")

    def delete_markdown(self, company_short_name: str, storage_key: str | None) -> None:
        if not storage_key:
            return
        self.storage_service.delete_file(company_short_name, storage_key)

    @staticmethod
    def render_frontmatter_document(frontmatter: dict[str, Any] | None, body: str) -> str:
        metadata = dict(frontmatter or {})
        lines = [
            "---",
            yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip(),
            "---",
            "",
            str(body or "").strip(),
        ]
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def parse_frontmatter_document(markdown: str) -> dict[str, Any]:
        content = str(markdown or "")
        frontmatter = {}
        body = content

        if content.startswith("---\n") and "\n---\n" in content:
            yaml_end = content.find("\n---\n")
            yaml_text = content[4:yaml_end]
            body = content[yaml_end + len("\n---\n"):]
            try:
                frontmatter = yaml.safe_load(yaml_text) or {}
            except Exception:
                frontmatter = {}

        if not isinstance(frontmatter, dict):
            frontmatter = {}
        return {
            "frontmatter": frontmatter,
            "body": body.strip(),
        }

    def write_document(
        self,
        company_short_name: str,
        storage_key: str,
        *,
        frontmatter: dict[str, Any] | None = None,
        body: str = "",
    ) -> str:
        markdown = self.render_frontmatter_document(frontmatter or {}, body)
        return self.write_markdown(company_short_name, storage_key, markdown)

    def read_document(self, company_short_name: str, storage_key: str) -> dict[str, Any]:
        markdown = self.read_markdown(company_short_name, storage_key)
        parsed = self.parse_frontmatter_document(markdown)
        parsed["storage_key"] = storage_key
        return parsed

    @staticmethod
    def _normalize_index_entries(entries: list[dict]) -> list[dict]:
        return [dict(entry) for entry in (entries or []) if isinstance(entry, dict)]

    @staticmethod
    def _build_index_frontmatter(entries: list[dict], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_entries = MarkdownWikiService._normalize_index_entries(entries)
        frontmatter = dict(extra or {})
        frontmatter["generated_at"] = datetime.now(timezone.utc).isoformat()
        frontmatter["entry_count"] = len(normalized_entries)
        frontmatter["entries"] = normalized_entries
        return frontmatter

    @staticmethod
    def _render_index_entry_lines(entries: list[dict]) -> list[str]:
        normalized_entries = MarkdownWikiService._normalize_index_entries(entries)
        if not normalized_entries:
            return ["No pages yet."]

        lines: list[str] = []
        for entry in normalized_entries:
            label = str(entry.get("title") or entry.get("path") or entry.get("slug") or "Untitled page").strip()
            target = str(entry.get("path") or entry.get("wiki_path") or entry.get("slug") or "").strip()
            summary = str(entry.get("summary") or "No summary yet.").strip()
            if target:
                lines.append(f"- [{label}]({target}) - {summary}")
            else:
                lines.append(f"- {label} - {summary}")
        return lines

    @classmethod
    def render_generic_index(cls, entries: list[dict], *, title: str = "Wiki Index") -> str:
        normalized_entries = [dict(entry) for entry in (entries or []) if isinstance(entry, dict)]
        frontmatter = cls._build_index_frontmatter(normalized_entries)
        lines = ["---", yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(), "---", "", f"# {title}", ""]
        lines.extend(cls._render_index_entry_lines(normalized_entries))
        return "\n".join(lines).strip() + "\n"

    @classmethod
    def render_curated_index(
        cls,
        authored_markdown: str,
        entries: list[dict],
        *,
        title: str = "Wiki Index",
        listing_title: str = "Available pages",
    ) -> str:
        parsed = cls.parse_frontmatter_document(authored_markdown)
        authored_frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        authored_body = str(parsed.get("body") or "").strip()
        normalized_entries = cls._normalize_index_entries(entries)
        frontmatter = cls._build_index_frontmatter(
            normalized_entries,
            extra={
                **authored_frontmatter,
                "authored_index": True,
            },
        )

        sections: list[str] = []
        if authored_body:
            sections.append(authored_body)
        else:
            sections.append(f"# {title}")

        listing_lines = [f"## {listing_title}", ""]
        listing_lines.extend(cls._render_index_entry_lines(normalized_entries))
        sections.append("\n".join(listing_lines).strip())

        return cls.render_frontmatter_document(frontmatter, "\n\n".join(section for section in sections if section))

    @classmethod
    def parse_generic_index(cls, markdown: str) -> dict:
        parsed = cls.parse_frontmatter_document(markdown)
        frontmatter = parsed.get("frontmatter") if isinstance(parsed.get("frontmatter"), dict) else {}
        entries = frontmatter.get("entries") if isinstance(frontmatter.get("entries"), list) else []
        return {
            "generated_at": frontmatter.get("generated_at"),
            "entries": [dict(entry) for entry in entries if isinstance(entry, dict)],
        }

    @staticmethod
    def render_log(entries: list[dict]) -> str:
        lines = ["# Wiki Log", ""]
        if not entries:
            lines.append("No activity yet.")
            return "\n".join(lines).strip() + "\n"

        for entry in entries:
            timestamp = str(entry.get("timestamp") or "").strip()
            title = str(entry.get("title") or "Wiki event").strip()
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

    @staticmethod
    def parse_log(markdown: str) -> list[dict]:
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

    def append_log_entry(
        self,
        company_short_name: str,
        storage_key: str,
        entry_type: str,
        title: str,
        details: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        markdown = self.read_optional_markdown(company_short_name, storage_key)
        parsed = self.parse_log(markdown or "")
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_type": str(entry_type or "event").strip().lower() or "event",
            "title": str(title or "").strip()[:200] or "Wiki event",
            "details": [str(detail).strip() for detail in (details or []) if str(detail or "").strip()],
            "metadata": {str(key): str(value) for key, value in (metadata or {}).items() if str(value or "").strip()},
        }
        parsed.append(entry)
        self.write_markdown(company_short_name, storage_key, self.render_log(parsed))
        return storage_key

    @staticmethod
    def parse_sections(body: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        current_title = None
        buffer: list[str] = []

        for line in str(body or "").splitlines():
            if line.startswith("## "):
                if current_title is not None:
                    sections[current_title] = "\n".join(buffer).strip()
                current_title = line[3:].strip()
                buffer = []
            else:
                buffer.append(line)

        if current_title is not None:
            sections[current_title] = "\n".join(buffer).strip()

        return sections

    @staticmethod
    def parse_markdown_list(content: str | None) -> list[str]:
        normalized = []
        for line in str(content or "").splitlines():
            candidate = re.sub(r"^\s*-\s*", "", line).strip()
            if candidate and candidate.lower() not in {"no entries yet.", "no sources yet."} and candidate not in normalized:
                normalized.append(candidate)
        return normalized

    @staticmethod
    def render_markdown_list(items, *, empty_label: str = "No entries yet.") -> str:
        normalized = []
        for item in items or []:
            text = str(item or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        if not normalized:
            return empty_label
        return "\n".join(f"- {item}" for item in normalized)
