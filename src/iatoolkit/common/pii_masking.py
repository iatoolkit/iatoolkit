# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Masking of personal data in SQL results before they reach the model (BL-034, R11).

Columns marked `pii: true` in a source's schema (the SQL modeler, knowledge
tables) are replaced in each result row by a token such as `[PII-3f9a1c0b7d2e]`
before the rows are handed to the model. The model reasons on the token ("the
client [PII-3f9a…] has 3 loans") without ever receiving the value.

This module holds the parts that need no application state:

- `sensitive_output_columns` decides which result columns carry a marked column,
  following aliases, expressions, subqueries and CTEs. `SELECT rut AS id` hides
  `id`; `COUNT(DISTINCT rut)` does not, a count reveals no value.
- `make_token` turns a value into a token with a keyed HMAC. Without the key a
  token cannot be reversed by hashing every possible RUT.
- `replace_tokens` puts the real values back where the model wrote a token: in
  the SQL it runs next, and in the files and charts it builds for the person.
"""

from __future__ import annotations

import hashlib
import html as _html
import hmac
import json
import re
from typing import Callable, Iterable

TOKEN_PREFIX = "PII-"
TOKEN_RE = re.compile(r"\[PII-([0-9a-f]{12})\]")

#: Aggregates that reveal no value of the column they read.
_SAFE_AGGREGATE_NAMES = frozenset({"count"})


def make_token(value, key: bytes) -> str:
    """A stable token for a value: the same value gives the same token, so the
    model can still group, join and compare what it sees."""
    digest = hmac.new(key, canonical(value).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"[{TOKEN_PREFIX}{digest[:12]}]"


def canonical(value) -> str:
    if isinstance(value, (dict, list)):
        return "json:" + json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return f"{type(value).__name__}:{value}"


def mention_any(query: str, names: Iterable[str]) -> bool:
    text = str(query or "").lower()
    return any(re.search(rf"\b{re.escape(name)}\b", text) for name in names if name)


def sensitive_output_columns(query: str, pii_names: set[str], dialect: str | None = None) -> set[str] | None:
    """The lowercase output names that may carry a marked column's values.

    Returns None when the query cannot be parsed: the caller then treats every
    column as sensitive if the query names a marked column.
    """
    pii = {str(name).lower() for name in pii_names if name}
    if not pii:
        return set()
    try:
        import sqlglot
        from sqlglot import exp

        trees = [tree for tree in sqlglot.parse(str(query or ""), read=_sqlglot_dialect(dialect)) if tree is not None]
    except Exception:
        return None
    if not trees:
        return None

    tainted = set(pii)
    selects = [select for tree in trees for select in tree.find_all(exp.Select)]
    # Aliases feed outer queries (subqueries, CTEs): repeat until nothing new is tainted.
    changed = True
    while changed:
        changed = False
        for select in selects:
            for projection in select.expressions:
                name = (projection.alias_or_name or "").lower()
                if not name or name in tainted:
                    continue
                if _projection_reveals(projection, tainted):
                    tainted.add(name)
                    changed = True
    return tainted


def _projection_reveals(projection, tainted: set[str]) -> bool:
    from sqlglot import exp

    for column in projection.find_all(exp.Column):
        if (column.name or "").lower() not in tainted:
            continue
        if not _inside_safe_aggregate(column, projection):
            return True
    return False


def _inside_safe_aggregate(node, stop) -> bool:
    from sqlglot import exp

    current = node.parent
    while current is not None and current is not stop.parent:
        if isinstance(current, exp.Count):
            return True
        if isinstance(current, exp.Anonymous) and str(current.name or "").lower() in _SAFE_AGGREGATE_NAMES:
            return True
        current = current.parent
    return False


def _sqlglot_dialect(dialect: str | None) -> str | None:
    value = str(dialect or "").strip().lower()
    if not value:
        return None
    aliases = {
        "postgresql": "postgres",
        "mssql": "tsql",
        "sqlserver": "tsql",
        "sql_server": "tsql",
        "mariadb": "mysql",
    }
    value = aliases.get(value, value)
    try:
        from sqlglot.dialects.dialect import Dialect

        Dialect.get_or_raise(value)
        return value
    except Exception:
        return None


def mask_rows(rows: list, sensitive: Callable[[str], bool], tokenize: Callable[[object], str]) -> tuple[list, set[str], int]:
    """Returns the rows with sensitive values replaced, the columns masked and
    how many values were replaced. Nulls stay null: an empty value reveals nothing."""
    masked_columns: set[str] = set()
    count = 0
    output = []
    for row in rows:
        if not isinstance(row, dict):
            output.append(row)
            continue
        new_row = {}
        for key, value in row.items():
            if value is not None and sensitive(str(key)):
                new_row[key] = tokenize(value)
                masked_columns.add(str(key))
                count += 1
            else:
                new_row[key] = value
        output.append(new_row)
    return output, masked_columns, count


def find_tokens(text: str) -> list[str]:
    return [f"[{TOKEN_PREFIX}{match}]" for match in TOKEN_RE.findall(str(text or ""))]


def replace_tokens(text: str, resolve: Callable[[str], object], *, sql: bool = False,
                   html: bool = False) -> str:
    """Replaces each known token with its value. In SQL the value goes inside the
    quotes the model already wrote, so a quote in it is doubled; in HTML it is
    escaped. Unknown tokens are left as written."""

    def substitute(match: re.Match) -> str:
        token = match.group(0)
        value = resolve(token)
        if value is _MISSING:
            return token
        rendered = value if isinstance(value, str) else (
            json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)
        )
        if sql:
            return rendered.replace("'", "''")
        if html:
            return _html.escape(rendered, quote=True)
        return rendered

    return TOKEN_RE.sub(substitute, str(text))


def replace_tokens_in(payload, resolve: Callable[[str], object]):
    """The same replacement in every string of a JSON-like payload."""
    if isinstance(payload, str):
        return replace_tokens(payload, resolve) if TOKEN_RE.search(payload) else payload
    if isinstance(payload, list):
        return [replace_tokens_in(item, resolve) for item in payload]
    if isinstance(payload, tuple):
        return tuple(replace_tokens_in(item, resolve) for item in payload)
    if isinstance(payload, dict):
        return {key: replace_tokens_in(value, resolve) for key, value in payload.items()}
    return payload


TOKEN_LENGTH = len("[PII-") + 12 + 1
_PARTIAL_TOKEN_RE = re.compile(r"\[(P(I(I(-[0-9a-f]{0,12})?)?)?)?")


class StreamingTokenRestorer:
    """Restores tokens in text that arrives in pieces: a token cut between two
    pieces is held back until it is complete (at most 17 characters)."""

    def __init__(self, resolve: Callable[[str], object]):
        self.resolve = resolve
        self.pending = ""

    def feed(self, text: str) -> str:
        data = self.pending + (text or "")
        cut = len(data)
        start = data.rfind("[", max(0, len(data) - TOKEN_LENGTH + 1))
        if start != -1 and _PARTIAL_TOKEN_RE.fullmatch(data[start:]):
            cut = start
        ready, self.pending = data[:cut], data[cut:]
        return replace_tokens(ready, self.resolve) if ready else ""

    def flush(self) -> str:
        rest, self.pending = self.pending, ""
        return replace_tokens(rest, self.resolve) if rest else ""


class _Missing:
    def __repr__(self):
        return "<missing>"


_MISSING = _Missing()
MISSING = _MISSING
