# SPDX-License-Identifier: BSD-3-Clause
"""A local patch for an Evennia bug. Delete this file when it is fixed upstream.

``AMPClientFactory.__init__`` resolves ``settings.AMP_CLIENT_PROTOCOL_CLASS``
into ``self.protocol`` and then never reads it — ``buildProtocol`` names
``AMPServerClientProtocol`` directly. Pointing that setting at a subclass has
no effect, and nothing is raised or logged. The Portal-side twin in
``amp_server.py`` does use ``self.protocol()``, which is what makes this a slip
rather than a decision.

Reproduced on 6.1.0 and present on ``main``. Reported upstream.

**This restores the setting rather than routing around it**, which is what
makes it removable. The library points ``AMP_CLIENT_PROTOCOL_CLASS`` at its own
protocol class the ordinary way, whether or not this patch is installed. On a
fixed Evennia, deleting `install()` and its one call site changes nothing:
Evennia honours the setting we were already setting and builds the same class.
A patch that replaced the protocol class directly would have skipped the
setting, and removing it would have been a behaviour change.

PT-04 is a canary — it asserts the bug is still there, so it fails when Evennia
is fixed. That failure is the signal to delete this file.

See docs/test-plan.md § PT.
"""

from evennia.server import amp_client


def make_patched_factory(base):
    """Build the factory class, subclassing whatever Evennia's is.

    A factory rather than a module-level class so a test can supply its own
    base, and so the patch is built from whatever is actually installed rather
    than from an import taken at load time.
    """

    class PatchedAMPClientFactory(base):
        """Evennia's factory, with `buildProtocol` reading `self.protocol`."""

        def buildProtocol(self, addr):
            """Evennia's, with the one line that reads the setting.

            Mirrors the original exactly otherwise: the reconnect delay has to
            be reset or a flapping link stops backing off, and the protocol
            has to be held on the service or the Server has nothing to send
            on.
            """
            self.resetDelay()
            self.server.amp_protocol = self.protocol()
            self.server.amp_protocol.factory = self
            return self.server.amp_protocol

    return PatchedAMPClientFactory


def install():
    """Replace the factory Evennia's Server service will construct.

    ``service.py`` looks up ``amp_client.AMPClientFactory`` at call time, so
    rebinding the module attribute before the service starts is enough.

    **Delete this call from `AppConfig.ready()` when the upstream fix lands.**
    """
    amp_client.AMPClientFactory = make_patched_factory(amp_client.AMPClientFactory)
