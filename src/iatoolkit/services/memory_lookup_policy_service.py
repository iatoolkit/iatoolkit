# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from injector import inject


@dataclass(frozen=True)
class MemoryLookupPolicyDecision:
    tool_choice_override: str | None = None
    should_suggest_memory_search: bool = False
    reason: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryLookupPolicyService:
    MEMORY_SEARCH_TOOL = "iat_memory_search"
    DOCUMENT_SEARCH_TOOL = "iat_document_search"
    FALLBACK_MEMORY_TERMS = {
        "memoria",
        "memory",
        "nota",
        "notas",
        "note",
        "notes",
        "contexto",
        "context",
    }
    FALLBACK_RECALL_TERMS = {
        "guarde",
        "guardado",
        "guardada",
        "saved",
        "save",
        "recuerdo",
        "remember",
        "recordar",
        "previo",
        "previous",
        "anterior",
        "hablamos",
        "talked",
    }

    @inject
    def __init__(self):
        pass

    def resolve(
        self,
        question: str | None,
        tools: list[dict],
        tool_router_metrics: dict | None = None,
    ) -> MemoryLookupPolicyDecision:
        if not self._contains_tool(tools, self.MEMORY_SEARCH_TOOL):
            return MemoryLookupPolicyDecision()

        router_decision = self._resolve_from_router_metrics(tool_router_metrics)
        if router_decision.tool_choice_override or router_decision.should_suggest_memory_search:
            return router_decision

        if self._has_fallback_memory_lookup_intent(question):
            return MemoryLookupPolicyDecision(
                tool_choice_override=self.MEMORY_SEARCH_TOOL,
                should_suggest_memory_search=True,
                reason="fallback_memory_keywords",
                confidence=0.45,
            )

        return MemoryLookupPolicyDecision()

    @staticmethod
    def _contains_tool(tools: list[dict], tool_name: str) -> bool:
        return any(isinstance(tool, dict) and tool.get("name") == tool_name for tool in (tools or []))

    def _resolve_from_router_metrics(self, tool_router_metrics: dict | None) -> MemoryLookupPolicyDecision:
        metrics = tool_router_metrics if isinstance(tool_router_metrics, dict) else {}
        hook_metadata = metrics.get("hook_metadata") if isinstance(metrics.get("hook_metadata"), dict) else {}
        ranked_preview = self._normalize_ranked_preview(
            hook_metadata.get("ranked_tools_preview") or metrics.get("ranked_tools_preview")
        )
        selected_names = self._normalize_names(
            hook_metadata.get("selected_tool_names") or metrics.get("selected_tool_names")
        )
        top_k = self._to_int(hook_metadata.get("top_k") or metrics.get("top_k"))
        selection_mode = str(metrics.get("selection_mode") or "").strip().lower()

        memory_rank = self._get_rank(ranked_preview, self.MEMORY_SEARCH_TOOL)
        document_rank = self._get_rank(ranked_preview, self.DOCUMENT_SEARCH_TOOL)
        document_competes = (
            self.DOCUMENT_SEARCH_TOOL in selected_names or
            (document_rank is not None and top_k is not None and document_rank <= top_k)
        )
        if memory_rank is not None and top_k is not None and memory_rank <= top_k:
            if document_competes:
                return MemoryLookupPolicyDecision(
                    reason="router_ranked_memory_but_document_competes",
                    confidence=self._get_score(ranked_preview, self.MEMORY_SEARCH_TOOL),
                    metadata={
                        "memory_tool_rank": memory_rank,
                        "document_tool_rank": document_rank,
                        "top_k": top_k,
                    },
                )
            return MemoryLookupPolicyDecision(
                should_suggest_memory_search=True,
                reason="router_ranked_memory_tool",
                confidence=self._get_score(ranked_preview, self.MEMORY_SEARCH_TOOL),
                metadata={"memory_tool_rank": memory_rank, "top_k": top_k},
            )

        if selection_mode == "router_selected" and self.MEMORY_SEARCH_TOOL in selected_names:
            if document_competes:
                return MemoryLookupPolicyDecision(
                    reason="router_selected_memory_but_document_competes",
                    metadata={"memory_tool_rank": memory_rank, "document_tool_rank": document_rank},
                )
            return MemoryLookupPolicyDecision(
                should_suggest_memory_search=True,
                reason="router_selected_memory_tool",
                metadata={"memory_tool_rank": memory_rank},
            )

        return MemoryLookupPolicyDecision()

    def _has_fallback_memory_lookup_intent(self, question: str | None) -> bool:
        tokens = set(self._tokenize(question))
        if not tokens:
            return False
        if "memoria" in tokens or "memory" in tokens:
            return True
        return bool(tokens & self.FALLBACK_MEMORY_TERMS) and bool(tokens & self.FALLBACK_RECALL_TERMS)

    @staticmethod
    def _normalize_names(names: object) -> set[str]:
        if not isinstance(names, list):
            return set()
        return {
            str(name).strip()
            for name in names
            if isinstance(name, str) and str(name).strip()
        }

    @staticmethod
    def _normalize_ranked_preview(preview: object) -> list[dict]:
        if not isinstance(preview, list):
            return []
        return [item for item in preview if isinstance(item, dict) and item.get("name")]

    @staticmethod
    def _get_rank(preview: list[dict], tool_name: str) -> int | None:
        for index, item in enumerate(preview, start=1):
            if item.get("name") == tool_name:
                return index
        return None

    @staticmethod
    def _get_score(preview: list[dict], tool_name: str) -> float | None:
        for item in preview:
            if item.get("name") != tool_name:
                continue
            try:
                score = item.get("score")
                return float(score) if score is not None else None
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _to_int(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _tokenize(value: str | None) -> list[str]:
        normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.findall(r"[a-z0-9_]+", normalized)
