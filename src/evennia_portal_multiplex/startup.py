# SPDX-License-Identifier: BSD-3-Clause
"""Refusing to start when this instance is not registered.

`query.am_i_registered` answers whether. This decides what to do about it, and
the answer is: nothing, or raise.

**One check, no retries.** The two failures are already covered elsewhere. If
the connection is down there is nothing to query, and `AMPClientFactory` is a
Twisted ``ReconnectingClientFactory`` already redialling with backoff — a retry
here would be a worse copy of that. If the connection is up and this instance
is not in the list, the handshake went down that same connection *before* the
query, AMP delivers in order, and the Portal records synchronously. So the
answer cannot mean "not yet"; it means something is broken, and asking again
will not change it.

That reasoning depends entirely on where this is called from. It has to be on
the same AMP connection and immediately after the handshake — a check from a
timer or a service hook would reintroduce the race, and with it the need for
the retries this deliberately does not have.

See docs/test-plan.md § ST.
"""

from .config import get_instance_id
from .log import portal_multiplex_log
from .query import am_i_registered


class NotRegistered(Exception):
    """This instance is not in the Portal's registry.

    Raised rather than logged and shrugged off. A Server nobody can reach is
    not started in any useful sense, and failing at boot beats running
    unreachable while somebody works out why players never arrive.
    """


def check_registration(attached):
    """Return quietly if this instance is registered; raise if it is not.

    The message carries this instance's name and what the Portal actually
    reported, because those two side by side are usually the whole diagnosis —
    a name that does not match what was expected, or a Portal holding nobody.
    Logged as well as raised: the exception may be caught by something that
    reports it differently, and the line should survive that.
    """
    if am_i_registered(attached):
        return

    me = get_instance_id()
    reported = ", ".join(attached) if attached else "nothing"
    message = (
        f"{me!r} is not registered with its Portal. The Portal reports "
        f"{reported} attached. This instance cannot be reached, so it is not "
        f"finishing startup."
    )
    portal_multiplex_log(message, level="ERROR")
    raise NotRegistered(message)
