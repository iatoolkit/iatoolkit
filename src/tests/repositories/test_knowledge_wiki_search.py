# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The hybrid wiki search on Postgres (SOP-654): the stored tsvector and the timeout."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import CreateIndex, CreateTable

from iatoolkit.repositories.knowledge_wiki_repo import KnowledgeWikiRepo, WikiSearchTimeout
from iatoolkit.repositories.models import KnowledgeWikiPageIndex


class _PgError(Exception):
    def __init__(self, pgcode):
        super().__init__(pgcode)
        self.pgcode = pgcode


def _repo(session):
    db_manager = MagicMock()
    db_manager.get_session.return_value = session
    return KnowledgeWikiRepo(db_manager)


def _statements(session):
    return [str(call.args[0]) for call in session.execute.call_args_list]


def test_postgres_stores_the_tsvector_and_indexes_it():
    table = KnowledgeWikiPageIndex.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    indexes = [str(CreateIndex(index).compile(dialect=postgresql.dialect())) for index in table.indexes]

    assert ("search_tsv TSVECTOR GENERATED ALWAYS AS "
            "(to_tsvector('simple'::regconfig, search_text)) STORED") in ddl
    assert any("USING gin (search_tsv)" in index for index in indexes)
    # the old expression index, which made every search recompute to_tsvector, is gone
    assert not any("to_tsvector" in index for index in indexes)


def test_the_search_ranks_with_the_stored_tsvector_and_restores_the_timeout():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = "0"
    session.execute.return_value.fetchall.return_value = [(7, 0.03)]

    assert _repo(session).hybrid_search_pages([1], "error en la cola", None) == [(7, 0.03)]

    statements = _statements(session)
    search = next(s for s in statements if "rrf_score" in s)
    assert "ts_rank_cd(i.search_tsv," in search and "i.search_tsv @@" in search
    assert "to_tsvector(" not in search
    timeouts = [call.args[1]["ms"] for call in session.execute.call_args_list
                if "set_config('statement_timeout'" in str(call.args[0])]
    assert timeouts == [str(KnowledgeWikiRepo.SEARCH_TIMEOUT_MS), "0"]


def test_a_cancelled_search_is_a_timeout():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = "0"

    def execute(statement, *args, **kwargs):
        if "rrf_score" in str(statement):
            raise OperationalError("SELECT ...", {}, _PgError("57014"))
        return MagicMock(scalar=MagicMock(return_value="0"))

    session.execute.side_effect = execute

    with pytest.raises(WikiSearchTimeout):
        _repo(session).hybrid_search_pages([1], "cola", None)


def test_another_database_error_is_not_a_timeout():
    session = MagicMock()

    def execute(statement, *args, **kwargs):
        if "rrf_score" in str(statement):
            raise OperationalError("SELECT ...", {}, _PgError("42P01"))
        return MagicMock(scalar=MagicMock(return_value="0"))

    session.execute.side_effect = execute

    with pytest.raises(OperationalError):
        _repo(session).hybrid_search_pages([1], "cola", None)
