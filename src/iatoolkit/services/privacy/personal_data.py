# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Where a person's data lives, and what erasing them does to each place (BL-034, R9).

Every column that holds who someone is (an email, a user identifier, an IP)
is declared here with one action:

- DELETE: the row is the person's own content (their questions and answers,
  conversations, feedback, tokens, invitations) and goes away with them.
- PSEUDONYMIZE: the row is a record or something others use (audit, billing,
  authorship of prompts, memory, wiki pages, tasks). It stays, and the person's
  identifier is replaced by a stable pseudonym such as `erased-3f9a1c0b7d2e`, so
  the audit still reads as one actor without saying who.
- REMOVE_FROM_LIST: a JSON list of people (folder owners) loses the person.
- ACCOUNT: the login account itself (iat_users, its identities, its membership),
  handled by the erasure service: the person leaves the company, and the account
  is deleted when no other company has them.
- KEEP: not a person's identity (a flag, a hash, a domain, an external contact),
  with the reason.

Erasure is per company: only rows of that company are touched.

Core declares its tables below; an extension (Enterprise) declares its own at
import with `register`. A test fails when a table has a column that looks
personal and nobody declared it, so a new table cannot be forgotten.

A declaration may also name a retention category (`conversations`, `audit`) and
the column that dates the row: the daily retention applies the same action to
rows older than the company's `privacy.retention.<category>_days`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DELETE = "delete"
PSEUDONYMIZE = "pseudonymize"
REMOVE_FROM_LIST = "remove_from_list"
ACCOUNT = "account"
KEEP = "keep"
ACTIONS = (DELETE, PSEUDONYMIZE, REMOVE_FROM_LIST, ACCOUNT, KEEP)

#: How the column identifies the person.
MATCH_IDENTIFIER = "identifier"   # the user identifier / email, compared case-insensitively
MATCH_USER_ID = "user_id"         # iat_users.id

RETENTION_CONVERSATIONS = "conversations"
RETENTION_AUDIT = "audit"
RETENTION_CATEGORIES = (RETENTION_CONVERSATIONS, RETENTION_AUDIT)

#: Column names that look like they hold who someone is. The guard test asks
#: every such column, in every table, to be declared.
PERSONAL_COLUMN_RE = re.compile(
    r"(user|email|identifier|author|owner|created_by|actor|principal|requested_by|subject"
    r"|(^|_)ip($|_)|ip_address|remote_addr)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PersonalColumn:
    table: str
    column: str
    action: str
    reason: str = ""
    match: str = MATCH_IDENTIFIER
    #: Extra equality conditions: only these rows hold a person (e.g. kind='user').
    where: tuple[tuple[str, str], ...] = ()
    #: Other columns of the same rows reset when the row is pseudonymized (an IP).
    scrub: tuple[tuple[str, str], ...] = ()
    retention: str | None = None
    age_column: str | None = None
    #: How the row reaches its company when it has no company column: the
    #: foreign key column and the parent table's company column are inferred.
    via: str | None = None

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"{self.table}.{self.column}: unknown action {self.action!r}")
        if self.action == KEEP and not self.reason:
            raise ValueError(f"{self.table}.{self.column}: KEEP needs a reason")
        if self.retention and self.retention not in RETENTION_CATEGORIES:
            raise ValueError(f"{self.table}.{self.column}: unknown retention {self.retention!r}")
        if self.retention and not self.age_column:
            raise ValueError(f"{self.table}.{self.column}: retention needs age_column")


_REGISTRY: dict[tuple[str, str], PersonalColumn] = {}


def register(*columns: PersonalColumn) -> None:
    for column in columns:
        _REGISTRY[(column.table, column.column)] = column


def declared() -> list[PersonalColumn]:
    return list(_REGISTRY.values())


def declaration(table: str, column: str) -> PersonalColumn | None:
    return _REGISTRY.get((table, column))


def acting(action: str | None = None) -> list[PersonalColumn]:
    """Declarations that change something on erasure, in registration order."""
    return [c for c in _REGISTRY.values() if c.action not in (KEEP,) and (action is None or c.action == action)]


