# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Compacts a long conversation history (BL-009, Fase E).

The older turns of a history close to the model's context window are replaced
by a summary written by the `history_compaction` system agent; the prepared
context and the most recent turns stay as they are. It runs in the background
(a deployment's HistoryCompactionTrigger queues it) or in line, on the turn that
would no longer fit.

The summary is computed from a snapshot and applied under the history lock, and
only if the compacted part is still exactly what was summarized: a turn that
arrived meanwhile is kept, and a history that was reset in between is never
overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from injector import inject

from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.history_manager_service import HistoryManagerService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.system_agent_runner import SystemAgentRunner, SystemAgentUnavailable
from iatoolkit.services.user_session_context_service import UserSessionContextService


@dataclass(frozen=True)
class CompactionPlan:
    #: Index of the first message kept as is; everything before it, after the
    #: prepared context, becomes the summary.
    cut: int
    previous_summary: str
    material: list
    #: Fingerprint of history[:cut] when the plan was made.
    prefix_hash: str


class HistoryCompactionService:
    AGENT_KEY = "history_compaction"
    #: Share of the budget the most recent turns may keep verbatim.
    KEEP_RECENT_SHARE = 0.30
    MIN_RECENT_TURNS = 2
    #: Tool outputs and long answers are cut in the transcript the agent reads:
    #: the summary keeps facts, and a 200-row result would crowd out the rest.
    MAX_MESSAGE_CHARS = 4000
    #: What one call to the agent reads. A longer stretch is summarized in
    #: parts, oldest first, each part extending the summary of the previous one.
    MAX_TRANSCRIPT_CHARS = 400_000
    #: Parts per compaction: in the background, enough for a history that grew
    #: without compaction (before BL-009) without summarizing forever; in line,
    #: one, because the person is waiting.
    MAX_CHUNKS = 6

    @inject
    def __init__(self,
                 session_context: UserSessionContextService,
                 history_manager: HistoryManagerService,
                 profile_repo: ProfileRepo,
                 system_agent_runner: SystemAgentRunner,
                 llm_client: llmClient):
        self.session_context = session_context
        self.history_manager = history_manager
        self.profile_repo = profile_repo
        self.system_agent_runner = system_agent_runner
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def compact(self, company_short_name: str, user_identifier: str, model: str,
                max_chunks: Optional[int] = None) -> dict:
        result = self._compact(company_short_name, user_identifier, model, max_chunks)
        if result.get("status") != "compacted":
            # A run that ends without applying anything is as worth knowing as
            # one that does: in production both looked the same ("executed").
            log = logging.warning if result.get("status") == "error" else logging.info
            log("History of %s/%s (model=%s) not compacted: %s",
                company_short_name, user_identifier, model, result)
        return result

    def _compact(self, company_short_name: str, user_identifier: str, model: str,
                 max_chunks: Optional[int]) -> dict:
        history = self.session_context.get_context_history(company_short_name, user_identifier, model=model) or []
        budget = self.history_manager.context_budget_tokens(company_short_name, model)
        plan = self.plan(history, budget)
        if plan is None:
            return {"status": "skipped", "reason": "nothing_to_compact"}

        if not SystemAgentRunner.is_enabled(self.AGENT_KEY):
            return {"status": "skipped", "reason": "the compaction agent is turned off"}
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "reason": "company_not_found"}

        chunks = self.chunk_material(plan.material)
        limit = max(int(max_chunks or self.MAX_CHUNKS), 1)
        dropped_chunks = max(len(chunks) - limit, 0)
        if dropped_chunks:
            # The oldest parts go unsummarized: a cost bound, logged so a short
            # summary of a very long conversation can be explained.
            logging.warning(
                "History of %s/%s (model=%s) needs %s parts to summarize; only the %s most recent are.",
                company_short_name, user_identifier, model, len(chunks), limit,
            )
            chunks = chunks[-limit:]

        summary = plan.previous_summary
        for chunk in chunks:
            try:
                response = self.system_agent_runner.run(
                    company,
                    self.AGENT_KEY,
                    {"previous_summary": summary, "transcript": self.render_transcript(chunk)},
                    user_identifier=user_identifier,
                )
            except SystemAgentUnavailable as e:
                return {"status": "skipped", "reason": str(e)}
            part = self._summary_from(response)
            if not part:
                return {"status": "error", "reason": "empty_summary"}
            summary = part

        result = self._apply(company_short_name, user_identifier, model, plan, summary)
        if result.get("status") == "compacted":
            result["chunks"] = len(chunks)
            if dropped_chunks:
                result["dropped_chunks"] = dropped_chunks
        return result

    @classmethod
    def chunk_material(cls, material: list) -> list[list]:
        """The material split into parts the agent can read in one call, at turn boundaries.

        A turn is never split, so a tool call stays with its result. A single
        turn longer than a part is a part of its own (render_transcript clips it).
        """
        turns: list[list] = []
        for message in material or []:
            if (isinstance(message, dict) and message.get("role") == "user") or not turns:
                turns.append([message])
            else:
                turns[-1].append(message)

        chunks: list[list] = []
        current: list = []
        current_chars = 0
        for turn in turns:
            turn_chars = len(cls.render_transcript(turn))
            if current and current_chars + turn_chars > cls.MAX_TRANSCRIPT_CHARS:
                chunks.append(current)
                current, current_chars = [], 0
            current.extend(turn)
            current_chars += turn_chars
        if current:
            chunks.append(current)
        return chunks

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def plan(self, history: list, budget_tokens: int) -> Optional[CompactionPlan]:
        """What to summarize, or None when there are not enough turns to gain anything."""
        if not history:
            return None
        prefix_len = 1
        previous_summary = ""
        if len(history) > 1 and HistoryManagerService.is_summary_message(history[1]):
            prefix_len = 2
            previous_summary = HistoryManagerService.summary_text(history[1])

        turn_starts = HistoryManagerService.turn_starts(history)
        if len(turn_starts) <= self.MIN_RECENT_TURNS:
            return None

        token_counts = [self._count(message) for message in history]
        keep_budget = budget_tokens * self.KEEP_RECENT_SHARE
        bounds = turn_starts + [len(history)]
        kept_tokens = 0
        kept_turns = 0
        cut = len(history)
        for index in range(len(turn_starts) - 1, -1, -1):
            start, end = bounds[index], bounds[index + 1]
            turn_tokens = sum(token_counts[start:end])
            if kept_turns >= self.MIN_RECENT_TURNS and kept_tokens + turn_tokens > keep_budget:
                break
            kept_tokens += turn_tokens
            kept_turns += 1
            cut = start

        if cut <= turn_starts[0]:
            return None  # every turn fits in the verbatim share: nothing to summarize

        return CompactionPlan(
            cut=cut,
            previous_summary=previous_summary,
            material=list(history[prefix_len:cut]),
            prefix_hash=self._fingerprint(history[:cut]),
        )

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------

    @classmethod
    def render_transcript(cls, messages: list) -> str:
        lines = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            if message.get("type") == "function_call_output":
                lines.append(f"TOOL RESULT: {cls._clip(cls._text(message.get('output')))}")
                continue
            if message.get("type") == "function_call":
                lines.append(
                    f"ASSISTANT called tool `{message.get('name')}` with: {cls._clip(str(message.get('arguments') or ''))}"
                )
                continue
            role = str(message.get("role") or "").strip().lower()
            speaker = "USER" if role == "user" else "ASSISTANT"
            content = cls._text(message.get("content"))
            if content:
                lines.append(f"{speaker}: {cls._clip(content)}")
            for tool_call in message.get("tool_calls") or []:
                function = (tool_call or {}).get("function") or {}
                name = function.get("name") or (tool_call or {}).get("name")
                arguments = function.get("arguments") or (tool_call or {}).get("arguments") or ""
                lines.append(f"ASSISTANT called tool `{name}` with: {cls._clip(str(arguments))}")

        transcript = "\n\n".join(lines)
        if len(transcript) > cls.MAX_TRANSCRIPT_CHARS:
            # The oldest part goes: the previous summary already covers it.
            transcript = "…\n\n" + transcript[-cls.MAX_TRANSCRIPT_CHARS:]
        return transcript

    @staticmethod
    def _text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
                elif isinstance(part, str):
                    parts.append(part)
                else:
                    parts.append("[non-text content]")
            return "\n".join(parts).strip()
        try:
            return json.dumps(content, ensure_ascii=False, default=str)
        except Exception:
            return str(content)

    @classmethod
    def _clip(cls, text: str) -> str:
        if len(text) <= cls.MAX_MESSAGE_CHARS:
            return text
        return text[:cls.MAX_MESSAGE_CHARS] + f"… [{len(text) - cls.MAX_MESSAGE_CHARS} characters cut]"

    # ------------------------------------------------------------------
    # Applying
    # ------------------------------------------------------------------

    def _apply(self, company_short_name: str, user_identifier: str, model: str,
               plan: CompactionPlan, summary: str) -> dict:
        lock_key = self.history_manager.history_lock_key(company_short_name, user_identifier, model)
        if not self.history_manager.acquire_history_lock(lock_key):
            return {"status": "skipped", "reason": "history_busy"}
        try:
            current = self.session_context.get_context_history(company_short_name, user_identifier, model=model) or []
            if len(current) < plan.cut or self._fingerprint(current[:plan.cut]) != plan.prefix_hash:
                # Reset, reloaded or already compacted by someone else since the
                # snapshot: the summary describes a history that is gone.
                return {"status": "skipped", "reason": "history_changed"}

            compacted = [current[0], HistoryManagerService.summary_message(summary)] + current[plan.cut:]
            self.session_context.save_context_history(company_short_name, user_identifier, compacted, model=model)
            # The provider's last measure described the long history; until the
            # next turn measures again, an estimate keeps the in-line check from
            # compacting a history that already fits.
            self.session_context.save_context_tokens(
                company_short_name, user_identifier, sum(self._count(m) for m in compacted), model=model
            )
        finally:
            self.history_manager.release_history_lock(lock_key)

        logging.info(
            "History of %s/%s (model=%s) compacted: %s messages summarized, %s kept.",
            company_short_name, user_identifier, model, len(plan.material), len(compacted) - 2,
        )
        return {
            "status": "compacted",
            "summarized_messages": len(plan.material),
            "kept_messages": len(compacted) - 2,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summary_from(response: Any) -> str:
        """The summary, however the model returned it.

        The agent asks for `{"summary": ...}`, but over a long transcript a model
        may answer the Markdown alone. That is still the summary; dropping it
        threw away minutes of work and left the history to grow.
        """
        if not isinstance(response, dict):
            return ""
        for key in ("structured_output", "parsed_output"):
            structured = response.get(key)
            if isinstance(structured, dict) and isinstance(structured.get("summary"), str):
                return structured["summary"].strip()
        answer = response.get("answer")
        if isinstance(answer, str) and answer.strip():
            text = answer.strip()
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                return text
            if isinstance(parsed, dict) and isinstance(parsed.get("summary"), str):
                return parsed["summary"].strip()
        return ""

    def _count(self, message: Any) -> int:
        try:
            return int(self.llm_client.count_tokens(json.dumps(message, ensure_ascii=False, default=str)))
        except Exception:
            return max(1, len(str(message)) // 4)

    @staticmethod
    def _fingerprint(messages: list) -> str:
        payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
