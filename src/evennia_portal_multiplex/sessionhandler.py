# SPDX-License-Identifier: BSD-3-Clause
"""The Portal session handler override, which routes a session's input.

Every call site in Evennia's `PortalSessionHandler` reaches for
``EVENNIA_PORTAL_SERVICE.amp_protocol``, and the send behind it goes through
``factory.server_connection`` — one reference, naming whichever Server spoke
most recently. This points it at the instance a session is bound to for the
duration of one call.

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
        """Routes a session's input to the instance it belongs to."""

        def data_in(self, session, **kwargs):
            """Send this session's input to the instance it belongs to.

            Wrapped, not replaced: Evennia's own applies a character limit, a
            command-rate limit, ``clean_senddata`` and a local echo before it
            sends.
            """
            with sending_to(connection_for(registry, session)):
                return super().data_in(session, **kwargs)

    return MultiplexPortalSessionHandler
