# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Audit records as log events, for a SIEM to receive them with the rest of the logs
(BL-034, R13).

The audit tables (iat_access_log, tool call events, MCP request audit) stay the
record of truth. With IAT_AUDIT_LOG_EVENTS=true each new record is also written to
the "iatoolkit.audit" logger as

    event=audit_<kind> company=acme user=ana@acme.com outcome=success ...

With IAT_LOG_FORMAT=json those fields come out as JSON fields, so a SIEM that
already collects the application's stdout (CloudWatch, Azure Monitor, Splunk,
Elastic, Sentinel) needs no connector and no access to the database. Off by
default: the tables are enough where nobody consumes the events.

Only identifiers and outcomes are written, never prompts, tool arguments or results.
"""

from __future__ import annotations

import json
import logging
import os

AUDIT_LOGGER_NAME = "iatoolkit.audit"
AUDIT_EVENTS_ENV = "IAT_AUDIT_LOG_EVENTS"
_TRUE_VALUES = ("1", "true", "yes", "on")
_MAX_VALUE_LENGTH = 300


def audit_events_enabled() -> bool:
    return str(os.getenv(AUDIT_EVENTS_ENV) or "").strip().lower() in _TRUE_VALUES


def _text_value(value) -> str:
    text = str(value)
    if not text or any(ch.isspace() or ch in '"=' for ch in text):
        return json.dumps(text, ensure_ascii=False)
    return text


def emit_audit_event(kind: str, **fields) -> None:
    """Write one audit record to the audit logger. Never raises: auditing must not break the request."""
    if not audit_events_enabled():
        return
    try:
        event = f"audit_{kind}"
        clean = {}
        for key, value in fields.items():
            if value is None or value == "":
                continue
            if not isinstance(value, (int, float, bool)):
                value = str(value)[:_MAX_VALUE_LENGTH]
            clean[key] = value
        message = " ".join([f"event={event}"] + [f"{key}={_text_value(value)}" for key, value in clean.items()])
        logging.getLogger(AUDIT_LOGGER_NAME).info(message, extra={"audit": {"event": event, **clean}})
    except Exception:
        logging.debug("Could not emit audit event %s", kind, exc_info=True)
