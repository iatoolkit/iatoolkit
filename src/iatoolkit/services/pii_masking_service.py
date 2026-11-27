# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Masking of `pii` columns in SQL results before they reach the model (BL-034, R11).

Turned on per company in company.yaml:

    privacy:
      pii_masking: mask        # off (default) | mask

With `mask`, the values of columns marked `pii: true` in a source's schema files
(written by the SQL modeler and by knowledge tables) leave each SQL result as
tokens such as `[PII-3f9a1c0b7d2e]`: in the chat's `iat_sql_query` and in the
MCP `query_sql`, the two ways a query result reaches a model.

The real values stay inside IAToolkit. Each token is kept for a while in Redis
for the person who received it, so that:

- a query the model writes with a token (`WHERE rut = '[PII-…]'`) runs with the
  value it stands for;
- the Excel, PDF and charts the model builds for the person carry the values.

The answer text keeps the tokens: putting the values back into what the person
reads is a later stage, since it touches the history and the stream.

Limits: only marked columns are masked (a free-text column with personal data
in it is not), and what the person writes in the chat goes to the model as is.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time

import yaml
from injector import inject

from iatoolkit.common import pii_masking
from iatoolkit.common.audit_log import emit_audit_event
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.sql_service import SqlService

MODE_OFF = "off"
MODE_MASK = "mask"
MODES = (MODE_OFF, MODE_MASK)


def normalize_mode(value) -> str | None:
    """The mode a company.yaml value means, None when it means nothing. YAML reads
    a bare `off` / `on` as false / true."""
    if value is None or value is False:
        return MODE_OFF
    if value is True:
        return MODE_MASK
    text = str(value).strip().lower()
    return text if text in MODES else None

#: Tools whose arguments are filled with the real values before they run: what
#: they produce goes to the person, never back to the model.
TOOLS_WITH_RESTORED_ARGUMENTS = frozenset({"iat_generate_excel", "iat_generate_pdf", "iat_chart"})

_PROCESS_KEY = secrets.token_bytes(32)