def undeclared_columns(metadata) -> list[str]:
    """`table.column` of every column that looks personal and is not declared."""
    missing = []
    for table in metadata.tables.values():
        for column in table.columns:
            if PERSONAL_COLUMN_RE.search(column.name) and (table.name, column.name) not in _REGISTRY:
                missing.append(f"{table.name}.{column.name}")
    return sorted(missing)


def unknown_declarations(metadata) -> list[str]:
    """Declarations whose table or columns do not exist (a rename left behind)."""
    tables = {table.name: table for table in metadata.tables.values()}
    problems = []
    for item in _REGISTRY.values():
        table = tables.get(item.table)
        if table is None:
            continue  # an extension's table, absent when it is not installed
        names = set(table.columns.keys())
        needed = [item.column] + [name for name, _ in item.where] + [name for name, _ in item.scrub]
        if item.age_column:
            needed.append(item.age_column)
        if item.via:
            needed.append(item.via)
        for name in needed:
            if name not in names:
                problems.append(f"{item.table}.{name}")
    return sorted(problems)


P, D, K = PSEUDONYMIZE, DELETE, KEEP

# ----------------------------------------------------------------- core tables
register(
    # The account.
    PersonalColumn("iat_users", "email", ACCOUNT),
    PersonalColumn("iat_users", "google_email", ACCOUNT),
    PersonalColumn("iat_users", "google_email_verified", KEEP, "flag of the account, deleted with it"),
    PersonalColumn("iat_user_identities", "user_id", ACCOUNT, match=MATCH_USER_ID),
    PersonalColumn("iat_user_identities", "subject", ACCOUNT),
    PersonalColumn("iat_user_identities", "email", ACCOUNT),
    PersonalColumn("iat_user_identities", "email_verified", KEEP, "flag of the identity, deleted with it"),
    PersonalColumn("iat_user_company", "user_id", ACCOUNT, match=MATCH_USER_ID),

    # The person's own content.
    PersonalColumn("iat_queries", "user_identifier", D,
                   retention=RETENTION_CONVERSATIONS, age_column="created_at"),
    PersonalColumn("iat_conversations", "owner_user_identifier", D,
                   retention=RETENTION_CONVERSATIONS, age_column="last_message_at"),
    PersonalColumn("iat_feedback", "user_identifier", D,
                   retention=RETENTION_CONVERSATIONS, age_column="created_at"),
    PersonalColumn("iat_mcp_tokens", "subject_identifier", D, where=(("subject_type", "user"),)),

    # Records and shared content: kept, the person replaced by a pseudonym.
    PersonalColumn("iat_conversation_messages", "author_user_identifier", P),
    PersonalColumn("iat_access_log", "user_identifier", P, scrub=(("source_ip", "0.0.0.0"),),
                   retention=RETENTION_AUDIT, age_column="timestamp"),
    PersonalColumn("iat_access_log", "source_ip", KEEP, "reset when the row is pseudonymized"),
    PersonalColumn("iat_access_log", "user_agent_hash", KEEP, "a hash, not reversible to a person"),
    PersonalColumn("iat_memory_usage_events", "user_identifier", P,
                   retention=RETENTION_AUDIT, age_column="created_at"),
    PersonalColumn("iat_documents", "user_identifier", P, "a company document the person loaded"),
    PersonalColumn("iat_memory_captures", "user_identifier", P, "teaches the company's Memoria"),
    PersonalColumn("iat_memory_items", "user_identifier", P, "teaches the company's Memoria"),
    PersonalColumn("iat_knowledge_wiki_pages", "owner", P, "a company page"),
    PersonalColumn("iat_mcp_tokens", "created_by_identifier", P),
    PersonalColumn("iat_data_erasure_requests", "requested_by", P, "the administrator who asked for an erasure"),

    # Not a person's identity.
    PersonalColumn("iat_mcp_tokens", "subject_type", KEEP, "the kind of subject, not who"),
    PersonalColumn("iat_api_keys", "can_act_for_users", KEEP, "a flag"),
    PersonalColumn("iat_bridges", "last_remote_addr", KEEP, "the address of a bridge machine, not a person"),
    PersonalColumn("iat_company_model_entitlements", "credential_owner", KEEP, "who pays: company or platform"),
)
