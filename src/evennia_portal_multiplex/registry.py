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
from .log import portal_multiplex_log


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

        Both the attach and the replacement are logged, and the replacement is
        matched on identity — an instance re-announcing down the connection it
        already holds displaced nobody, and `record_announcement` runs on any
        admin message carrying the name. See docs/test-plan.md § IR.
        """
        if not instance_id:
            return

        held = self._connections.get(instance_id)
        if held is None:
            portal_multiplex_log(f"{instance_id!r} attached.")
        elif held is not connection:
            # Either a Server that restarted before this Portal noticed the old
            # connection drop, or a second Server carrying the same id — which
            # takes the first's sessions and leaves it attached and
            # unreachable. Indistinguishable from here, so this reports it
            # rather than ruling on it.
            portal_multiplex_log(
                f"{instance_id!r} attached on a new connection, replacing the "
                f"one held. Either it restarted, or a second Server is "
                f"configured with this id."
            )

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

        **The name stays, mapped to nothing.** Deleting it would throw away the
        fact that this instance was here, which is what lets routing tell a
        dropped shard from a typo — see docs/test-plan.md § IR.
        """
        for instance_id, registered in list(self._connections.items()):
            if registered is connection:
                self._connections[instance_id] = None

    def connection_for(self, instance_id):
        """The connection reaching ``instance_id``, or ``None`` if not attached.

        ``None`` rather than raising, because the two callers want different
        things from a miss: routing a session falls back, while moving one to a
        named instance must refuse. Neither is served by a single choice made
        here.

        ``None`` covers both a name that dropped and a name never held — see
        `is_known` for the other half.
        """
        return self._connections.get(instance_id)

    def is_known(self, instance_id):
        """Whether this instance has ever attached to this Portal.

        The half `connection_for` cannot answer. A name it has never held is a
        typo or an instance that has not booted; a name that dropped has
        sessions bound to it and belongs somewhere specific. See
        docs/test-plan.md § IR.
        """
        return instance_id in self._connections

    def default_connection(self):
        """The connection reaching the default instance, or ``None``.

        The registry resolves the default instance's id itself rather than making every
        caller carry it. "Where does this go by default" is asked from several
        places, and each of them knowing how to answer it is one more place to
        get it wrong.
        """
        return self.connection_for(get_default_instance())

    def attached(self):
        """Every instance id currently reachable, sorted.

        So what a Portal is holding can be inspected — from a log line, a
        diagnostic command, or a test. Sorted because an unstable order makes
        two readings of the same state look like a change.

        **Reachable, not merely present.** A dropped instance keeps its name in
        the mapping, and both callers — the startup check and the registry
        query — are asking whether an instance can be spoken to. Reporting a
        name with no connection would have a Server confirm its own
        registration against an entry that reaches nobody.
        """
        return sorted(
            instance_id
            for instance_id, connection in self._connections.items()
            if connection is not None
        )
