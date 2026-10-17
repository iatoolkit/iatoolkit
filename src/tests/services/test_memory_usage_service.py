from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.memory_usage_repo import MemoryUsageRepo
from iatoolkit.repositories.models import Company, MemoryUsageEvent
from iatoolkit.services.memory_usage_service import MemoryUsageService


@pytest.fixture
def env():
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all()
    session = db.get_session()
    company = Company(name="Acme", short_name="acme")
    session.add(company)
    session.commit()
    profile = MagicMock()
    profile.get_company_by_short_name.return_value = company
    repo = MemoryUsageRepo(db)
    return MemoryUsageService(repo, profile), repo, session, company


def test_searches_and_reads_are_recorded_and_summarized(env):
    service, repo, session, company = env
    service.record("acme", "iat_memory_search", {"query": "plazo de pago"}, {"results": [{"id": 7}]},
                   user_identifier="carmen@acme.cl")
    service.record("acme", "iat_document_search", {"query": "precios"}, {"chunks": []}, channel="mcp")
    service.record("acme", "iat_memory_get_page", {"page_id": 7}, {"page": {"id": 7}})
    service.record("acme", "iat_memory_get_page", {"page_id": "7"}, {"page": {"id": 7}})
    service.record("acme", "iat_document_read", {"document_id": 3}, {"text": "..."})
    service.record("acme", "iat_sql_query", {"sql": "select 1"}, {})

    now = datetime.now()
    summary = repo.summarize(company.id, now - timedelta(days=1), now + timedelta(days=1))

    assert session.query(MemoryUsageEvent).count() == 5
    assert summary["searches"] == 2 and summary["searches_found"] == 1
    assert summary["by_channel"] == {"chat": 1, "mcp": 1}
    assert summary["page_reads"] == {"7": 2} and summary["document_reads"] == {"3": 1}


def test_a_failed_record_never_breaks_the_tool(env):
    service, repo, _, _ = env
    repo.add = MagicMock(side_effect=RuntimeError("db down"))

    service.record("acme", "iat_memory_search", {"query": "x"}, {"results": []})
