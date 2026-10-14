# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta

from injector import inject
from sqlalchemy import text

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.memory_question_repo import MemoryQuestionRepo
from iatoolkit.repositories.models import Company, MemoryQuestion, MemoryQuestionCandidate
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.memory_service import MemoryService


class MemoryQuestionService:
    """
    Memoria's unanswered questions (BL-005, Fase 1): what people ask about the
    company that the AI could not answer, so someone who knows can answer it.

    A periodic scan, not the chat turn, finds them: it reads the company's new
    turns that searched Memoria or the documents (`iat_queries.function_calls`
    keeps each tool's name and arguments, not its results), plus the Memoria
    searches from MCP that found nothing, and asks the company's model, in
    batches, whether each one was answered with the company's information. The
    same call writes the question neutrally, gives it a topic and says whether
    it is one of the questions already open, which then only counts once more.

    Who asked is never stored. Answering saves a normal Memoria capture,
    attributed to whoever answered.
    """

    SCAN_IDENTITY = "service:memory-questions"
    SEARCH_TOOLS = frozenset({"iat_memory_search", "iat_document_search"})
    BATCH_SIZE = 20
    MAX_QUERIES_PER_SCAN = 1000
    MAX_OPEN_IN_PROMPT = 80
    MAX_QUESTION_CHARS = 1000
    MAX_ANSWER_CHARS = 1500
    MAX_CANDIDATE_CHARS = 500
    # A company's first review (or one whose cursor never advanced) starts with
    # the last days, not with the whole history.
    FIRST_SCAN_DAYS = 7
    REF_KEYS = ("ref", "id", "turn", "turn_ref", "turn_id")
    TRUE_WORDS = {"true", "yes", "si", "sí", "1"}
    FALSE_WORDS = {"false", "no", "0"}
    # First key of the two-key Postgres advisory lock; the second is the company id.
    ADVISORY_LOCK_NAMESPACE = 734002

    CLASSIFICATION_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "answered": {"type": "boolean"},
                        "question": {"type": "string"},
                        "topic": {"type": "string"},
                        # Nullable as a type list: core's validator rejects null under anyOf.
                        "same_as_question_id": {"type": ["integer", "null"]},
                        "same_as_ref": {"type": ["string", "null"]},
                    },
                    "required": ["ref", "answered"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 question_repo: MemoryQuestionRepo,
                 memory_service: MemoryService,
                 llm_client: llmClient,
                 configuration_service: ConfigurationService,
                 db_manager: DatabaseManager):
        self.profile_repo = profile_repo
        self.question_repo = question_repo
        self.memory_service = memory_service
        self.llm_client = llm_client
        self.configuration_service = configuration_service
        self.db_manager = db_manager

    # =====================================================================
    # Reading and resolving
    # =====================================================================

    def list_questions(self, company_short_name: str, status: str | None = MemoryQuestion.STATUS_OPEN,
                       limit: int = 200) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        questions = self.question_repo.list_questions(company.id, status=status, limit=limit)
        return {"status": "success", "questions": [self.serialize(question) for question in questions]}

    def answer(self, company_short_name: str, question_id: int, answer_text: str, answered_by: str) -> dict:
        """Saves the answer as a Memoria capture by `answered_by`; the compiler files it."""
        company, question, error = self._open_question(company_short_name, question_id)
        if error:
            return error
        answer_text = str(answer_text or "").strip()
        if not answer_text:
            return {"status": "error", "error_message": "write the answer"}
        content = f"Pregunta: {question.question}\nRespuesta: {answer_text}"
        saved = self.memory_service.save_capture(
            company_short_name=company_short_name,
            user_identifier=answered_by,
            capture_text=content,
            title=question.question[:200],
            new_items=[{
                "item_type": "note",
                "content_text": content,
                "source_meta": {"origin": "memory_question", "question_id": question.id},
            }],
            meta={"origin": "memory_question", "question_id": question.id},
        )
        if saved.get("status") != "success":
            return saved
        question.status = MemoryQuestion.STATUS_ANSWERED
        question.answer_text = answer_text
        question.answer_capture_id = (saved.get("capture") or {}).get("capture_id")
        question.resolved_by = answered_by
        question.resolved_at = datetime.now()
        self.question_repo.commit()
        return {"status": "success", "question": self.serialize(question)}

    def dismiss(self, company_short_name: str, question_id: int, dismissed_by: str) -> dict:
        """'No aplica': the question leaves the list without adding anything to Memoria."""
        _, question, error = self._open_question(company_short_name, question_id)
        if error:
            return error
        question.status = MemoryQuestion.STATUS_DISMISSED
        question.resolved_by = dismissed_by
        question.resolved_at = datetime.now()
        self.question_repo.commit()
        return {"status": "success", "question": self.serialize(question)}

    def _open_question(self, company_short_name: str, question_id: int):
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, None, {"status": "error", "error_message": "company not found"}
        question = self.question_repo.get_question(company.id, question_id)
        if question is None:
            return company, None, {"status": "error", "error_message": "question not found"}
        if question.status != MemoryQuestion.STATUS_OPEN:
            return company, None, {"status": "error", "error_code": "already_resolved",
                                   "error_message": "that question was already answered or dismissed"}
        return company, question, None

    # =====================================================================
    # Candidates from outside the chat
    # =====================================================================

    def record_search_miss(self, company_short_name: str, query: str, source: str = "mcp") -> None:
        """A Memoria search with no results from a channel that does not write `iat_queries`."""
        query = str(query or "").strip()
        if not query:
            return
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return
        try:
            self.question_repo.add(MemoryQuestionCandidate(
                company_id=company.id,
                query_text=query[:self.MAX_CANDIDATE_CHARS],
                source=source,
            ))
            self.question_repo.commit()
        except Exception:
            logging.exception("Memoria search miss could not be recorded for %s", company_short_name)

    def has_pending_work(self, company_short_name: str) -> bool:
        """Whether a scan would find anything new; lets the hourly dispatch skip quiet tenants."""
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return False
        cursor = self.question_repo.find_cursor(company.id)
        last_query_id = cursor.last_query_id if cursor is not None else 0
        return (self.question_repo.has_queries_after(company.id, last_query_id)
                or self.question_repo.has_pending_candidates(company.id))

    # =====================================================================
    # Scan
    # =====================================================================

    def scan_company(self, company_short_name: str) -> dict:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return {"status": "error", "error_message": "company not found"}
        with self._company_lock(company.id):
            return self._scan(company)

    def _scan(self, company: Company) -> dict:
        counts = {"turns": 0, "reviewed": 0, "answered": 0, "new_questions": 0, "repeated": 0, "batches": 0}
        cursor = self.question_repo.get_cursor(company.id)
        if not cursor.last_query_id:
            cursor.last_query_id = self.question_repo.last_query_id_before(
                company.id, datetime.now() - timedelta(days=self.FIRST_SCAN_DAYS))
            self.question_repo.commit()
        queries = self.question_repo.list_queries_after(company.id, cursor.last_query_id, self.MAX_QUERIES_PER_SCAN)
        candidates = self.question_repo.list_pending_candidates(company.id, self.MAX_QUERIES_PER_SCAN)
        counts["turns"] = len(queries)

        entries = [entry for entry in (self._entry_from_query(query) for query in queries) if entry]
        entries += [self._entry_from_candidate(candidate) for candidate in candidates]
        if not entries:
            self._advance(cursor, queries[-1].id if queries else None)
            return {"status": "success", "counts": counts}

        model, _ = self.configuration_service.get_llm_configuration(company.short_name)
        if not model:
            return {"status": "error", "error_message": "the company has no model configured", "counts": counts}

        open_questions = self.question_repo.list_questions(company.id, limit=self.MAX_OPEN_IN_PROMPT)
        last_done_query_id = cursor.last_query_id
        failed = False
        for start in range(0, len(entries), self.BATCH_SIZE):
            batch = entries[start:start + self.BATCH_SIZE]
            items = self._classify(company, model, batch, open_questions)
            if items is None:
                failed = True
                break
            counts["batches"] += 1
            self._apply(company, batch, items, open_questions, counts)
            for entry in batch:
                if entry["kind"] == "query":
                    last_done_query_id = max(last_done_query_id, entry["query_id"])
                else:
                    entry["candidate"].processed_at = datetime.now()
            self.question_repo.commit()

        if failed:
            # Everything before the failed batch is done; the rest is read again next time.
            self._advance(cursor, last_done_query_id)
            return {"status": "partial", "error_message": "the model could not classify a batch", "counts": counts}
        # Turns that did not search the company are reviewed too: the cursor passes them all.
        self._advance(cursor, max(last_done_query_id, queries[-1].id if queries else 0))
        return {"status": "success", "counts": counts}

    def _advance(self, cursor, last_query_id: int | None) -> None:
        if last_query_id is not None and last_query_id > (cursor.last_query_id or 0):
            cursor.last_query_id = last_query_id
        cursor.last_scan_at = datetime.now()
        self.question_repo.commit()

    def _entry_from_query(self, query) -> dict | None:
        if str(query.user_identifier or "").startswith("service:"):
            # Nobody asked: an agent or a background job ran it.
            return None
        if not self._searched_the_company(query.function_calls):
            return None
        question = str(query.query or "").strip()
        if not question:
            return None
        return {
            "kind": "query",
            "ref": f"q{query.id}",
            "query_id": query.id,
            "channel": "chat",
            "asked_at": query.created_at or datetime.now(),
            "question": question[:self.MAX_QUESTION_CHARS],
            "answer": str(query.output or "").strip()[:self.MAX_ANSWER_CHARS],
        }

    def _entry_from_candidate(self, candidate: MemoryQuestionCandidate) -> dict:
        return {
            "kind": "candidate",
            "ref": f"m{candidate.id}",
            "candidate": candidate,
            "channel": candidate.source or "mcp",
            "asked_at": candidate.created_at or datetime.now(),
            "question": str(candidate.query_text or "")[:self.MAX_QUESTION_CHARS],
            "answer": None,
        }

    @classmethod
    def _searched_the_company(cls, function_calls) -> bool:
        calls = function_calls if isinstance(function_calls, list) else []
        for call in calls:
            if isinstance(call, dict) and cls.SEARCH_TOOLS.intersection(call.keys()):
                return True
        return False

    def _classify(self, company: Company, model: str, batch: list[dict], open_questions: list[MemoryQuestion]) -> list[dict] | None:
        turns = [
            {
                "ref": entry["ref"],
                "question": entry["question"],
                "answer": entry["answer"] if entry["answer"] is not None
                else "(a search of the company memory that found nothing; there is no answer)",
            }
            for entry in batch
        ]
        existing = [
            {"id": question.id, "question": question.question, "topic": question.topic}
            for question in open_questions
        ]
        prompt = (
            "You review conversations of people with the company's AI assistant. In each turn below the "
            "assistant searched the company's memory or documents to answer a question about the company.\n"
            "For each turn decide `answered`: true when the answer gave a concrete answer based on the "
            "company's own information; false when the assistant said it did not find it, did not know, "
            "gave only generic advice, or asked the person to check with someone.\n"
            "For each turn with answered=false also return:\n"
            "- `question`: the question rewritten in one neutral sentence, in the language of the turn, "
            "without names of people, personal details or the conversation's wording, so anyone in the "
            "company could answer it;\n"
            "- `topic`: two or three words for the subject;\n"
            "- `same_as_question_id`: the id of the OPEN QUESTION that asks the same thing, or null;\n"
            "- `same_as_ref`: when it is the same as an earlier unanswered turn of this batch that is not an "
            "open question yet, that turn's ref; otherwise null.\n"
            "Return one item per turn, with its ref.\n\n"
            f"OPEN QUESTIONS:\n{json.dumps(existing, ensure_ascii=False)}\n\n"
            f"TURNS:\n{json.dumps(turns, ensure_ascii=False)}"
        )
        try:
            response = self.llm_client.invoke(
                company=company,
                user_identifier=self.SCAN_IDENTITY,
                previous_response_id=None,
                question="Scan memory questions",
                context=prompt,
                tools=[],
                text={},
                model=model,
                images=[],
                attachments=[],
                response_contract={
                    "schema": self.CLASSIFICATION_SCHEMA,
                    "schema_mode": "best_effort",
                    "response_mode": "structured_only",
                },
            )
        except Exception as exc:
            logging.warning("Memory question scan for %s could not reach the model: %s", company.short_name, exc)
            return None
        items = self._extract_items(response.get("structured_output"))
        if items is None:
            items = self._extract_items(response.get("parsed_output"))
        if items is None:
            # A top-level list never reaches parsed_output (it carries objects only).
            items = self._extract_items(self._json_from_text(response.get("answer")))
        if items is None:
            logging.warning(
                "Memory question scan for %s did not understand the model's answer: %s",
                company.short_name, str(response.get("answer") or "")[:500],
            )
            return None
        return [normalized for normalized in (self._normalize_item(item) for item in items) if normalized]

    @staticmethod
    def _extract_items(value) -> list | None:
        """The list of classified turns, whether it comes bare or under some key."""
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if not isinstance(value, dict):
            return None
        if isinstance(value.get("items"), list):
            return [item for item in value["items"] if isinstance(item, dict)]
        for nested in value.values():
            if isinstance(nested, list) and all(isinstance(item, dict) for item in nested):
                return list(nested)
        for key in ("answer", "additional_data", "result", "data"):
            if isinstance(value.get(key), (dict, list)):
                return MemoryQuestionService._extract_items(value[key])
        return None

    @staticmethod
    def _json_from_text(text) -> object | None:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[4:] if raw.lower().startswith("json") else raw
        try:
            return json.loads(raw.strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_item(cls, item: dict) -> dict | None:
        ref = next((item.get(key) for key in cls.REF_KEYS if item.get(key) not in (None, "")), None)
        if ref is None:
            return None
        answered = item.get("answered")
        if isinstance(answered, str):
            word = answered.strip().lower()
            answered = True if word in cls.TRUE_WORDS else False if word in cls.FALSE_WORDS else None
        if not isinstance(answered, bool):
            return None
        return {**item, "ref": str(ref), "answered": answered}

    def _apply(self, company: Company, batch: list[dict], items: list[dict], open_questions: list[MemoryQuestion],
               counts: dict) -> None:
        by_ref = {entry["ref"]: entry for entry in batch}
        open_by_id = {question.id: question for question in open_questions}
        created_by_ref: dict[str, MemoryQuestion] = {}
        for item in items:
            entry = by_ref.get(str(item.get("ref") or ""))
            if entry is None:
                continue
            counts["reviewed"] += 1
            if item.get("answered") is True:
                counts["answered"] += 1
                continue
            target = open_by_id.get(self._as_int(item.get("same_as_question_id")))
            if target is None:
                target = created_by_ref.get(str(item.get("same_as_ref") or ""))
            if target is not None:
                self._count_again(target, entry)
                created_by_ref[entry["ref"]] = target
                counts["repeated"] += 1
                continue
            text_value = str(item.get("question") or "").strip() or entry["question"]
            question = self.question_repo.add(MemoryQuestion(
                company_id=company.id,
                question=text_value[:self.MAX_QUESTION_CHARS],
                topic=str(item.get("topic") or "").strip()[:200] or None,
                times_asked=1,
                channels={entry["channel"]: 1},
                first_asked_at=entry["asked_at"],
                last_asked_at=entry["asked_at"],
                status=MemoryQuestion.STATUS_OPEN,
            ))
            created_by_ref[entry["ref"]] = question
            counts["new_questions"] += 1
        self.question_repo.commit()
        # The next batches group against these too.
        for question in created_by_ref.values():
            if question.id not in open_by_id:
                open_questions.append(question)
                open_by_id[question.id] = question

    @staticmethod
    def _count_again(question: MemoryQuestion, entry: dict) -> None:
        question.times_asked = int(question.times_asked or 0) + 1
        channels = dict(question.channels or {})
        channels[entry["channel"]] = int(channels.get(entry["channel"]) or 0) + 1
        question.channels = channels
        if entry["asked_at"] and (question.last_asked_at is None or entry["asked_at"] > question.last_asked_at):
            question.last_asked_at = entry["asked_at"]

    @staticmethod
    def _as_int(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @contextmanager
    def _company_lock(self, company_id: int):
        """One scan per company at a time, across workers (as the compiler does)."""
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

    # =====================================================================
    # Shape
    # =====================================================================

    @staticmethod
    def serialize(question: MemoryQuestion) -> dict:
        def iso(value):
            return value.isoformat() if value else None
        return {
            "id": question.id,
            "question": question.question,
            "topic": question.topic,
            "times_asked": question.times_asked,
            "channels": question.channels or {},
            "first_asked_at": iso(question.first_asked_at),
            "last_asked_at": iso(question.last_asked_at),
            "status": question.status,
            "answer_text": question.answer_text,
            "answer_capture_id": question.answer_capture_id,
            "resolved_by": question.resolved_by,
            "resolved_at": iso(question.resolved_at),
        }
