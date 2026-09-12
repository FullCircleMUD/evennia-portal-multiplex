# SPDX-License-Identifier: BSD-3-Clause
"""Waiting for an instance that dropped, and deciding when to stop waiting.

A command arrives for a session whose instance has a registry entry but no
connection against it. That instance was here and is not now, so the command has
nowhere it belongs — and the default is not a substitute, because a Server never
told about a session discards what it is sent without a word.

**A dropped connection does not mean the Server is gone.** Evennia's
``AMPClientFactory`` is a ``ReconnectingClientFactory`` that redials on its own,
at one second growing to a ceiling of ten, indefinitely. A reload, a crash under
a process manager or a network blip is back inside that; only a dead machine
stays gone. So the answer is to wait a little rather than act at once.

The Portal cannot see those redial attempts — they happen at the other end — so
it watches its own registry entry, which is what actually tells it whether the
instance is reachable.

**One wait per instance.** A shard with forty players drops once, not forty
times, and every session bound to it is told together and moved together.

See docs/test-plan.md § RC.
"""

from .binding import instance_for
from .config import (
    RECONNECT_LOST_MESSAGE,
    RECONNECT_NOWHERE_MESSAGE,
    RECONNECT_POLL_SECONDS,
    RECONNECT_RESTORED_MESSAGE,
    RECONNECT_TIMED_OUT_MESSAGE,
    RECONNECT_WAIT_SECONDS,
    get_default_instance,
)
from .log import portal_multiplex_log
from .move import move_session


class ReconnectWatch:
    """The waits currently running, one per instance that dropped.

    ``sessions`` is a callable returning every session the Portal holds, rather
    than the handler itself: the watch only ever asks "who is on this instance
    right now", and a callable keeps it from reaching into anything else. It is
    also what makes the answer current — a session that disconnects mid-wait is
    simply not in the next answer.
    """

    def __init__(self, registry, sessions):
        self._registry = registry
        self._sessions = sessions
        #: instance id -> (LoopingCall, polls so far)
        self._waits = {}

    def command_arrived(self, session):
        """Note a command for a session whose instance has dropped.

        Starts a wait for that instance if none is running, and tells its
        sessions their connection is lost. A later command during the same wait
        joins it rather than starting another, and says nothing further — they
        have already been told once.
        """
        instance_id = instance_for(session)
        if instance_id in self._waits:
            return

        waiting = self._sessions_on(instance_id)
        portal_multiplex_log(
            f"{instance_id!r} has dropped and {len(waiting)} session(s) are "
            f"waiting for it. Holding them for "
            f"{RECONNECT_WAIT_SECONDS}s before moving them to the default."
        )
        self._tell(waiting, RECONNECT_LOST_MESSAGE)

        # Imported here, not at module scope: the reactor's presence is a
        # property of the running Portal, and this module is imported while
        # Django is still building its app registry.
        from twisted.internet.task import LoopingCall

        call = LoopingCall(self._poll, instance_id)
        self._waits[instance_id] = [call, 0]
        # `now=False` because the entry cannot have changed in the same tick
        # the command arrived on — the first look belongs one interval later.
        call.start(RECONNECT_POLL_SECONDS, now=False)

    def waiting_for(self, instance_id):
        """Whether a wait is currently running for ``instance_id``."""
        return instance_id in self._waits

    def _poll(self, instance_id):
        """One look at the registry entry — reattached, timed out, or neither."""
        if self._registry.connection_for(instance_id) is not None:
            self._finish(instance_id, RECONNECT_RESTORED_MESSAGE)
            portal_multiplex_log(f"{instance_id!r} is back; its sessions resume.")
            return

        wait = self._waits.get(instance_id)
        if wait is None:  # pragma: no cover - the call is stopped before this
            return
        wait[1] += 1
        if wait[1] * RECONNECT_POLL_SECONDS < RECONNECT_WAIT_SECONDS:
            return

        moving = self._finish(instance_id, RECONNECT_TIMED_OUT_MESSAGE)
        default = get_default_instance()
        portal_multiplex_log(
            f"{instance_id!r} did not come back within "
            f"{RECONNECT_WAIT_SECONDS}s. Moving {len(moving)} session(s) to "
            f"{default!r}.",
            level="WARN",
        )
        for session in moving:
            self._move_or_disconnect(session, default)

    def _move_or_disconnect(self, session, default):
        """Move one session to the default, or give up on it and close it.

        One session at a time, each with its own handling: a failure raised on
        one player's behalf must not abandon everybody after them in the batch.

        Giving up is the end of it. Their own instance is gone and the default
        cannot build them a session, so the game is down rather than one shard
        of it — there is nothing left to fall back to, so they are told and
        disconnected and whoever restarts the game brings them back.
        """

        def gave_up(reason):
            portal_multiplex_log(
                f"Could not move a session to {default!r} ({reason}). "
                f"Disconnecting it — there is nowhere left to put it.",
                level="ERROR",
            )
            self._tell([session], RECONNECT_NOWHERE_MESSAGE)
            session.disconnect()

        def landed(result):
            moved, outcome = result
            if not moved:
                gave_up(outcome)

        try:
            moving = move_session(self._registry, session, default)
        except Exception as error:  # the move could not even be started
            gave_up(error)
            return

        moving.addCallbacks(landed, lambda failure: gave_up(failure.value))

    def _finish(self, instance_id, message):
        """Stop the wait, tell its sessions the outcome, and return them."""
        call, _polls = self._waits.pop(instance_id)
        if call.running:
            call.stop()
        sessions = self._sessions_on(instance_id)
        self._tell(sessions, message)
        return sessions

    def _sessions_on(self, instance_id):
        """Every session the Portal currently holds that is bound there."""
        return [
            session
            for session in self._sessions()
            if instance_for(session) == instance_id
        ]

    def _tell(self, sessions, message):
        """Say one line to each session. Never about our own mechanism.

        A Portal session is a protocol — `TelnetProtocol` and friends — not a
        Server-side object, so it has no ``msg()``. `data_out` is the outbound
        path, and ``text=[[message], {}]`` is the shape Evennia's own
        `announce_all` builds. Writing to the Portal's own sockets involves no
        Server, which is the whole reason this can be said at all when the
        session's Server has gone.
        """
        for session in sessions:
            session.data_out(text=[[message], {}])
