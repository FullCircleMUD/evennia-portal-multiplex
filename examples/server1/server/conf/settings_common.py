"""
Common configuration shared by every instance in the demo.

One source tree, three settings files. `server1/` holds all the code and all
four settings files; `server2/` and `server3/` symlink back to it and own only
their `server/` directory. Identity is config, never a separate checkout.

Cascade:
    settings_server1.py / settings_server2.py / settings_server3.py
        -> settings_common.py (this file)
            -> settings.py
                -> secret_settings.py

Anything every instance needs goes here, so there is one place to change it
and no way for the three to drift. Anything that differs — a name, a set of
ports — goes in the per-instance file and nowhere else.

What each instance owns vs shares:

    evennia.db3      per instance   its own world, its own Limbo, its own #1
    logs/            per instance   so a log line belongs to one instance
    everything else  shared         symlinks back to server1/

This library shares no databases at all. It carries no tables of its own and
depends on nothing that does, so there is no equivalent of the archive or bus
files the scaling demo symlinks between instances.

`evennia.db3` and `logs/` need no configuration: Evennia derives both from
GAME_DIR, which is `os.getcwd()`, and each instance is started from its own
directory.
"""

import sys

# ── macOS only: use a bundled, non-Apple SQLite build ────────────────
#
# macOS ships /usr/lib/libsqlite3.dylib, which drives sqlite3_initialize()
# through libdispatch. libdispatch does not survive fork(), so once any
# SQLite connection has been opened, a daemonizing (forking) start deadlocks
# on the child's first SQLite call — silently, with no error or timeout.
# `evennia start` forks on Unix; `--nodaemon` and Windows do not, which is
# why this only bites daemonized starts on macOS.
#
# sqlean.py ships its own statically-linked SQLite, so Apple's library is
# never loaded. The swap must happen before anything imports sqlite3.
#
# Scoped to darwin so Linux keeps the stdlib module and this whole block is
# dead code there. Also a no-op if sqlean isn't installed, so a Mac without
# it still runs — just not daemonized.
if sys.platform == "darwin":
    try:
        import sqlean
        import sqlean.dbapi2

        # sqlean's DBAPI predates a couple of things Django 6's sqlite3
        # backend expects. Its Connection is an immutable C type, so the
        # additions go on a subclass installed via connect(factory=...).
        class _MultiplexConnection(sqlean.dbapi2.Connection):
            def getlimit(self, category):
                # Django uses this only to size bulk_create batches.
                # 999 is SQLite's conservative historical default.
                return 999

        _sqlean_connect = sqlean.dbapi2.connect

        def _connect(*args, **kwargs):
            kwargs.setdefault("factory", _MultiplexConnection)
            return _sqlean_connect(*args, **kwargs)

        sqlean.dbapi2.connect = _connect
        sqlean.connect = _connect
        sqlean.SQLITE_LIMIT_VARIABLE_NUMBER = 9
        sqlean.dbapi2.SQLITE_LIMIT_VARIABLE_NUMBER = 9

        sys.modules["sqlite3"] = sqlean
        sys.modules["sqlite3.dbapi2"] = sqlean.dbapi2
    except ImportError:
        pass

from server.conf.settings import *  # noqa: F401, F403, E402

######################################################################
# Apps
######################################################################

INSTALLED_APPS = list(INSTALLED_APPS) + [  # noqa: F405
    "evennia_portal_multiplex",
]

######################################################################
# Which instance's Portal everything attaches to
######################################################################
#
# One Portal serves all three Servers, and it is server1's. That single fact
# decides most of the per-instance settings below it:
#
#   - server1 runs a Portal and a Server, started normally.
#   - server2 and server3 run a Server only, started with
#     `evennia server_start`, and their AMP_PORT points at server1's Portal
#     rather than at one of their own.
#
# Declared here so the name exists once and the three cannot disagree about
# who they are attaching to.
MULTIPLEX_DEFAULT_INSTANCE = "server1"

# The AMP port server1's Portal listens on, and therefore the port the other
# two dial. One constant, used three times, because a mismatch means a Server
# that never attaches and a registry that never hears of it.
MULTIPLEX_AMP_PORT = 4006

######################################################################
# SSH
######################################################################
#
# Off in Evennia by default. On here because a session should move whatever
# protocol a player arrived on, and SSH is one of the ways in — so the demo
# offers it to have something to prove that against.
#
# Needs `bcrypt` and `pyasn1`, which Evennia does not pull in; see
# requirements.txt. The host keypair is Evennia's own, generated under
# `server/` on first start.
#
# Declared here so the three agree about what this deployment offers. The
# port each instance would listen on is per-instance, like every other port.
SSH_ENABLED = True

######################################################################
# The launcher verb that starts a Server without a Portal
######################################################################
#
# Declared for all three even though only server2 and server3 use it: one
# place to change, and no way for the two that need it to disagree. server1
# starts normally and never reaches for the verb.
#
# Without this, `evennia server_start` does not resolve. It fails silently —
# the verb falls through to Django and is reported as an unknown command.
EXTRA_LAUNCHER_COMMANDS = {
    "server_start": "evennia_portal_multiplex.launcher.server_start",
}
