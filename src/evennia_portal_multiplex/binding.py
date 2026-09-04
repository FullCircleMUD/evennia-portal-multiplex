# SPDX-License-Identifier: BSD-3-Clause
"""Which instance a session belongs to.

Routing points one send at one instance; this decides which instance that is
for a given session. It is the only per-session state the Portal keeps.

**A name, not a connection.** The Portal deliberately outlives Servers — that
is how ``reload`` works, and why a telnet session survives one. A Server that
restarts comes back on a new AMP connection and the registry replaces its
entry; a session holding the old connection object would be writing into a dead
one, silently. A session holding the name follows the replacement without
noticing. The lookup that costs is a dict access against a message that has
already crossed a socket.

**Unbound means the default instance.** Not "whatever Evennia's global happens
to hold", which names whichever Server attached most recently — so a player
arriving while a second Server starts would be handed to that one. The default
is a decision, not a leftover.

See docs/test-plan.md § SB.
"""

from .config import get_default_instance

#: The attribute a session's instance name is stamped on. Prefixed because a
#: Portal session is an Evennia object and a consumer may stamp their own.
BINDING_KEY = "_multiplex_instance"


def bind(session, instance_id):
    """Record that ``session`` belongs to ``instance_id`` from now on.

    On the session itself rather than in a map the Portal keeps: a session's
    destination lives as long as the session does, and a separate map would be
    one more thing to clean up when one goes away.
    """
    setattr(session, BINDING_KEY, instance_id)


def instance_for(session):
    """The instance a session belongs to — the default unless bound elsewhere."""
    return getattr(session, BINDING_KEY, None) or get_default_instance()


def connection_for(registry, session):
    """The live connection a session's traffic should go down.

    Falls back to the default instance when the bound one is not attached: an
    instance that has stopped should leave its sessions somewhere real rather
    than somewhere nonexistent.

    Resolved through the registry every time rather than cached, so a Server
    that restarts and re-registers is followed. This and `instance_for` are the
    only two answers to "where does this session go", and both come from here —
    two sources agree only for as long as both are maintained.
    """
    return registry.connection_for(instance_for(session)) or (
        registry.default_connection()
    )
