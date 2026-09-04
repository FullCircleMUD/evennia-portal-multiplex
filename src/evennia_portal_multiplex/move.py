# SPDX-License-Identifier: BSD-3-Clause
"""Moving a session from one instance to another.

Changing a session's binding alone only points its traffic at a Server that has
never heard of it. This is what makes the destination have a session to receive
it: release at one end, build at the other, and the socket never involved.

Sent directly rather than through ``sessionhandler.disconnect()`` and
``.connect()``. Those also drop the session from the Portal's own handler and
close the transport, which is the one thing a move must not do.

**Release first, then build.** Building before releasing would avoid stranding
anyone, but it leaves a window where the session exists on two Servers at once,
and a release that then failed would leave a ghost standing in the origin's
world. Releasing first trades that for a stranded player, which the rollback
recovers.

See docs/test-plan.md § MV.
"""

from twisted.protocols import amp

from .binding import bind, connection_for, instance_for
from .log import portal_multiplex_log
from .routing import sending_to


#: What a move resolves to. The names describe what happened to the session,
#: not what this library did about it — a destination that would not take the
#: session **rejected** it, and that we then put the session back is
#: bookkeeping the consumer has no use for.
MOVED = "moved"
ALREADY_THERE = "already_there"
NOT_ATTACHED = "not_attached"
REJECTED = "rejected"
STRANDED = "stranded"
NO_SUCH_SESSION = "no_such_session"

#: Where a payload lands on the session. `server_data` is on
#: ``SESSION_SYNC_ATTRS``, so what is put there crosses with the ``PCONN``.
#: Prefixed because the dict is Evennia's and a consumer keeps their own keys
#: in it too.
PAYLOAD_KEY = "multiplex_payload"


def send_session(session, destination, payload=None):
    """Ask this Server's Portal to hand ``session`` to ``destination``.

    The consumer's whole API. Returns a Deferred resolving to
    ``(moved, outcome)`` — see the outcome constants above.

    **One session.** A move hands one socket from one Server to another. An
    account can hold several sessions, and whether they all follow is a game
    decision: a consumer wanting to move an account loops its sessions and
    decides for itself what to do when the third comes back refused after the
    first two moved.

    ``payload`` is an optional dict carried to the destination — which archive
    to rebuild the session from, say. It travels as JSON and lands in the
    session's ``server_data``, which the sync data takes across. **Nothing of
    ours reads it back:** the session at the destination is built by Evennia
    from that sync data, so the consumer's own code is the first thing of
    anyone's to see it, and calls `json.loads` itself. JSON types only.

    It is not a ticket. A moved session never leaves the Portal, so there is no
    untrusted hop to authenticate across — the destination trusts the
    instruction because it came from the Portal it is attached to.
    """
    import json

    import evennia

    return evennia.EVENNIA_SERVER_SERVICE.amp_protocol.callRemote(
        MultiplexMoveSession,
        sessid=session.sessid,
        destination=destination,
        payload=json.dumps(payload) if payload is not None else None,
    ).addCallback(lambda reply: (reply["moved"], reply["outcome"]))

class MultiplexMoveSession(amp.Command):
    """A Server asking its Portal to hand one of its sessions elsewhere.

    `move_session` runs on the Portal, because the Portal holds the sessions
    and the connections. Deciding one should move is the game's, and the game
    runs on a Server. This is what crosses between them.

    One class, imported by both processes: AMP matches on the key, so the
    Portal's responder and the Server's `callRemote` need the same definition
    rather than two that agree.

    The outcome travels as two declared fields rather than a pickled blob, so
    a Server reading it is reading types AMP checked.
    """

    key = "MultiplexMoveSession"
    arguments = [
        (b"sessid", amp.Integer()),
        (b"destination", amp.Unicode()),
        # Optional because most moves carry nothing. Opaque to this library:
        # a consumer's JSON, which their own code reads at the far end.
        (b"payload", amp.Unicode(optional=True)),
    ]
    response = [
        (b"moved", amp.Boolean()),
        (b"outcome", amp.Unicode()),
    ]


