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

        def connectionLost(self, reason):
            """Drop this connection from the registry, then tear down as usual.

            By connection rather than by name — see `InstanceRegistry.forget`.
            """
            registry.forget(self)
            return super().connectionLost(reason)

    return MultiplexAMPServerProtocol
