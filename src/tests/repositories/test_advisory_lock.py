from unittest.mock import MagicMock

from iatoolkit.repositories.advisory_lock import advisory_lock


def postgres(scalar=True):
    db = MagicMock()
    db.get_dialect.return_value = "postgresql"
    connection = db.get_connection.return_value
    connection.execute.return_value.scalar.return_value = scalar
    return db, connection


def sql(connection):
    return [str(call.args[0]) for call in connection.execute.call_args_list]


def test_the_lock_is_taken_and_released_on_its_own_connection():
    db, connection = postgres()

    with advisory_lock(db, 7, 42) as held:
        assert held is True

    assert sql(connection) == ["SELECT pg_advisory_lock(:namespace, :key)", "SELECT pg_advisory_unlock(:namespace, :key)"]
    connection.close.assert_called_once()


def test_without_waiting_a_lock_held_elsewhere_is_not_released_here():
    db, connection = postgres(scalar=False)

    with advisory_lock(db, 7, 42, wait=False) as held:
        assert held is False

    assert sql(connection) == ["SELECT pg_try_advisory_lock(:namespace, :key)"]
    connection.close.assert_called_once()


def test_the_lock_is_released_when_the_block_fails():
    db, connection = postgres()

    try:
        with advisory_lock(db, 7, 42):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert sql(connection)[-1] == "SELECT pg_advisory_unlock(:namespace, :key)"


def test_sqlite_runs_the_block_as_held():
    db = MagicMock()
    db.get_dialect.return_value = "sqlite"

    with advisory_lock(db, 7, 42) as held:
        assert held is True
    db.get_connection.assert_not_called()
