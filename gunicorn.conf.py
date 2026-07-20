# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# Makes psycopg2 cooperative under the gevent worker class. gevent's
# monkey.patch_all() (applied automatically by gunicorn's gevent worker in
# init_process) does not cover psycopg2's C extension, since psycopg2 blocks
# inside a single libpq call rather than yielding through Python's socket/
# select layer. psycogreen installs a wait callback so those calls release
# the greenlet while waiting on the DB socket instead of blocking the worker.
def post_fork(server, worker):
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
    server.log.info("Made psycopg2 green")
