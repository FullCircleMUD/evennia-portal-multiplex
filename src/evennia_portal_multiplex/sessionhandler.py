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

``data_in`` is wrapped, never replaced. Evennia's own applies a character
limit, a command-rate limit, ``clean_senddata`` and a local echo before it
sends; replacing it and sending directly puts a malformed message on the wire,
which surfaces inside the Server's input handling as ``too many values to
unpack`` — nowhere near the cause.

See docs/test-plan.md § IN.
"""

from .binding import connection_for
from .routing import sending_to

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

    return MultiplexPortalSessionHandler
