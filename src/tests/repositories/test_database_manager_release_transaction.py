# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import declarative_base

from iatoolkit.repositories.database_manager import DatabaseManager

Base = declarative_base()


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    body = Column(String)


def _manager(tmp_path) -> DatabaseManager:
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'release.db'}", register_pgvector=False)
    Base.metadata.create_all(manager.engine)
    return manager


def test_release_without_a_session_is_a_no_op(tmp_path):
    manager = _manager(tmp_path)

    assert manager.release_idle_transaction() is False


def test_release_ends_a_read_only_transaction(tmp_path):
    # A read opens a transaction that holds its connection until the next
    # commit - for the whole of an LLM call, before this existed.
    manager = _manager(tmp_path)
    session = manager.get_session()
    session.execute(text("SELECT 1"))
    assert session().in_transaction()

    assert manager.release_idle_transaction() is True
    assert not session().in_transaction()


def test_release_keeps_loaded_objects_usable(tmp_path):
    manager = _manager(tmp_path)
    session = manager.get_session()
    session.add(Note(id=1, body="kept"))
    session.commit()
    note = session.get(Note, 1)

    assert manager.release_idle_transaction() is True
    # A rollback would have expired it; the commit keeps its loaded state.
    assert "body" in note.__dict__
    assert note.body == "kept"


def test_release_leaves_pending_changes_to_the_caller(tmp_path):
    manager = _manager(tmp_path)
    session = manager.get_session()
    session.add(Note(id=2, body="pending"))

    assert manager.release_idle_transaction() is False
    assert session().in_transaction()
    assert session.new

    session.rollback()
    manager.remove_session()
    assert manager.get_session().get(Note, 2) is None
