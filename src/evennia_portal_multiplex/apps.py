# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig — the library's only way into a running Evennia.

`ready()` runs during ``django.setup()``, which both the Portal and the Server
call before ``evennia._init()`` builds their services. So repointing the class
settings here is early enough for `_init()` to find ours, and nothing has to be
patched at runtime.

There is no alternative entry point. `PORTAL_SERVICES_PLUGIN_MODULES` names a
gamedir module, so a consumer would have to wire it themselves; a library gets
`ready()` and what it can reach from there.

Every line of `ready()` runs in **both** processes, and at that moment there is
no way to tell which one this is — the distinction is a flag passed to `_init()`
later. That is why the repointing pattern suits it: the setting the wrong
process never resolves costs a class object and nothing else.

See docs/test-plan.md § IN.
"""

from django.apps import AppConfig


class EvenniaPortalMultiplexConfig(AppConfig):
    name = "evennia_portal_multiplex"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import amp_client, evennia_patch, services, sessionhandler
        from .registry import InstanceRegistry

        # Not a class setting, so it does not go through _layer_over: Evennia's
        # Server service looks `amp_client.AMPClientFactory` up by name at call
        # time, and this rebinds it. **Delete this line when the upstream fix
        # lands** — see evennia_patch's docstring and PT-04.
        evennia_patch.install()

        # Layered on after the patch, so ours is the leaf and the patched
        # class is underneath. The other way round, the patch would subclass
        # ours and `buildProtocol` would still be Evennia's broken one.
        # Rebound the same way, because no setting names this class either.
        from evennia.server import amp_client as evennias_amp_client

        evennias_amp_client.AMPClientFactory = amp_client.make_amp_client_factory(
            evennias_amp_client.AMPClientFactory
        )

        # One registry, built here and handed to every factory that needs it.
        # The AMP protocol writes into it, the session handler reads from it,
        # and the Portal service holds it so there is one obvious owner — all
        # three the same object. Two of them would not fail: the service would
        # be recorded into while the handler consulted an empty one, so every
        # session would route to the default and nothing would say so.
        registry = InstanceRegistry()

        self._layer_over(
            setting="EVENNIA_PORTAL_SERVICE_CLASS",
            stash="_MULTIPLEX_ORIGINAL_PORTAL_SERVICE",
            module=services,
            attribute="MultiplexPortalService",
            factory=lambda base: services.make_portal_service(base, registry),
        )
        self._layer_over(
            setting="EVENNIA_SERVER_SERVICE_CLASS",
            stash="_MULTIPLEX_ORIGINAL_SERVER_SERVICE",
            module=services,
            attribute="MultiplexServerService",
            factory=services.make_server_service,
        )
        # Layered after the patch above, which is what makes this setting
        # reach anything: unpatched, Evennia resolves it and then ignores it.
        self._layer_over(
            setting="AMP_CLIENT_PROTOCOL_CLASS",
            stash="_MULTIPLEX_ORIGINAL_AMP_CLIENT_PROTOCOL",
            module=amp_client,
            attribute="MultiplexAMPClientProtocol",
            factory=amp_client.make_amp_client_protocol,
        )
        self._layer_over(
            setting="PORTAL_SESSION_HANDLER_CLASS",
            stash="_MULTIPLEX_ORIGINAL_SESSION_HANDLER",
            module=sessionhandler,
            attribute="MultiplexPortalSessionHandler",
            factory=lambda base: sessionhandler.make_session_handler(
                base, registry
            ),
        )

    def _layer_over(self, setting, stash, module, attribute, factory):
        """Subclass whatever class a setting names, and repoint it at ours.

        The consumer's class is stashed and built on top of, rather than
        replaced — ours is the leaf, so our method runs and `super()` runs
        theirs. A game with its own Portal service keeps it.

        The generated class is assigned onto its module because Evennia
        resolves these settings by dotted path, not by value.

        `ready()` can run more than once, so repointing a setting that already
        names ours returns rather than layering a second time.
        """
        from django.conf import settings
        from evennia.utils.utils import class_from_module

        ours = f"{module.__name__}.{attribute}"
        original = getattr(settings, setting)
        if original == ours:
            return

        setattr(settings, stash, original)
        setattr(module, attribute, factory(class_from_module(original)))
        setattr(settings, setting, ours)
