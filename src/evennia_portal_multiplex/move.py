# SPDX-License-Identifier: BSD-3-Clause
"""Moving a session from one instance to another.

Changing a session's binding alone only points its traffic at a Server that has
never heard of it. This is what makes the destination have a session to receive
it: release at one end, build at the other, and the socket never involved.

Sent directly rather than through ``sessionhandler.disconnect()`` and
``.connect()``. Those also drop the session from the Portal's own handler and
close the transport, which is the one thing a move must not do.

See docs/test-plan.md § MV.
"""

from .binding import bind, connection_for, instance_for
from .routing import sending_to


class NotAttached(Exception):
    """Raised when the destination instance has no live connection.

    Loud rather than a fallback. Falling back would leave the player where they
    were while everything above believed they had moved — and the two would
    only disagree later, somewhere else. `binding.connection_for` falls back
    deliberately for *routing*, because traffic has to go somewhere real; a
    move is a decision and can refuse.
    """


def move_session(registry, session, instance_id):
    """Hand ``session`` from the instance it is on to ``instance_id``.

    Returns ``True`` when the session moved, ``False`` when it was already
    there. Raises `NotAttached` when the destination is not attached.
    """
    from evennia.server.portal.amp import PCONN, PDISCONN

    if instance_for(session) == instance_id:
        return False

    destination = registry.connection_for(instance_id)
    if destination is None:
        raise NotAttached(
            f"{instance_id!r} is not attached. Attached: "
            f"{', '.join(registry.attached()) or 'none'}."
        )

    # Resolved before anything is sent, because rebinding changes the answer.
    origin = connection_for(registry, session)

    # 1. Release. Sent directly rather than through sessionhandler.disconnect(),
    # which would also drop the session from the Portal's handler and close the
    # transport — the one thing a move must not do.
    with sending_to(origin):
        origin.send_AdminPortal2Server(session, operation=PDISCONN)

    # 2. Drop the identity. All three are on SESSION_SYNC_ATTRS and all three
    # are primary keys belonging to the Server being left: carried across, the
    # destination believes the session is already authenticated as whatever
    # account holds that id over there. Cleared *before* the sync data is taken,
    # or the destination receives the old values and this achieves nothing.
    session.uid = None
    session.logged_in = False
    session.puid = None
    bind(session, instance_id)

    # 3. Build. The destination's Server creates a session from this and picks
    # up wherever its own login flow leads.
    with sending_to(destination):
        destination.send_AdminPortal2Server(
            session, operation=PCONN, sessiondata=session.get_sync_data()
        )
    return True
