"""
Settings for server1 — the instance whose Portal every Server attaches to.

Usage, from the `server1/` directory:

    evennia start --settings settings_server1

Cascade:
    settings_server1.py (this file)
        -> settings_common.py
            -> settings.py

This is the only instance that runs a Portal. It is started normally, and it
must be running before server2 or server3 can attach — `evennia server_start`
needs a live Portal at the address it dials.
"""

from server.conf.settings_common import *  # noqa: F401, F403

SERVERNAME = "Server1"

MULTIPLEX_INSTANCE_ID = "server1"

TELNET_PORTS = [4000]
WEBSERVER_PORTS = [(4001, 4005)]
WEBSOCKET_CLIENT_PORT = 4002
SSH_PORTS = [4003]

# This instance's Portal listens here; the other two dial it.
AMP_PORT = MULTIPLEX_AMP_PORT  # noqa: F405