#: The fields cleared on the way out and restored on the way back. All three
#: are on ``SESSION_SYNC_ATTRS`` and all three are primary keys belonging to
#: the Server being left: carried across, the destination believes the session
#: is already authenticated as whatever account holds that id over there.
IDENTITY = {"uid": None, "logged_in": False, "puid": None}


def move_session(registry, session, instance_id):
    """Hand ``session`` from the instance it is on to ``instance_id``.

    Returns a Deferred resolving to ``(moved, outcome)``. ``moved`` is true for
    `MOVED` and nothing else — including `ALREADY_THERE`, which is a consumer
    asking to send a session where it already is, and so a bug in their logic
    worth surfacing rather than a quiet success.

    Asynchronous because the reply to each send is what says whether the far
    end took the message, and that is the only way to know a build failed.
    """
    from twisted.internet import defer

    from evennia.server.portal.amp import PDISCONN

    if instance_for(session) == instance_id:
        return defer.succeed((False, ALREADY_THERE))

    # Everything that can refuse is checked before anything is sent. A reason
    # found after the origin has let go cannot leave the session where it was,
    # because it is not there any more.
    destination = registry.connection_for(instance_id)
    if destination is None:
        portal_multiplex_log(
            f"Not moving a session to {instance_id!r}: not attached. "
            f"Attached: {', '.join(registry.attached()) or 'none'}."
        )
        return defer.succeed((False, NOT_ATTACHED))

    # Both resolved before anything is sent, because rebinding changes the
    # answer and the identity is about to be wiped.
    origin = connection_for(registry, session)
    origin_instance = instance_for(session)
    identity = {field: getattr(session, field) for field in IDENTITY}

    # Release. Sent directly rather than through sessionhandler.disconnect(),
    # which would also drop the session from the Portal's handler and close the
    # transport — the one thing a move must not do.
    with sending_to(origin):
        origin.send_AdminPortal2Server(session, operation=PDISCONN)

    built = _build_at(session, destination, instance_id, IDENTITY)
    built.addCallback(lambda _result: (True, MOVED))
    built.addErrback(
        lambda failure: _put_back(
            session, origin, origin_instance, identity, failure
        )
    )
    return built


def _build_at(session, connection, instance_id, identity):
    """Bind the session to ``instance_id`` and have that Server build one.

    The one step both directions share. ``identity`` is what the session's
    identity fields are set to first — wiped moving away, the captured values
    coming back — and it is applied *before* the sync data is taken, or the
    far end receives the old values and the setting achieves nothing.
    """
    from evennia.server.portal.amp import PCONN

    for field, value in identity.items():
        setattr(session, field, value)
    bind(session, instance_id)

    with sending_to(connection):
        return connection.send_AdminPortal2Server(
            session, operation=PCONN, sessiondata=session.get_sync_data()
        )


def _put_back(session, origin, origin_instance, identity, failure):
    """Rebuild the session on the instance it came from.

    The origin has already let go by the time a build can fail, so a session
    left alone is a player connected to a Portal and on no Server at all.

    Nothing is sent to the destination: it never built anything to release.

    This is Evennia's own reload, applied to one session — when a Server
    reconnects, the Portal hands back every session's sync data and they come
    back logged in and re-puppeted.
    """
    portal_multiplex_log(
        f"{origin_instance!r} released a session the destination would not "
        f"take ({failure.getErrorMessage()}). Putting it back."
    )

    restored = _build_at(session, origin, origin_instance, identity)
    restored.addCallback(lambda _result: (False, REJECTED))
    restored.addErrback(lambda origin_failure: _stranded(origin_failure))
    return restored


def _stranded(failure):
    """Both ends refused, and there is nowhere left to put the session.

    Logged rather than retried: both Servers unreachable in the same instant is
    a different failure, and nothing can be done about it here. The player
    reconnects.
    """
    portal_multiplex_log(
        f"A session is on no instance: released by its origin, refused by the "
        f"destination, and the origin would not take it back "
        f"({failure.getErrorMessage()}). The player has to reconnect.",
        level="ERROR",
    )
    return (False, STRANDED)
