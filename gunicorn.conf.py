# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# Patch as early as possible: this module is exec'd by the gunicorn master
# before it resolves --worker-class into a class object and before any
# fork(). If that resolution (or anything else in the master) imports ssl/
# urllib3/etc. first, workers inherit an unpatched ssl module via fork and
# the worker class's own monkey.patch_all() (in init_process) runs too late,
# causing infinite recursion in SSLContext.verify_mode
# (https://github.com/gevent/gevent/issues/1016). Patching here, at import
# time of this config file, avoids that race entirely.
from gevent import monkey
monkey.patch_all()


# Makes psycopg2 cooperative under the gevent worker class. psycopg2's C
# extension blocks inside a single libpq call rather than yielding through
# Python's socket/select layer, so monkey.patch_all() alone doesn't cover it.
# psycogreen installs a wait callback so those calls release the greenlet
# while waiting on the DB socket instead of blocking the worker.
def post_fork(server, worker):
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
    server.log.info("Made psycopg2 green")
