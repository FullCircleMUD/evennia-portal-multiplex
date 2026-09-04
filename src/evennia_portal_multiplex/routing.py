# SPDX-License-Identifier: BSD-3-Clause
"""Pointing one send at one instance.

Every message the Portal sends to a Server goes through
`AMPServerProtocol.data_to_server`, and that method ignores the connection
object it was called on::

    if self.factory.server_connection:
        return self.factory.server_connection.callRemote(...)

So ``connection.send_AdminPortal2Server(...)`` does not send to ``connection``.
It sends to whatever ``factory.server_connection`` holds — and Evennia assigns
that on every inbound admin message, so it names whichever Server spoke most
recently. With one Server that is always right and the indirection is
invisible. With two it is never reliably right.

Routing is therefore not choosing which object to call. It is pointing that one
reference at the instance we mean for the duration of a call, and putting it
back.

Safe because the Portal is a single-threaded reactor: nothing runs between the
swap and the restore. That is a property of the environment rather than of this
code — on a threaded portal the approach would be wrong.

See docs/test-plan.md § RT.
"""

from contextlib import contextmanager


@contextmanager
def sending_to(connection):
    """Point the Portal's outbound reference at ``connection`` for one block.

    ``connection`` of ``None`` — an instance that is not attached — leaves
    Evennia's own choice alone rather than clearing it, so the send behaves as
    it would without this library rather than failing on a null reference.

    Restores on the way out whether or not the block raised. Leaving the
    reference pointed at one instance would send every later unrouted message to
    the wrong Server, with nothing failing visibly.
    """
    if connection is None:
        yield
        return

    factory = connection.factory
    held = factory.server_connection
    factory.server_connection = connection
    try:
        yield
    finally:
        # finally, not just after the yield: a send that raises would otherwise
        # leave the Portal pointed at one instance for good.
        factory.server_connection = held
