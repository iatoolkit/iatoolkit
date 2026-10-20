# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""What a tool call may reach, for the person it runs for (BL-010, Fase 2).

Every tool call goes through the dispatcher (chat, API, async tasks, MCP
projected tools). Before the tool runs, this scopes the call to the resources
the person may use:

- the tool itself (level 1 over "tool", by its name);
- the SQL source a query names (`database_key`);
- the RAG collections a document search names; with none named, the search is
  narrowed to the collections the person may see (it no longer reaches all);
- the document a read asks for, by its collection;
- the wikis a wiki tool names; a search over every wiki is narrowed likewise.

A resource the person may not use raises PERMISSION. A call with no person
(pipelines, packs: internal runs) is not scoped. Without groups (core alone, or
nothing restricted) every check passes and the call is unchanged.
"""

from __future__ import annotations

from injector import inject
from sqlalchemy import select

from iatoolkit.common import access
from iatoolkit.common.access import USE
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import CollectionType, Company, Document, KnowledgeWiki

SQL_TOOLS = frozenset({"iat_sql_query", "iat_sql_schema"})
#: Tools whose access follows another tool's (BL-017): whoever may query may read
#: the schema of what they query, and nobody else. Without this a new tool falls
#: to the type default and can end up wider or narrower than the one it serves.
TOOL_ACCESS_ALIASES = {"iat_sql_schema": "iat_sql_query"}


def tool_access_key(function_name: str) -> str:
    """The tool name whose access list decides this tool's access."""
    return TOOL_ACCESS_ALIASES.get(function_name, function_name)
COLLECTION_TOOLS = frozenset({"iat_document_search", "iat_document_list", "iat_image_search", "iat_visual_search"})
DOCUMENT_READ_TOOLS = frozenset({"iat_document_read"})
WIKI_TOOLS = frozenset({"iat_wiki_search", "iat_wiki_get_page"})
# Collection tools that accept a list of collections; the others take one.
MULTI_COLLECTION_TOOLS = frozenset({"iat_document_search"})


