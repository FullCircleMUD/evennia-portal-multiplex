# SPDX-License-Identifier: BSD-3-Clause
"""The Server's side of the AMP link — where the startup check runs.

Two classes, because a connection can fail in two places. The protocol covers
a Portal that answered; the factory covers one that was never reached, which
never gets as far as `connectionMade` at all.

`startup.check_registration` decides what an unregistered instance does. This
is the one place it can be called from and have that decision mean anything:
`connectionMade` is what sends the `PSYNC` handshake, so a query issued from it
goes down the same connection immediately after, and AMP delivers in order.
That ordering is what makes a single check trustworthy — see docs/test-plan.md
§ ST for why a timer or a service hook would need retries instead.

Reached through `AMP_CLIENT_PROTOCOL_CLASS`, the documented way, layered over
whatever the setting already named. That setting only works because
`evennia_patch` restored it.

See docs/test-plan.md § CP and § FC.
"""

import os

from twisted.internet import reactor
from twisted.protocols.amp import UnhandledCommand

from .log import portal_multiplex_log
from .query import query_registry
from .startup import check_registration

#: Set by `AppConfig.ready()` to the generated class, so the dotted path in
#: AMP_CLIENT_PROTOCOL_CLASS resolves. Evennia looks the setting up by string.
MultiplexAMPClientProtocol = None


def make_amp_client_protocol(base):
    """Build the client protocol class, subclassing whatever the setting named.

    A factory rather than a module-level class so the base is supplied rather
    than resolved at import time — `AppConfig.ready()` passes the class the
    setting named, and a test passes its own.
    """

    class MultiplexAMPClientProtocol(base):
        """Evennia's client protocol, checking its registration on connect."""

        def connectionMade(self):
            """Send the handshake, then confirm the Portal recorded it.

            `super()` first, and not for tidiness: Evennia's `connectionMade`
            is what sends `PSYNC`. Query before it and the Portal has not been
            told who this is, so the answer is "not registered" every time and
            every Server refuses to start.

            The Deferred is returned rather than dropped, so what happens to
            the answer is reachable — Twisted ignores what `connectionMade`
            gives back.
            """
            super().connectionMade()
            return (
                query_registry(self)
                .addCallback(check_registration)
                .addErrback(self._refuse)
            )

        def _refuse(self, failure):
            """Write down everything known about the failure, then shut down.

            Reached by every failure worth refusing on: this instance missing
            from the answer, a Portal that does not speak the query, a
            connection that dropped mid-question. They all mean the same
            thing — this Server cannot confirm anybody can reach it.

            The log line is not a duplicate of `check_registration`'s. That
            one says what the Portal reported; this one says what is being
            done about it, and covers the failures that never reached it.

            `reactor.stop()` rather than a raise: a raise from here is logged
            by Twisted and the reactor carries on, which leaves a Server
            running unreachable. Stopping brings the services down in order,
            so the line above reaches disk — and the log is the only place the
            reason exists, since the launcher can only report the fact.
            """
            if failure.check(UnhandledCommand):
                reason = (
                    "the Portal did not recognise the registry query, so it "
                    "is not running evennia-portal-multiplex"
                )
            else:
                reason = failure.getErrorMessage()

            portal_multiplex_log(
                f"Not starting: {reason}", level="ERROR"
            )
            # Non-zero, so a process manager reads this as a failure and
            # retries rather than leaving the Server down. After a reboot the
            # cause is often just the Portal not listening yet. On the
            # after-shutdown trigger because a `sys.exit` here raises
            # SystemExit into the Deferred, which swallows it.
            reactor.addSystemEventTrigger(
                "after", "shutdown", lambda: os._exit(1)
            )
            reactor.stop()

    return MultiplexAMPClientProtocol


def make_amp_client_factory(base):
    """Build the client factory class, subclassing whatever is bound.

    Whatever is bound, rather than `PatchedAMPClientFactory` by name: naming
    the patched class would make `evennia_patch` load-bearing, and it exists to
    be deleted. Nothing names this class in settings — Evennia's Server service
    looks it up on its module — so there is no consumer class to preserve
    either.
    """

    class MultiplexAMPClientFactory(base):
        """Evennia's client factory, naming the Portal it could not reach."""

        def clientConnectionFailed(self, connector, reason):
            """Say which Portal, then let Twisted retry as it would have.

            A Portal that was never reached never reaches
            `MultiplexAMPClientProtocol.connectionMade`, so none of the
            startup check is on this path. This is the only place the address
            is in hand.

            Evennia logs this too, without the address. With one Server that
            is enough — there is only one Portal it could mean. With several
            instances and a mistyped `AMP_HOST` it says nothing about which
            one is wrong.

            `super()` last and unconditional: the retry is Twisted's and is
            the right behaviour, since a Portal that is not up yet usually
            will be shortly.
            """
            address = connector.getDestination()
            portal_multiplex_log(
                f"Could not reach the Portal at {address.host}:{address.port} "
                f"({reason}). Retrying.",
                level="ERROR",
            )
            return super().clientConnectionFailed(connector, reason)

    return MultiplexAMPClientFactory
