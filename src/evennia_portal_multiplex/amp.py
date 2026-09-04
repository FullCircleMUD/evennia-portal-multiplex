# SPDX-License-Identifier: BSD-3-Clause
"""The AMP responder that records which instance a connection belongs to.

The Portal side of the announcement. A Server names itself in the `info_dict`
it sends with its ``PSYNC`` handshake; this hears that message and writes the
name into the registry against the connection it arrived on. It also drops a
connection from the registry when the connection is lost.

**An AMP responder must be re-registered, not overridden.** Twisted builds
``_commandDispatch`` as a class attribute at class-creation time, mapping each
command to the function its ``@Command.responder`` decorator was applied to. A
subclass inherits that table, and unless it applies the decorator itself the
entry still points at the *parent's* function. An ordinary override then
compiles, installs, sits on the instance and is never called — nothing raised,
nothing logged. AR-07 exists to catch exactly that.

See docs/test-plan.md § AR.
"""

from .announce import MultiplexAnnounce
from .log import portal_multiplex_log
from .move import (
    NO_SUCH_SESSION,
    PAYLOAD_KEY,
    MultiplexMoveSession,
    move_session,
)
from .query import MultiplexQueryRegistry
from .services import INSTANCE_KEY


def record_announcement(registry, connection, message):
    """Register ``connection`` if this admin message named an instance.

    Split out of the responder because it is plain data handling and testable
    as such, while the responder itself is awkward to reach. Most admin
    messages carry no ``info_dict`` at all.

    No guard against an absent name: `InstanceRegistry.register` already
    ignores one (IR-03), and a second check here would be a second place to
    disagree about what counts as absent.
    """
    _sessid, kwargs = message
    name = (kwargs.get("info_dict") or {}).get(INSTANCE_KEY)
    registry.register(name, connection)


def make_amp_protocol(base, registry):
    """Build the AMP protocol class, subclassing whatever the Portal builds.

    ``registry`` is closed over rather than looked up, so the class has one
    obvious source for it and a test can supply its own.
    """

    from evennia.server.portal import amp as evennia_amp

    class MultiplexAMPServerProtocol(base):
        """Records an instance against its connection, and forgets it on loss."""

        @evennia_amp.AdminServer2Portal.responder
        @evennia_amp.catch_traceback
        def portal_receive_adminserver2portal(self, packed_data):
            """Let Evennia handle the message, then note who sent it.

            The decorators are the point. Without them this method is on the
            instance and never called: Twisted's dispatch table, built when the
            class was created, would still name the base's function.

            `super()` first, so Evennia's own handling — including the
            operations that mean "the Server that just spoke" — has resolved
            before anything here looks at the message.
            """
            result = super().portal_receive_adminserver2portal(packed_data)
            record_announcement(registry, self, self.data_in(packed_data))
            return result

        @MultiplexQueryRegistry.responder
        @evennia_amp.catch_traceback
        def portal_receive_query_registry(self):
            """Answer which instances are attached.

            The registry is read here rather than captured when this class was
            built: a copy would answer correctly once and be stale for the
            life of the process.

            The decorator is what makes this reachable. Without it the method
            sits on the class and AMP, routing by its own table, never calls
            it — nothing raised, the query simply unhandled. See QY-07.
            """
            return {"attached": evennia_amp.dumps(registry.attached())}

        @MultiplexMoveSession.responder
        @evennia_amp.catch_traceback
        def portal_receive_move_session(self, sessid, destination, payload=None):
            """Move the session this id names, and answer with the outcome.

            The Portal holds the sessions and the connections, so the move
            happens here; deciding it should happen is the game's, and the
            game runs on a Server.

            An id the Portal does not hold is an outcome, not an error: the
            usual cause is a player disconnecting between the game deciding to
            move them and this arriving. Logged here as well, because this is
            the only side that knows which ids it does have.

            The move's Deferred is returned rather than waited on. AMP waits
            on a Deferred a responder gives back, so the reply carries the
            outcome instead of an acknowledgement that the message arrived.
            """
            import evennia

            session = evennia.PORTAL_SESSION_HANDLER.get(sessid)
            if session is None:
                portal_multiplex_log(
                    f"Asked to move session {sessid}, which this Portal does "
                    f"not hold. Holding: "
                    f"{', '.join(str(held) for held in evennia.PORTAL_SESSION_HANDLER) or 'nothing'}."
                )
                return {"moved": False, "outcome": NO_SUCH_SESSION}

            # Stamped before the move, because the move takes the sync data —
            # set afterwards, the destination would already have been sent a
            # copy without it. Stored exactly as it arrived: nothing of ours
            # runs on the destination to decode it.
            if payload is not None:
                session.server_data[PAYLOAD_KEY] = payload

            return move_session(registry, session, destination).addCallback(
                lambda outcome: {"moved": outcome[0], "outcome": outcome[1]}
            )

        @MultiplexAnnounce.responder
        @evennia_amp.catch_traceback
        def portal_receive_announce(self, message):
            """Say it to every session this Portal holds.

            A pass-through to the Portal's own `announce_all`, which already
            reaches every player whichever Server owns their session. The
            Server's method of the same name reaches only its own handler's
            sessions.
            """
            import evennia

            evennia.PORTAL_SESSION_HANDLER.announce_all(message)
            return {}

        def connectionLost(self, reason):
            """Drop this connection from the registry, then tear down as usual.

            By connection rather than by name — see `InstanceRegistry.forget`.
            """
            registry.forget(self)
            return super().connectionLost(reason)

    return MultiplexAMPServerProtocol
