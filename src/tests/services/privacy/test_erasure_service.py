"""BL-034 R9: erasing a person from a company."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import (
    AccessLog, Company, Conversation, ConversationMessage, DataErasureRequest, LLMQuery,
    MemoryItem, User, UserFeedback, user_company,
)
from iatoolkit.services.privacy.erasure_service import PrivacyErasureService, pseudonym_for

ANA, BETO = "ana@acme.cl", "beto@acme.cl"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("IATOOLKIT_SECRET_KEY", "k" * 64)
    db = DatabaseManager(f"sqlite:///{tmp_path / 'erase.db'}")
    db.create_all()
    session = db.get_session()
    acme, other = Company(name="Acme", short_name="acme"), Company(name="Otra", short_name="otra")
    ana = User(email=ANA, first_name="Ana", last_name="Pérez")
    beto = User(email=BETO, first_name="Beto", last_name="Soto")
    session.add_all([acme, other, ana, beto])
    session.flush()
    session.execute(user_company.insert(), [
        {"user_id": ana.id, "company_id": acme.id}, {"user_id": beto.id, "company_id": acme.id}])

    # Ana's own content in acme.
    ana_query = LLMQuery(company_id=acme.id, user_identifier="Ana@Acme.cl", query="rut de clientes",
                         output="...")
    ana_conversation = Conversation(public_id="c-ana", company_id=acme.id, owner_user_identifier=ANA)
    session.add_all([ana_query, ana_conversation])
    session.flush()
    session.add_all([
        ConversationMessage(conversation_id=ana_conversation.id, company_id=acme.id, role="user",
                            author_user_identifier=ANA, content="hola", llm_query_id=ana_query.id),
        UserFeedback(company_id=acme.id, user_identifier=ANA, message="bien", rating=5),
    ])
    # Ana's message in Beto's conversation points to her query.
    beto_conversation = Conversation(public_id="c-beto", company_id=acme.id, owner_user_identifier=BETO)
    session.add(beto_conversation)
    session.flush()
    session.add(ConversationMessage(conversation_id=beto_conversation.id, company_id=acme.id, role="user",
                                    author_user_identifier=ANA, content="aporte", llm_query_id=ana_query.id))
    # Records that stay.
    session.add_all([
        # SQLite does not autoincrement a BIGINT key: ids given.
        AccessLog(id=1, company_short_name="acme", user_identifier=ANA, auth_type="local", outcome="success",
                  source_ip="10.1.2.3", request_path="/login"),
        MemoryItem(company_id=acme.id, user_identifier=ANA, title="nota"),
        # The same person in another company is not touched.
        LLMQuery(company_id=other.id, user_identifier=ANA, query="otra", output="..."),
        AccessLog(id=2, company_short_name="otra", user_identifier=ANA, auth_type="local", outcome="success",
                  source_ip="10.9.9.9", request_path="/login"),
    ])
    session.commit()

    storage = MagicMock()
    storage.list_files.return_value = [{"path": f"companies/acme/users/{ANA}/memory/a.md"}]
    service = PrivacyErasureService(db, storage)
    return {"db": db, "session": session, "service": service, "storage": storage,
            "acme": acme, "other": other, "ana": ana, "beto": beto, "ana_query": ana_query}


def _rows(session, model, *conditions):
    session.expire_all()
    return session.execute(select(model).where(*conditions)).scalars().all()


def test_a_dry_run_counts_and_changes_nothing(world):
    service, session = world["service"], world["session"]

    result = service.erase("acme", ANA, requested_by=BETO, dry_run=True)

    assert result["dry_run"] is True and result["account"] == "deleted"
    assert result["summary"]["iat_queries"] == 1
    assert result["summary"]["iat_conversations"] == 1
    assert result["summary"]["iat_access_log.user_identifier"] == 1
    assert len(_rows(session, LLMQuery, LLMQuery.company_id == world["acme"].id)) == 1
    assert _rows(session, DataErasureRequest) == []
    world["storage"].delete_file.assert_not_called()


def test_erasing_deletes_own_content_and_pseudonymizes_records(world):
    service, session, acme = world["service"], world["session"], world["acme"]
    pseudonym = pseudonym_for("acme", ANA)

    result = service.erase("acme", "ANA@acme.cl", requested_by=BETO)

    assert result["pseudonym"] == pseudonym
    # Own content gone (the identifier matched case-insensitively).
    assert _rows(session, LLMQuery, LLMQuery.company_id == acme.id) == []
    assert [c.public_id for c in _rows(session, Conversation)] == ["c-beto"]
    assert _rows(session, UserFeedback) == []
    # Her message in Beto's conversation stays, pseudonymized, without the deleted query.
    message = _rows(session, ConversationMessage)[0]
    assert message.author_user_identifier == pseudonym and message.llm_query_id is None
    # Records stay, pseudonymized, with the IP reset.
    log = _rows(session, AccessLog, AccessLog.company_short_name == "acme")[0]
    assert log.user_identifier == pseudonym and log.source_ip == "0.0.0.0"
    assert _rows(session, MemoryItem)[0].user_identifier == pseudonym
    # Another company keeps everything.
    assert len(_rows(session, LLMQuery, LLMQuery.company_id == world["other"].id)) == 1
    assert _rows(session, AccessLog, AccessLog.company_short_name == "otra")[0].user_identifier == ANA
    # The account had no other company: deleted. Beto is untouched.
    assert [u.email for u in _rows(session, User)] == [BETO]
    # Files and receipt.
    world["storage"].delete_file.assert_called_once_with("acme", f"companies/acme/users/{ANA}/memory/a.md")
    receipt = _rows(session, DataErasureRequest)[0]
    assert receipt.pseudonym == pseudonym and receipt.requested_by == BETO
    assert receipt.account_outcome == "deleted" and receipt.files_deleted == 1
    assert ANA not in str(receipt.to_dict()).lower()


def test_an_account_in_another_company_only_leaves_this_one(world):
    session = world["session"]
    session.execute(user_company.insert(), [{"user_id": world["ana"].id, "company_id": world["other"].id}])
    session.commit()

    result = world["service"].erase("acme", ANA, requested_by=BETO)

    assert result["account"] == "left_company"
    assert [u.email for u in _rows(session, User, User.email == ANA)] == [ANA]
    memberships = session.execute(select(user_company.c.company_id).where(
        user_company.c.user_id == world["ana"].id)).scalars().all()
    assert memberships == [world["other"].id]


def test_erasing_is_repeatable_and_rejects_non_people(world):
    service = world["service"]
    service.erase("acme", ANA, requested_by=BETO)
    again = service.erase("acme", ANA, requested_by=BETO, dry_run=True)
    assert again["rows"] == 0 and again["account"] == "not_found"

    with pytest.raises(IAToolkitException):
        service.erase("acme", "service:mcp", requested_by=BETO)
    with pytest.raises(IAToolkitException):
        service.erase("acme", pseudonym_for("acme", ANA), requested_by=BETO)
    with pytest.raises(IAToolkitException):
        service.erase("nope", ANA, requested_by=BETO)


def test_receipts_are_listed_without_the_person(world):
    world["service"].erase("acme", ANA, requested_by=BETO)
    receipts = world["service"].list_receipts("acme")
    assert len(receipts) == 1 and receipts[0]["requested_by"] == BETO
    assert ANA not in str(receipts)
