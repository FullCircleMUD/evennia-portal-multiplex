# SPDX-License-Identifier: BSD-3-Clause
"""Overrides of Evennia's Server and Portal service classes.

Both are named by settings that `evennia._init()` resolves — and `_init()` runs
after `django.setup()`, so `AppConfig.ready()` has already had its chance to
repoint them. That ordering is what makes these ordinary subclasses rather than
patches over live objects: at `ready()` time neither service exists yet, and by
the time one does, the class it was built from was ours.

Only one of the two is ever built in a given process. A Portal never constructs
a Server service and a Server never constructs a Portal's, so the unused
override costs a class object and nothing else.

See docs/test-plan.md § IA.
"""

from .config import get_instance_id

#: The key an instance's name travels under inside Evennia's ``info_dict``.
#: Prefixed because the dict is Evennia's and a consumer may add to it too.
INSTANCE_KEY = "multiplex_instance_id"

#: Set by `AppConfig.ready()` to the generated class, so the dotted path in
#: EVENNIA_SERVER_SERVICE_CLASS resolves. Evennia looks the setting up by string.
ScalingServerService = None


def make_server_service(base):
    """Build the Server service class, subclassing whatever the consumer had.

    A factory rather than a module-level class so the base is supplied rather
    than resolved at import time — `AppConfig.ready()` passes the consumer's
    stashed class, and a test passes its own.
    """

    class ScalingServerService(base):
        """Announces this instance's name on the handshake it already sends."""

        def get_info_dict(self):
            """Evennia's own info, plus who this instance is.

            Called when the Server's AMP client connects, and sent to the
            Portal with the ``PSYNC`` handshake. The Portal reads the name off
            that message and records the connection it arrived on.

            Copied rather than written into: Evennia returns the live dict off
            the service, so mutating it would leave the key on the service
            itself, accumulating across calls and appearing in Evennia's own
            view of its state.

            `get_instance_id` is imported here rather than at module scope, so
            a Portal loading this module does not pull in the bus for a class
            it will never build.
            """
            info = dict(super().get_info_dict())
            # No guard around this. Message-bus refuses to boot without an id,
            # so a Server that is running has one — and swallowing a failure
            # would hide a misconfiguration at the moment the Portal is
            # deciding who it is talking to.
            info[INSTANCE_KEY] = get_instance_id()
            return info

    return ScalingServerService
