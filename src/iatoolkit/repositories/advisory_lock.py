# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""One Postgres advisory lock helper for everything that runs once per key across workers.

A Postgres advisory lock belongs to the *database connection* that took it. An
ORM session hands its connection back to the pool on every commit, so a lock
taken through the session can end up held by a pooled connection nobody owns,
and released (or not) through another one. This helper always takes and
releases the lock on its own dedicated connection, for exactly the `with` block.

On SQLite (tests) there is no advisory lock: the block runs as if it held it.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text


@contextmanager
def advisory_lock(db_manager, namespace: int, key: int, *, wait: bool = True):
    """
    Holds the two-key advisory lock (namespace, key) for the block and yields
    whether it is held: always True when `wait` (it blocks until it gets it);
    with `wait=False`, False when someone else holds it (the block should skip).
    """
    if db_manager.get_dialect() not in ("postgresql", "postgres"):
        yield True
        return
    params = {"namespace": int(namespace), "key": int(key)}
    connection = db_manager.get_connection()
    try:
        if wait:
            connection.execute(text("SELECT pg_advisory_lock(:namespace, :key)"), params)
            held = True
        else:
            held = bool(connection.execute(text("SELECT pg_try_advisory_lock(:namespace, :key)"), params).scalar())
        try:
            yield held
        finally:
            if held:
                connection.execute(text("SELECT pg_advisory_unlock(:namespace, :key)"), params)
    finally:
        connection.close()
