# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import io
import json
import logging

import pytest

from iatoolkit.common.audit_log import AUDIT_LOGGER_NAME, emit_audit_event
from iatoolkit.runtime_logging import JsonLogFormatter, build_log_formatter


def _capture(formatter=None):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    if formatter:
        handler.setFormatter(formatter)
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return stream, lambda: logger.removeHandler(handler)


def test_audit_events_are_off_by_default(monkeypatch):
    monkeypatch.delenv("IAT_AUDIT_LOG_EVENTS", raising=False)
    stream, done = _capture()
    try:
        emit_audit_event("access", company="acme", outcome="success")
    finally:
        done()
    assert stream.getvalue() == ""


def test_an_audit_event_is_a_key_value_line(monkeypatch):
    monkeypatch.setenv("IAT_AUDIT_LOG_EVENTS", "true")
    stream, done = _capture()
    try:
        emit_audit_event("access", company="acme", user="ana@acme.com", outcome="failure",
                         reason="bad password", status_code=401, empty=None)
    finally:
        done()
    line = stream.getvalue().strip()
    assert line == ('event=audit_access company=acme user=ana@acme.com outcome=failure '
                    'reason="bad password" status_code=401')


def test_in_json_each_audit_field_is_its_own_field(monkeypatch):
    monkeypatch.setenv("IAT_AUDIT_LOG_EVENTS", "true")
    stream, done = _capture(JsonLogFormatter(service="iatoolkit-test"))
    try:
        emit_audit_event("tool_call", company="acme", tool="query_sql", status="success", duration_ms=42)
    finally:
        done()
    record = json.loads(stream.getvalue())
    assert record["event"] == "audit_tool_call"
    assert record["company"] == "acme"
    assert record["tool"] == "query_sql"
    assert record["duration_ms"] == 42
    assert record["service"] == "iatoolkit-test"
    assert record["logger"] == AUDIT_LOGGER_NAME
    assert record["@timestamp"].endswith("Z")


def test_an_event_line_is_split_into_fields_in_json():
    record = logging.LogRecord("root", logging.WARNING, __file__, 1,
                               'event=csrf_blocked method=POST path=/acme reason=foreign_origin note="two words"',
                               None, None)
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["event"] == "csrf_blocked"
    assert payload["reason"] == "foreign_origin"
    assert payload["note"] == "two words"
    assert payload["level"] == "WARNING"


def test_a_plain_message_and_an_exception_in_json():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord("app", logging.ERROR, __file__, 1, "something failed", None, sys.exc_info())
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "something failed"
    assert "event" not in payload
    assert payload["error.type"] == "ValueError"
    assert "boom" in payload["error.stack"]


@pytest.mark.parametrize("value, is_json", [("json", True), ("JSON", True), ("text", False), ("", False)])
def test_the_format_is_chosen_by_environment(monkeypatch, value, is_json):
    monkeypatch.setenv("IAT_LOG_FORMAT", value)
    assert isinstance(build_log_formatter(), JsonLogFormatter) is is_json


def test_a_failed_emit_never_raises(monkeypatch):
    monkeypatch.setenv("IAT_AUDIT_LOG_EVENTS", "true")

    class Unprintable:
        def __str__(self):
            raise RuntimeError("no")

    emit_audit_event("access", company=Unprintable())