class ResourceAccessScope:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    @property
    def session(self):
        return self.db_manager.get_session()

    # ---------------------------------------------------------------- tool calls
    def scope_tool_call(self, company_short_name: str, function_name: str, user_identifier: str | None,
                        arguments: dict) -> dict:
        """The call's arguments, narrowed to what the person may reach; raises PERMISSION otherwise."""
        if not user_identifier:
            return arguments
        if not access.can(company_short_name, user_identifier, USE, "tool", tool_access_key(function_name)):
            raise _denied(f"No access to the tool '{function_name}'.")

        scoped = dict(arguments)
        if function_name in SQL_TOOLS:
            database = str(scoped.get("database_key") or "").strip()
            if database and not access.can(company_short_name, user_identifier, USE, "sql_source", database):
                raise _denied(f"No access to the SQL source '{database}'.")

        elif function_name in COLLECTION_TOOLS:
            named = _as_list(scoped.get("collection"))
            if named:
                denied = [c for c in named if not self._can_see_collection(company_short_name, user_identifier, c)]
                if denied:
                    raise _denied(f"No access to the collection '{denied[0]}'.")
            else:
                allowed = self.allowed_collections(company_short_name, user_identifier)
                if allowed is not None:
                    # Everything the person may see, never the whole corpus.
                    if not allowed:
                        raise _denied("No access to any document collection.")
                    if function_name in MULTI_COLLECTION_TOOLS:
                        scoped["collection"] = allowed
                    elif len(allowed) == 1:
                        scoped["collection"] = allowed[0]
                    else:
                        # These tools take one collection: someone who sees only some names one.
                        raise _denied("Name the collection: you can see only some of them.")

        elif function_name in DOCUMENT_READ_TOOLS:
            collection = self._document_collection(company_short_name, scoped.get("document_id"))
            if collection and not self._can_see_collection(company_short_name, user_identifier, collection):
                raise _denied("No access to that document.")

        elif function_name in WIKI_TOOLS:
            wiki_key = str(scoped.get("wiki_key") or "").strip()
            if wiki_key:
                if not access.can(company_short_name, user_identifier, USE, "knowledge_wiki", wiki_key):
                    raise _denied(f"No access to the wiki '{wiki_key}'.")
            else:
                allowed = self.allowed_wiki_keys(company_short_name, user_identifier)
                if allowed is not None:
                    requested = _as_list(scoped.get("allowed_wiki_keys"))
                    scoped["allowed_wiki_keys"] = [k for k in allowed if not requested or k in requested]
        return scoped

    # ---------------------------------------------------------------- the RAG API
    def scope_collection(self, company_short_name: str, user_identifier: str | None, collection,
                         *, multi: bool):
        """A collection argument narrowed for this person (the RAG REST API, BL-010).

        Named collections must all be visible; with none named, the visible ones
        (a list when `multi`, the only one otherwise). Raises PERMISSION."""
        if not user_identifier or not access.Access.registered():
            return collection
        named = _as_list(collection)
        if named:
            denied = [c for c in named if not self._can_see_collection(company_short_name, user_identifier, c)]
            if denied:
                raise _denied(f"No access to the collection '{denied[0]}'.")
            return collection
        allowed = self.allowed_collections(company_short_name, user_identifier)
        if allowed is None:
            return collection
        if not allowed:
            raise _denied("No access to any document collection.")
        if multi:
            return allowed
        if len(allowed) == 1:
            return allowed[0]
        raise _denied("Name the collection: you can see only some of them.")

    def document_allowed(self, company_short_name: str, user_identifier: str | None, document_id) -> bool:
        if not user_identifier or not access.Access.registered():
            return True
        collection = self._document_collection(company_short_name, document_id)
        return not collection or self._can_see_collection(company_short_name, user_identifier, collection)

    def visible_collection_filter(self, company_short_name: str, user_identifier: str | None):
        """`fn(collection_name) -> bool` for lists of documents; None when nothing is restricted."""
        if not user_identifier or not access.Access.registered():
            return None
        allowed = self.allowed_collections(company_short_name, user_identifier)
        if allowed is None:
            return None
        allowed_set = set(allowed)
        return lambda name: name in allowed_set

    # ------------------------------------------------------------------- listings
    def allowed_collections(self, company_short_name: str, user_identifier: str | None) -> list[str] | None:
        """The collections the person may see, or None when nothing is restricted for them."""
        names = self._collection_names(company_short_name)
        allowed = [n for n in names if self._can_see_collection(company_short_name, user_identifier, n)]
        return None if len(allowed) == len(names) else allowed

    def allowed_wiki_keys(self, company_short_name: str, user_identifier: str | None) -> list[str] | None:
        keys = self._wiki_keys(company_short_name)
        allowed = [k for k in keys if access.can(company_short_name, user_identifier, USE, "knowledge_wiki", k)]
        return None if len(allowed) == len(keys) else allowed

    def allowed_databases(self, company_short_name: str, user_identifier: str | None,
                          databases: list[str]) -> list[str]:
        return [d for d in databases if access.can(company_short_name, user_identifier, USE, "sql_source", d)]

    def _can_see_collection(self, company_short_name: str, user_identifier: str | None, collection: str) -> bool:
        return access.can(company_short_name, user_identifier, USE, "rag_collection", collection)

    def _company_id(self, company_short_name: str) -> int | None:
        return self.session.execute(select(Company.id).where(Company.short_name == company_short_name)).scalar()

    def _collection_names(self, company_short_name: str) -> list[str]:
        company_id = self._company_id(company_short_name)
        if company_id is None:
            return []
        return [str(n) for n in self.session.execute(
            select(CollectionType.name).where(CollectionType.company_id == company_id)).scalars()]

    def _wiki_keys(self, company_short_name: str) -> list[str]:
        company_id = self._company_id(company_short_name)
        if company_id is None:
            return []
        return [str(k) for k in self.session.execute(
            select(KnowledgeWiki.wiki_key).where(KnowledgeWiki.company_id == company_id)).scalars()]

    def _document_collection(self, company_short_name: str, document_id) -> str | None:
        try:
            doc_id = int(document_id)
        except (TypeError, ValueError):
            return None
        return self.session.execute(
            select(CollectionType.name)
            .join(Document, Document.collection_type_id == CollectionType.id)
            .join(Company, Company.id == Document.company_id)
            .where(Document.id == doc_id, Company.short_name == company_short_name)
        ).scalar()


def _as_list(value) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(v).strip() for v in values if str(v or "").strip()]


def _denied(message: str) -> IAToolkitException:
    return IAToolkitException(IAToolkitException.ErrorType.PERMISSION, message)
