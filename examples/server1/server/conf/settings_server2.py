"""
Settings for server2 — a Server attached to server1's Portal.

Usage, from the `server2/` directory:

    evennia server_start --settings settings_server2

**Only that verb.** AMP_PORT below points at server1's Portal, and the
launcher uses AMP_PORT to reach a Portal as well — so `evennia start`,
`stop`, `reload` or `istart` from this directory all issue instructions to
**server1's** Portal. `istart` in particular stops the Server that Portal
already has, which is server1's. `server_start` exists because it sends
nothing to any Portal at all.

Cascade:
    settings_server2.py (this file)
        -> settings_common.py
            -> settings.py
"""

from server.conf.settings_common import *  # noqa: F401, F403

SERVERNAME = "Server2"

MULTIPLEX_INSTANCE_ID = "server2"

# Never listened on: this instance runs no Portal. They are set, and set
# distinctly, so that starting it fully by accident fails on something
# obvious rather than on three instances silently fighting over port 4000.
TELNET_PORTS = [4020]
WEBSERVER_PORTS = [(4021, 4025)]
WEBSOCKET_CLIENT_PORT = 4022

# server1's Portal, not one of ours. This is what makes this Server attach
# there — and what makes every other launcher verb from this directory
# reach across to server1.
AMP_PORT = MULTIPLEX_AMP_PORT  # noqa: F405
