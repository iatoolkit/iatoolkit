"""BL-034 R9: each company decides how long personal data is kept."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import AccessLog, Company, Conversation, LLMQuery
from iatoolkit.services.privacy.erasure_service import PrivacyErasureService, pseudonym_for
from iatoolkit.services.privacy.retention_service import PrivacyRetentionService, parse_retention

NOW = datetime(2026, 11, 27, 12, 0)
OLD, RECENT = NOW - timedelta(days=400), NOW - timedelta(days=10)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("IATOOLKIT_SECRET_KEY", "k" * 64)
    db = DatabaseManager(f"sqlite:///{tmp_path / 'retention.db'}")
    db.create_all()
    session = db.get_session()
    acme, other = Company(name="Acme", short_name="acme"), Company(name="Otra", short_name="otra")
    session.add_all([acme, other])
    session.flush()
    session.add_all([
        LLMQuery(company_id=acme.id, user_identifier="ana@acme.cl", query="vieja", output="", created_at=OLD),
        LLMQuery(company_id=acme.id, user_identifier="ana@acme.cl", query="nueva", output="", created_at=RECENT),
        LLMQuery(company_id=other.id, user_identifier="ana@acme.cl", query="otra", output="", created_at=OLD),
        Conversation(public_id="old", company_id=acme.id, owner_user_identifier="ana@acme.cl",
                     last_message_at=OLD),
        Conversation(public_id="new", company_id=acme.id, owner_user_identifier="ana@acme.cl",
                     last_message_at=RECENT),
        AccessLog(id=1, company_short_name="acme", user_identifier="ana@acme.cl", auth_type="local",
                  outcome="success", source_ip="10.0.0.1", request_path="/", timestamp=OLD),
        AccessLog(id=2, company_short_name="acme", user_identifier="service:mcp", auth_type="api_key",
                  outcome="success", source_ip="10.0.0.2", request_path="/", timestamp=OLD),
        AccessLog(id=3, company_short_name="acme", user_identifier="ana@acme.cl", auth_type="local",
                  outcome="success", source_ip="10.0.0.3", request_path="/", timestamp=RECENT),
    ])
    session.commit()

    config = MagicMock()
    config.get_configuration.side_effect = lambda company, key: (
        {"retention": {"conversations_days": 365, "audit_days": 180}} if key == "privacy" and company == "acme"
        else None)
    erasure = PrivacyErasureService(db, MagicMock())
    return {"session": session, "service": PrivacyRetentionService(db, config, erasure), "acme": acme,
            "other": other}


def _all(session, model):
    session.expire_all()
    return session.execute(select(model)).scalars().all()


def test_settings_are_validated():
    assert parse_retention(None) == ({}, [])
    assert parse_retention({"retention": {"conversations_days": 30}}) == ({"conversations": 30}, [])
    _, errors = parse_retention({"retention": {"conversations_days": 0, "audit_days": "x", "files_days": 3}})
    assert len(errors) == 3


def test_nothing_happens_without_settings(world):
    result = world["service"].apply("otra", now=NOW)
    assert result["status"] == "not_configured"
    assert len(_all(world["session"], LLMQuery)) == 3


def test_a_dry_run_counts_and_changes_nothing(world):
    result = world["service"].apply("acme", dry_run=True, now=NOW)
    assert result["summary"]["iat_queries"] == 1 and result["summary"]["iat_conversations"] == 1
    assert len(_all(world["session"], LLMQuery)) == 3


def test_old_conversations_go_and_old_audit_is_pseudonymized(world):
    session = world["session"]

    result = world["service"].apply("acme", now=NOW)

    assert result["status"] == "completed"
    queries = {(q.company_id, q.query) for q in _all(session, LLMQuery)}
    assert queries == {(world["acme"].id, "nueva"), (world["other"].id, "otra")}
    assert [c.public_id for c in _all(session, Conversation)] == ["new"]
    logs = {log.id: log for log in _all(session, AccessLog)}
    assert logs[1].user_identifier == pseudonym_for("acme", "ana@acme.cl") and logs[1].source_ip == "0.0.0.0"
    assert logs[2].user_identifier == "service:mcp"   # not a person
    assert logs[3].user_identifier == "ana@acme.cl"   # recent
    # Running again changes nothing more.
    assert world["service"].apply("acme", now=NOW)["rows"] == 0
