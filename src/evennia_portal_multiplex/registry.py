# SPDX-License-Identifier: BSD-3-Clause
"""Which AMP connection belongs to which instance.

A Portal serving more than one Server needs to tell its connections apart.
Evennia keeps one ``portal.amp_protocol`` and one ``factory.server_connection``,
both naming whichever Server attached or spoke most recently — so with two
Servers attached there is nothing distinguishing them and everything lands on
the last one to speak.

This is that distinction and nothing else: instance id to live connection. It
holds no session state, makes no routing decisions and sends nothing. Whatever
routes a send or moves a session asks it which connection a name resolves to.

See docs/test-plan.md § IR.
"""

from .config import get_default_instance


class InstanceRegistry:
    """The instances currently attached to this Portal.

    A class rather than module state so a test gets a fresh one and the Portal
    gets exactly one, rather than both sharing whatever the import left behind.
    """

    def __init__(self):
        self._connections = {}

    def register(self, instance_id, connection):
        """Record ``connection`` as the way to reach ``instance_id``.

        An instance announces its id on the ``PSYNC`` handshake, so this is
        called from the handler that receives it. Most admin messages carry no
        id at all, and those record nothing.

        Registering an instance already present replaces its entry: a Server
        that restarts reattaches on a new connection, and the old one is dead.
        """
        if not instance_id:
            return
        self._connections[instance_id] = connection

    def forget(self, connection):
        """Drop ``connection``, whichever instance it belonged to.

        By connection rather than by name, because the connection is what is in
        hand when one drops — and because a reconnecting instance can register
        its replacement before the old connection's loss is noticed. Deleting by
        name would then remove the live entry, leaving an attached instance
        unreachable with nothing to say why.

        So the match is on identity: a connection that has already been replaced
        is no longer anybody's, and its late notification does nothing.
        """
        for instance_id, registered in list(self._connections.items()):
            if registered is connection:
                del self._connections[instance_id]

    def connection_for(self, instance_id):
        """The connection reaching ``instance_id``, or ``None`` if not attached.

        ``None`` rather than raising, because the two callers want different
        things from a miss: routing a session falls back, while moving one to a
        named instance must refuse. Neither is served by a single choice made
        here.
        """
        return self._connections.get(instance_id)

    def default_connection(self):
        """The connection reaching the default instance, or ``None``.

        The registry resolves the default instance's id itself rather than making every
        caller carry it. "Where does this go by default" is asked from several
        places, and each of them knowing how to answer it is one more place to
        get it wrong.
        """
        return self.connection_for(get_default_instance())

    def attached(self):
        """Every instance id currently attached, sorted.

        So what a Portal is holding can be inspected — from a log line, a
        diagnostic command, or a test. Sorted because an unstable order makes
        two readings of the same state look like a change.
        """
        return sorted(self._connections)
