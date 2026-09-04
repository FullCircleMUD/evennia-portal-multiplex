# SPDX-License-Identifier: BSD-3-Clause
"""Announcing to every player, whichever instance they are on.

A pass-through. The Portal's session handler already has `announce_all`, and
it already reaches every player, because the Portal holds every socket
whichever Server owns the session. What Evennia has no way to do is ask for
it from a Server: the Server-to-Portal admin operations disconnect, sync and
shut down, and none of them speaks.

The Server's own `announce_all` is not the same method. It reaches the
sessions in its own handler, which under several instances is a fraction of
the players — and an admin command written before this library was installed
would quietly become partial.

See docs/test-plan.md § AN.
"""

from twisted.protocols import amp


class MultiplexAnnounce(amp.Command):
    """A Server asking its Portal to say something to every session.

    One argument, no response fields. Who may send one, what it says and
    whether the game wants a prefix on it are the consumer's; this delivers a
    string to every session.
    """

    key = "MultiplexAnnounce"
    arguments = [(b"message", amp.Unicode())]
    errors = {Exception: b"EXCEPTION"}
    response = []


def broadcast_to_all_instances(message):
    """Say ``message`` to every session on this Portal, whichever instance.

    Named for exactly what it does, because `announce` would leave a reader
    guessing who it reaches, and there is no parameter to answer them with.

    **Every session, not every player.** That includes anyone sitting at the
    login screen who has not authenticated — the Portal's `announce_all`
    writes to sockets, not accounts. Right for "the game is going down in five
    minutes"; a consumer wanting only logged-in players wants their own
    Server-side loop instead, on each instance.

    Returns a Deferred that fires when the Portal has done it. The consumer
    passes a string and nothing about AMP — the Portal connection is this
    Server's own, and they should not have to know it exists.
    """
    import evennia

    return evennia.EVENNIA_SERVER_SERVICE.amp_protocol.callRemote(
        MultiplexAnnounce, message=message
    )