class PiiMaskingService:
    COLUMNS_CACHE_SECONDS = 300
    VAULT_PREFIX = "iat:pii"

    @inject
    def __init__(self,
                 configuration_service: ConfigurationService,
                 asset_repo: AssetRepository,
                 sql_service: SqlService):
        self.configuration_service = configuration_service
        self.asset_repo = asset_repo
        self.sql_service = sql_service
        self._columns_cache: dict[tuple[str, str], tuple[float, set[str]]] = {}

    # ------------------------------------------------------------------ settings

    def mode(self, company_short_name: str) -> str:
        try:
            privacy = self.configuration_service.get_configuration(company_short_name, "privacy") or {}
        except Exception as exc:
            logging.debug("pii masking: no configuration for %s: %s", company_short_name, exc)
            return MODE_OFF
        if not isinstance(privacy, dict):
            return MODE_OFF
        return normalize_mode(privacy.get("pii_masking")) or MODE_OFF

    def is_enabled(self, company_short_name: str) -> bool:
        return self.mode(company_short_name) == MODE_MASK

    @staticmethod
    def _token_ttl_seconds() -> int:
        try:
            hours = float(os.getenv("IAT_PII_TOKEN_TTL_HOURS", "24"))
        except ValueError:
            hours = 24
        return max(60, int(hours * 3600))

    @staticmethod
    def _token_key(company_short_name: str) -> bytes:
        secret = os.getenv("IATOOLKIT_SECRET_KEY") or ""
        base = secret.encode("utf-8") if secret else _PROCESS_KEY
        return base + b"|pii|" + str(company_short_name).encode("utf-8")

    # ------------------------------------------------------------- marked columns

    def pii_columns(self, company_short_name: str, database_key: str) -> set[str]:
        """Lowercase names of the columns marked pii in a source's schema files."""
        cache_key = (str(company_short_name), str(database_key))
        cached = self._columns_cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        names: set[str] = set()
        prefix = f"{str(database_key).strip().lower()}-"
        try:
            files = self.asset_repo.list_files(company_short_name, AssetType.SCHEMA)
        except Exception as exc:
            logging.warning("pii masking: could not list schema files of %s: %s", company_short_name, exc)
            files = []
        for filename in files:
            clean = str(filename).strip().lower()
            if not clean.startswith(prefix) or not clean.endswith((".yaml", ".yml")):
                continue
            try:
                content = self.asset_repo.read_text(company_short_name, AssetType.SCHEMA, filename)
                _collect_pii_columns(yaml.safe_load(content or "") or {}, names)
            except Exception as exc:
                logging.warning("pii masking: could not read schema file %s: %s", filename, exc)
        self._columns_cache[cache_key] = (time.monotonic() + self.COLUMNS_CACHE_SECONDS, names)
        return names

    def clear_cache(self) -> None:
        self._columns_cache.clear()

    # ------------------------------------------------------------------- masking

    def mask_sql_result(self, company_short_name: str, user_identifier: str | None,
                        database_key: str, query: str, result, *, channel: str = "chat"):
        """The result with marked values replaced by tokens, in the same shape it
        came (a JSON string or a list of rows)."""
        if not self.is_enabled(company_short_name):
            return result
        pii_names = self.pii_columns(company_short_name, database_key)
        if not pii_names:
            return result

        rows, as_text = result, False
        if isinstance(result, str):
            try:
                rows, as_text = json.loads(result), True
            except (TypeError, ValueError):
                return result
        if isinstance(rows, dict):
            rows_list, single = [rows], True
        elif isinstance(rows, list):
            rows_list, single = rows, False
        else:
            return result

        sensitive_names = pii_masking.sensitive_output_columns(
            query, pii_names, self._dialect(company_short_name, database_key))
        if sensitive_names is None:
            # Unparsed query that names a marked column: nothing in it is trusted.
            if pii_masking.mention_any(query, pii_names):
                sensitive = lambda _name: True
            else:
                sensitive = lambda name: name.lower() in pii_names
        else:
            sensitive = lambda name: name.lower() in sensitive_names

        key = self._token_key(company_short_name)
        vault: dict[str, object] = {}

        def tokenize(value):
            token = pii_masking.make_token(value, key)
            vault[token] = value
            return token

        masked_rows, masked_columns, count = pii_masking.mask_rows(rows_list, sensitive, tokenize)
        if not count:
            return result
        self._store(company_short_name, user_identifier, vault)
        logging.info("event=pii_masked company=%s database=%s channel=%s columns=%s values=%s",
                     company_short_name, database_key, channel, ",".join(sorted(masked_columns)), count)
        emit_audit_event("pii_masked", company=company_short_name, user=user_identifier,
                         database=database_key, channel=channel,
                         columns=",".join(sorted(masked_columns)), values=count)

        output = masked_rows[0] if single else masked_rows
        if as_text:
            return json.dumps(output, default=self.sql_service.util.serialize)
        return output

    def mask_chart_result(self, company_short_name: str, user_identifier: str | None,
                          arguments: dict, result):
        """A chart is drawn for the person with the real values, but the summary
        `iat_chart` returns to the model (rows, min, max, first, last) holds the
        x values. Those coming from a marked column, or from a token the model
        wrote, go back to the model as tokens."""
        if not self.is_enabled(company_short_name) or not isinstance(result, dict):
            return result
        model_view = result.get("data")
        if not isinstance(model_view, dict):
            return result

        from iatoolkit.services.chart_service import CHART_RESULT_KEY

        key = self._token_key(company_short_name)
        by_value: dict[str, str] = {}
        vault: dict[str, object] = {}

        # Values the model only knows as tokens (inline data, or a filter in the query).
        written_tokens = pii_masking.find_tokens(json.dumps(arguments, default=str, ensure_ascii=False))
        for token, value in self._load(company_short_name, user_identifier, written_tokens).items():
            by_value[pii_masking.canonical(value)] = token

        # Values the chart's own query read from a marked column.
        database_key = str(arguments.get("database_key") or "").strip()
        query = self.restore_sql(company_short_name, user_identifier, arguments.get("query"))
        chart = result.get(CHART_RESULT_KEY) if isinstance(result.get(CHART_RESULT_KEY), dict) else {}
        if database_key and query and chart:
            pii_names = self.pii_columns(company_short_name, database_key)
            if pii_names:
                sensitive_names = pii_masking.sensitive_output_columns(
                    query, pii_names, self._dialect(company_short_name, database_key))
                header = [str(name) for name in chart.get("columns") or []]
                if sensitive_names is None:
                    positions = (range(len(header)) if pii_masking.mention_any(query, pii_names)
                                 else [i for i, name in enumerate(header) if name.lower() in pii_names])
                else:
                    positions = [i for i, name in enumerate(header) if name.lower() in sensitive_names]
                for row in chart.get("rows") or []:
                    for index in positions:
                        if index < len(row) and row[index] is not None:
                            token = pii_masking.make_token(row[index], key)
                            vault[token] = row[index]
                            by_value[pii_masking.canonical(row[index])] = token

        if not by_value:
            return result
        self._store(company_short_name, user_identifier, vault)

        def hide(node):
            if isinstance(node, dict):
                return {k: hide(v) for k, v in node.items()}
            if isinstance(node, list):
                return [hide(item) for item in node]
            if node is None or isinstance(node, bool):
                return node
            return by_value.get(pii_masking.canonical(node), node)

        masked = dict(result)
        masked["data"] = hide(model_view)
        logging.info("event=pii_masked company=%s database=%s channel=chart values=%s",
                     company_short_name, database_key or "-", len(by_value))
        emit_audit_event("pii_masked", company=company_short_name, user=user_identifier,
                         database=database_key or None, channel="chart", values=len(by_value))
        return masked

    def _dialect(self, company_short_name: str, database_key: str) -> str | None:
        try:
            return self.sql_service.get_database_dialect(company_short_name, database_key) or None
        except Exception:
            return None

    # ----------------------------------------------------------------- restoring

    def restore_sql(self, company_short_name: str, user_identifier: str | None, query):
        """The query with each known token replaced by its value, quoted as SQL."""
        if not isinstance(query, str) or not pii_masking.TOKEN_RE.search(query):
            return query
        resolve = self._resolver(company_short_name, user_identifier, pii_masking.find_tokens(query))
        return pii_masking.replace_tokens(query, resolve, sql=True)

    def restore_arguments(self, company_short_name: str, user_identifier: str | None, arguments: dict) -> dict:
        """Tool arguments with each known token replaced by its value."""
        text = json.dumps(arguments, default=str, ensure_ascii=False)
        tokens = pii_masking.find_tokens(text)
        if not tokens:
            return arguments
        resolve = self._resolver(company_short_name, user_identifier, tokens)
        return pii_masking.replace_tokens_in(arguments, resolve)

    def _resolver(self, company_short_name: str, user_identifier: str | None, tokens: list[str]):
        values = self._load(company_short_name, user_identifier, tokens)
        return lambda token: values.get(token, pii_masking.MISSING)

    # --------------------------------------------------------------------- vault

    def _vault_key(self, company_short_name: str, user_identifier: str | None) -> str:
        return f"{self.VAULT_PREFIX}:{company_short_name}:{user_identifier or '-'}"

    def _store(self, company_short_name: str, user_identifier: str | None, vault: dict) -> None:
        if not vault:
            return
        try:
            from iatoolkit.infra.redis_session_manager import RedisSessionManager

            key = self._vault_key(company_short_name, user_identifier)
            pipe = RedisSessionManager.pipeline()
            for token, value in vault.items():
                pipe.hset(key, token, json.dumps(value, default=str, ensure_ascii=False))
            pipe.expire(key, self._token_ttl_seconds())
            pipe.execute()
        except Exception as exc:
            # Without the vault the tokens still protect the data; they just
            # cannot be turned back into values in later queries or files.
            logging.warning("pii masking: could not keep the tokens of %s: %s", company_short_name, exc)

    def _load(self, company_short_name: str, user_identifier: str | None, tokens: list[str]) -> dict:
        if not tokens:
            return {}
        try:
            from iatoolkit.infra.redis_session_manager import RedisSessionManager

            key = self._vault_key(company_short_name, user_identifier)
            values = {}
            for token in dict.fromkeys(tokens):
                raw = RedisSessionManager.hget(key, token)
                if raw is not None:
                    values[token] = json.loads(raw)
            return values
        except Exception as exc:
            logging.warning("pii masking: could not read the tokens of %s: %s", company_short_name, exc)
            return {}


def _collect_pii_columns(node, names: set[str]) -> None:
    """Column names marked `pii: true` anywhere in a schema file, whatever its
    layout (nested under the table, flat, `columns` or `fields`, map or list)."""
    if isinstance(node, dict):
        for key in ("columns", "fields"):
            columns = node.get(key)
            if isinstance(columns, dict):
                for name, spec in columns.items():
                    if isinstance(spec, dict) and spec.get("pii") is True:
                        names.add(str(name).lower())
            elif isinstance(columns, list):
                for spec in columns:
                    if isinstance(spec, dict) and spec.get("pii") is True and spec.get("name"):
                        names.add(str(spec["name"]).lower())
        for value in node.values():
            if isinstance(value, (dict, list)):
                _collect_pii_columns(value, names)
    elif isinstance(node, list):
        for item in node:
            _collect_pii_columns(item, names)
