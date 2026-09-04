# SPDX-License-Identifier: BSD-3-Clause
"""The Portal session handler override, which routes what is said about a session.

Every call site in Evennia's `PortalSessionHandler` reaches for
``EVENNIA_PORTAL_SERVICE.amp_protocol``, and the send behind it goes through
``factory.server_connection`` — one reference, naming whichever Server spoke
most recently. This points it at the instance a session is bound to for the
duration of one call.

Four methods, one rule. ``data_in`` carries what a player types; ``connect``,
``sync`` and ``disconnect`` are the other three things the Portal says about a
session. All four resolve through `connection_for`, so the announce and the
input cannot disagree — unrouted, a session was created on one Server while
everything typed went to another, which had never heard of it.

``get_all_sync_data`` answers the same question from the other end: not "where
does this session go" but "which sessions belong to the instance asking". It
filters on the same binding, so a session cannot be handed to one instance on
a handshake and spoken to on another.

``data_in`` is wrapped, never replaced. Evennia's own applies a character
limit, a command-rate limit, ``clean_senddata`` and a local echo before it
sends; replacing it and sending directly puts a malformed message on the wire,
which surfaces inside the Server's input handling as ``too many values to
unpack`` — nowhere near the cause.

See docs/test-plan.md § IN.
"""

from .binding import connection_for, instance_for
from .routing import sending_to
from .syncing import currently_syncing

#: Set by `AppConfig.ready()` to the generated class, so the dotted path in
#: PORTAL_SESSION_HANDLER_CLASS resolves. Evennia looks the setting up by string.
MultiplexPortalSessionHandler = None


def make_session_handler(base, registry):
    """Build the handler class, subclassing whatever the consumer had.

    ``registry`` is closed over rather than looked up, so the class has one
    obvious source for it and a test can supply its own.
    """

    class MultiplexPortalSessionHandler(base):
        """Routes everything said about a session to the instance holding it."""

        def data_in(self, session, **kwargs):
            """Send this session's input to the instance it belongs to.

            Wrapped, not replaced: Evennia's own applies a character limit, a
            command-rate limit, ``clean_senddata`` and a local echo before it
            sends.
            """
            with sending_to(connection_for(registry, session)):
                return super().data_in(session, **kwargs)

        def connect(self, session):
            """Announce a new session down the connection its input will use.

            Unrouted, this went to whichever Server spoke to the Portal most
            recently while everything typed went to the default — so the
            session was created on one Server and spoken to on another, which
            had never heard of it.

            Evennia's own may announce a *different* session off its
            connection queue than the one passed here. Both are unbound at
            this point and resolve to the same default; a session is only ever
            bound later, by a move.
            """
            with sending_to(connection_for(registry, session)):
                return super().connect(session)

        def sync(self, session):
            """Resend a session's data to the instance holding it.

            Telnet negotiates terminal type, width and compression after the
            session already exists, and calls this when they settle. The
            Server holding the session is the one that needs them.
            """
            with sending_to(connection_for(registry, session)):
                return super().sync(session)

        def disconnect(self, session):
            """Tell the instance actually holding the session that it is going.

            Not the last Server to speak, which never had it — and which would
            be asked to drop a session it does not have while the one that
            does keeps it.
            """
            with sending_to(connection_for(registry, session)):
                return super().disconnect(session)

        def get_all_sync_data(self):
            """The sessions to hand over, filtered to whoever is syncing.

            This builds the payload of a `PSYNC` reply, and Evennia's own
            answers with every session the Portal holds. Under several
            instances each attaching Server is then given the others'
            sessions, builds a `ServerSession` for each, and attaches any
            carrying a ``uid`` to *its own* account of that number.

            Filtered on the session's binding — the same answer `connect` and
            `data_in` route on, so a session cannot be synced to one instance
            and spoken to on another. A session bound to an instance that is
            not attached syncs to nobody, which is right: it belongs somewhere
            that is not listening.

            Outside a sync this answers with everything. The method has other
            callers, and `currently_syncing` returning nothing means "not a
            `PSYNC` reply", not "an instance holding no sessions".
            """
            instance_id = currently_syncing()
            if instance_id is None:
                return super().get_all_sync_data()

            return {
                sessid: session.get_sync_data()
                for sessid, session in self.items()
                if instance_for(session) == instance_id
            }

        def disconnect_all(self):
            """Tell every attached instance to drop everything it holds.

            A broadcast rather than a routed send: this is one message meaning
            "drop all your sessions", and the Portal sends it when it shuts
            down. Sent once, the other instances carry on believing their
            players are still connected — characters standing in rooms with
            nobody at the keyboard.

            **`super()` sends one more, deliberately.** Evennia welds the send
            to the teardown: the callback that closes the Portal's own sockets
            is attached to that send's Deferred. Skipping it would leave every
            socket open, and reimplementing it would mean carrying a copy of
            the watchdog that stops `disconnect` deleting sessions mid-loop —
            a copy that goes stale silently the first time Evennia changes
            theirs. So the last message lands on a Server that has already
            dropped everything and finds nothing to do.
            """
            from evennia.server.portal.amp import DUMMYSESSION, PDISCONNALL

            for instance_id in registry.attached():
                connection = registry.connection_for(instance_id)
                with sending_to(connection):
                    connection.send_AdminPortal2Server(
                        DUMMYSESSION, operation=PDISCONNALL
                    )
            return super().disconnect_all()

    return MultiplexPortalSessionHandler
