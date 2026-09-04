# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-portal-multiplex.

A case is agreed in docs/test-plan.md first, then the test is written here
against it, then the code. Every test carries its case ID as its
docstring, so the coverage trail reads in both directions.

Discovered by Django's test runner via runtests.py at the repository root.
"""

import unittest
from unittest import mock

from evennia_portal_multiplex.amp import make_amp_protocol, record_announcement
from evennia_portal_multiplex.binding import bind, connection_for, instance_for
from evennia_portal_multiplex.launcher import server_start
from evennia_portal_multiplex.registry import InstanceRegistry
from evennia_portal_multiplex.routing import sending_to
from evennia_portal_multiplex.services import INSTANCE_KEY, make_server_service
from evennia_portal_multiplex.move import NotAttached, move_session


def _patch_default(instance_id):
    """Patch every module that resolves the default instance.

    `binding` resolves it to answer "which instance does this session belong
    to"; `registry` resolves it to answer "which connection is the default".
    Both imported the name, so each holds its own reference — patching one
    leaves the other reading real settings.
    """
    binding_patch = mock.patch(
        "evennia_portal_multiplex.binding.get_default_instance",
        return_value=instance_id,
    )
    registry_patch = mock.patch(
        "evennia_portal_multiplex.registry.get_default_instance",
        return_value=instance_id,
    )

    class _Both:
        def __enter__(self):
            binding_patch.start()
            registry_patch.start()
            return self

        def __exit__(self, *exc):
            registry_patch.stop()
            binding_patch.stop()
            return False

    return _Both()


class TestInstanceRegistry(unittest.TestCase):
    """IR — the instance registry."""

    def _connection(self, label="conn"):
        """A stand-in for an AMP connection. The registry only stores it."""
        return mock.Mock(name=label)

    def test_ir_01_registers_a_connection_under_its_instance_id(self):
        """IR-01: what was registered comes back under that id."""
        registry = InstanceRegistry()
        connection = self._connection()
        registry.register("second", connection)
        self.assertIs(registry.connection_for("second"), connection)

    def test_ir_02_reconnecting_replaces_rather_than_duplicates(self):
        """IR-02: a Server that restarts reattaches; the dead one goes."""
        registry = InstanceRegistry()
        first, second = self._connection("first"), self._connection("second")
        registry.register("second", first)
        registry.register("second", second)
        self.assertIs(registry.connection_for("second"), second)
        self.assertEqual(registry.attached(), ["second"])

    def test_ir_03_registering_without_an_id_records_nothing(self):
        """IR-03: most admin messages carry no instance id."""
        registry = InstanceRegistry()
        registry.register(None, self._connection())
        registry.register("", self._connection())
        self.assertEqual(registry.attached(), [])

    def test_ir_04_a_dropped_connection_is_removed(self):
        """IR-04: forget() takes the instance with it."""
        registry = InstanceRegistry()
        connection = self._connection()
        registry.register("second", connection)
        registry.forget(connection)
        self.assertEqual(registry.attached(), [])
        self.assertIsNone(registry.connection_for("second"))

    def test_ir_05_a_stale_disconnect_cannot_delete_its_replacement(self):
        """IR-05: the old connection's loss arrives after the new one registers.

        Deleting by name here would leave the instance attached but unreachable, and
        nothing would say so.
        """
        registry = InstanceRegistry()
        old, new = self._connection("old"), self._connection("new")
        registry.register("second", old)
        registry.register("second", new)
        registry.forget(old)
        self.assertIs(registry.connection_for("second"), new)

    def test_ir_06_an_unattached_instance_returns_none(self):
        """IR-06: a miss is None, so each caller decides what that means."""
        registry = InstanceRegistry()
        registry.register("second", self._connection())
        self.assertIsNone(registry.connection_for("third"))

    def test_ir_07_the_default_instance_is_retrievable_by_role(self):
        """IR-07: callers ask for the default, not for its configured id."""
        registry = InstanceRegistry()
        default = self._connection("default")
        registry.register("this-instance", default)
        registry.register("second", self._connection("second"))
        with mock.patch(
            "evennia_portal_multiplex.registry.get_default_instance", return_value="this-instance"
        ):
            self.assertIs(registry.default_connection(), default)

    def test_ir_09_default_connection_is_none_when_it_is_not_attached(self):
        """IR-09: a Portal whose default instance has not attached has none."""
        registry = InstanceRegistry()
        registry.register("second", self._connection())
        with mock.patch(
            "evennia_portal_multiplex.registry.get_default_instance", return_value="this-instance"
        ):
            self.assertIsNone(registry.default_connection())

    def test_ir_08_reports_every_attached_instance(self):
        """IR-08: what this Portal is holding, inspectable and stable in order."""
        registry = InstanceRegistry()
        registry.register("third", self._connection())
        registry.register("this-instance", self._connection())
        registry.register("second", self._connection())
        self.assertEqual(registry.attached(), sorted(["third", "this-instance", "second"]))


class TestLauncherCommands(unittest.TestCase):
    """LC — launcher commands the library adds to `evennia`."""

    #: What Evennia's own launcher would hand back for this gamedir.
    PORTAL_CMD = ["twistd", "--python=portal.py"]
    SERVER_CMD = ["twistd", "--python=server.py"]

    def _launcher(self):
        """A stand-in for `evennia.server.evennia_launcher`.

        `server_start` imports it inside the function, so patching the module
        attribute reaches the call.
        """
        fake = mock.Mock()
        fake._get_twistd_cmdline.return_value = (self.PORTAL_CMD, self.SERVER_CMD)
        fake.getenv.return_value = {"PYTHONPATH": "/gamedir"}
        return fake

    def _run(self, launcher):
        """Call server_start with the launcher and subprocess both faked."""
        with mock.patch.dict(
            "sys.modules", {"evennia.server.evennia_launcher": launcher}
        ), mock.patch("subprocess.Popen") as popen:
            server_start()
        return popen

    def test_lc_01_runs_the_command_evennia_would_build(self):
        """LC-01: the invocation comes from Evennia, not from us."""
        launcher = self._launcher()
        popen = self._run(launcher)
        launcher._get_twistd_cmdline.assert_called_once()
        self.assertEqual(popen.call_args.args[0], self.SERVER_CMD)

    def test_lc_02_never_runs_the_portals_command(self):
        """LC-02: _get_twistd_cmdline returns both; only the Server's is wanted.

        Taking the wrong element starts a second Portal, which fights the first
        for the AMP port — an easy slip with a confusing symptom.
        """
        popen = self._run(self._launcher())
        self.assertNotEqual(popen.call_args.args[0], self.PORTAL_CMD)

    def test_lc_03_runs_it_with_the_launchers_environment(self):
        """LC-03: the gamedir and settings reach the child process."""
        launcher = self._launcher()
        popen = self._run(launcher)
        launcher.getenv.assert_called_once()
        self.assertEqual(popen.call_args.kwargs["env"], launcher.getenv.return_value)

    def test_lc_04_sends_nothing_to_a_portal(self):
        """LC-04: the whole point — an attached Server is not stopped.

        `send_instruction` is how the launcher speaks to a Portal, and
        `istart` uses it to stop the current Server before starting its own.
        """
        launcher = self._launcher()
        self._run(launcher)
        launcher.send_instruction.assert_not_called()

    def test_lc_05_resolves_at_the_configured_dotted_path(self):
        """LC-05: resolved the way `run_custom_commands` resolves it.

        Mirrors Evennia's own lookup rather than importing directly, so the
        string a consumer writes in EXTRA_LAUNCHER_COMMANDS is what is proven.
        """
        import importlib

        path = "evennia_portal_multiplex.launcher.server_start"
        modpath, cmdname = path.rsplit(".", 1)
        module = importlib.import_module(modpath)
        self.assertIs(module.__dict__.get(cmdname), server_start)


class TestInstanceAnnouncement(unittest.TestCase):
    """IA — announcing an instance's name."""

    def _base(self):
        """A stand-in for Evennia's Server service.

        `get_info_dict` returns the live dict off the service, as Evennia's
        does — which is what IA-03 exists to catch.
        """

        class FakeServerService:
            def __init__(self):
                self.info_dict = {"amp": "amp: 4006", "webserver": "4005"}

            def get_info_dict(self):
                return self.info_dict

        return FakeServerService

    def _service(self):
        base = self._base()
        return make_server_service(base)(), base

    def test_ia_01_announces_the_instance_id(self):
        """IA-01: the name goes into the handshake under the library's key."""
        service, _ = self._service()
        with mock.patch(
            "evennia_portal_multiplex.services.get_instance_id",
            return_value="second",
        ):
            info = service.get_info_dict()
        self.assertEqual(info[INSTANCE_KEY], "second")

    def test_ia_02_leaves_evennias_own_keys_intact(self):
        """IA-02: the launcher still prints what it always printed."""
        service, _ = self._service()
        with mock.patch(
            "evennia_portal_multiplex.services.get_instance_id",
            return_value="second",
        ):
            info = service.get_info_dict()
        self.assertEqual(info["amp"], "amp: 4006")
        self.assertEqual(info["webserver"], "4005")

    def test_ia_03_does_not_mutate_the_services_own_dict(self):
        """IA-03: Evennia hands back the live dict; we must not write into it."""
        service, _ = self._service()
        with mock.patch(
            "evennia_portal_multiplex.services.get_instance_id",
            return_value="second",
        ):
            service.get_info_dict()
            service.get_info_dict()
        self.assertNotIn(INSTANCE_KEY, service.info_dict)

    def test_ia_04_subclasses_the_consumers_service_class(self):
        """IA-04: a consumer's own service class stays underneath ours."""
        base = self._base()
        self.assertTrue(issubclass(make_server_service(base), base))


class TestAmpResponder(unittest.TestCase):
    """AR — recording an announcement."""

    def _base(self):
        """A stand-in for Evennia's AMP protocol, recording what it was asked.

        Deliberately not a `CommandLocator`: these cases call the methods
        directly. AR-07 uses Evennia's real class instead, because the dispatch
        table is the thing under test there.
        """

        class FakeAMPProtocol:
            def __init__(self):
                self.admin_calls = []
                self.lost = []

            def data_in(self, packed_data):
                return packed_data

            def portal_receive_adminserver2portal(self, packed_data):
                self.admin_calls.append(packed_data)
                return "evennias-return-value"

            def connectionLost(self, reason):
                self.lost.append(reason)

        return FakeAMPProtocol

    def _protocol(self, registry):
        return make_amp_protocol(self._base(), registry)()

    def _message(self, info_dict):
        """What `data_in` hands back: a (sessid, kwargs) pair."""
        return (0, {"operation": b"\x03", "info_dict": info_dict})

    def test_ar_01_an_announcement_registers_the_connection(self):
        """AR-01: the name is written against the connection it arrived on."""
        registry = InstanceRegistry()
        protocol = self._protocol(registry)
        protocol.portal_receive_adminserver2portal(
            self._message({"amp": "4006", INSTANCE_KEY: "second"})
        )
        self.assertIs(registry.connection_for("second"), protocol)

    def test_ar_02_a_message_without_an_info_dict_registers_nothing(self):
        """AR-02: most admin messages carry none."""
        registry = InstanceRegistry()
        protocol = self._protocol(registry)
        protocol.portal_receive_adminserver2portal((0, {"operation": b"\x04"}))
        self.assertEqual(registry.attached(), [])

    def test_ar_03_an_info_dict_without_our_key_registers_nothing(self):
        """AR-03: a Server that predates this library still announces itself."""
        registry = InstanceRegistry()
        protocol = self._protocol(registry)
        protocol.portal_receive_adminserver2portal(self._message({"amp": "4006"}))
        self.assertEqual(registry.attached(), [])

    def test_ar_04_evennias_own_handling_still_runs(self):
        """AR-04: we observe the message, we do not consume it."""
        registry = InstanceRegistry()
        protocol = self._protocol(registry)
        message = self._message({INSTANCE_KEY: "second"})
        result = protocol.portal_receive_adminserver2portal(message)
        self.assertEqual(protocol.admin_calls, [message])
        self.assertEqual(result, "evennias-return-value")

    def test_ar_05_a_lost_connection_is_forgotten(self):
        """AR-05: an instance that drops stops being reachable."""
        registry = InstanceRegistry()
        protocol = self._protocol(registry)
        protocol.portal_receive_adminserver2portal(
            self._message({INSTANCE_KEY: "second"})
        )
        protocol.connectionLost("gone")
        self.assertEqual(registry.attached(), [])

    def test_ar_06_losing_a_connection_still_calls_the_base(self):
        """AR-06: Evennia's own teardown is not skipped."""
        registry = InstanceRegistry()
        protocol = self._protocol(registry)
        protocol.connectionLost("gone")
        self.assertEqual(protocol.lost, ["gone"])

    def test_ar_07_the_responder_is_registered_not_merely_overridden(self):
        """AR-07: the dispatch table must point at ours, not the parent's.

        Twisted builds `_commandDispatch` at class creation from the
        `@Command.responder` decorators it finds. A subclass that redefines the
        method without the decorator inherits a table still naming the parent's
        function, so the override is never called and nothing says so.
        """
        from evennia.server.portal import amp as evennia_amp
        from evennia.server.portal.amp_server import AMPServerProtocol

        generated = make_amp_protocol(AMPServerProtocol, InstanceRegistry())
        key = evennia_amp.AdminServer2Portal.commandName
        _command, responder = generated._commandDispatch[key]

        self.assertIs(responder, generated.portal_receive_adminserver2portal)
        self.assertIsNot(
            responder, AMPServerProtocol.portal_receive_adminserver2portal
        )

    def test_ar_08_subclasses_the_class_it_was_given(self):
        """AR-08: whatever the Portal was going to build stays underneath."""
        base = self._base()
        self.assertTrue(issubclass(make_amp_protocol(base, InstanceRegistry()), base))


class TestRouting(unittest.TestCase):
    """RT — routing a send."""

    def _factory(self, held=None):
        """A stand-in for the Portal's AMP factory."""
        factory = mock.Mock()
        factory.server_connection = held
        factory.portal.amp_protocol = "untouched"
        return factory

    def _connection(self, factory):
        connection = mock.Mock()
        connection.factory = factory
        return connection

    def test_rt_01_points_the_outbound_reference_at_the_connection(self):
        """RT-01: while routed, this is where data_to_server will send."""
        factory = self._factory(held="evennias-choice")
        connection = self._connection(factory)
        with sending_to(connection):
            self.assertIs(factory.server_connection, connection)

    def test_rt_02_restores_what_was_there_before(self):
        """RT-02: the Portal is left as it was found."""
        factory = self._factory(held="evennias-choice")
        connection = self._connection(factory)
        with sending_to(connection):
            pass
        self.assertEqual(factory.server_connection, "evennias-choice")

    def test_rt_03_restores_even_when_the_block_raises(self):
        """RT-03: otherwise the Portal stays pointed at one instance.

        Every later unrouted message would then go to the wrong Server, and
        nothing would have failed visibly.
        """
        factory = self._factory(held="evennias-choice")
        connection = self._connection(factory)
        with self.assertRaises(ValueError):
            with sending_to(connection):
                raise ValueError("the send failed")
        self.assertEqual(factory.server_connection, "evennias-choice")

    def test_rt_04_routing_to_nothing_leaves_evennias_choice_alone(self):
        """RT-04: an unattached instance does not clear the reference."""
        factory = self._factory(held="evennias-choice")
        with sending_to(None):
            pass
        self.assertEqual(factory.server_connection, "evennias-choice")

    def test_rt_05_does_not_write_to_amp_protocol(self):
        """RT-05: proved unnecessary, and kept that way deliberately.

        `data_in` and `connect` read it only as a truthiness check; the send
        goes through data_to_server, which reads server_connection.
        """
        factory = self._factory(held="evennias-choice")
        connection = self._connection(factory)
        with sending_to(connection):
            self.assertEqual(factory.portal.amp_protocol, "untouched")
        self.assertEqual(factory.portal.amp_protocol, "untouched")


class TestSessionBinding(unittest.TestCase):
    """SB — which instance a session belongs to."""

    DEFAULT = "first"

    def _session(self):
        """A stand-in for a Portal session. Only the attribute matters."""

        class FakeSession:
            pass

        return FakeSession()

    def _default(self):
        """Patch both lookups.

        `binding` resolves the default to answer "which instance", and
        `registry` resolves it to answer "which connection". Each imported the
        name, so each holds its own reference and each needs patching.
        """
        return _patch_default(self.DEFAULT)

    def test_sb_01_an_unbound_session_belongs_to_the_default(self):
        """SB-01: the default is a decision, not whatever a global holds."""
        with self._default():
            self.assertEqual(instance_for(self._session()), self.DEFAULT)

    def test_sb_02_a_bound_session_belongs_where_it_was_bound(self):
        """SB-02: binding is what the session then answers with."""
        session = self._session()
        bind(session, "second")
        with self._default():
            self.assertEqual(instance_for(session), "second")

    def test_sb_03_follows_an_instance_that_reconnects(self):
        """SB-03: the binding is a name, so a replaced connection is followed.

        A session holding the connection object would be writing into a dead
        one after an instance restarts, and nothing would say so.
        """
        registry = InstanceRegistry()
        old, new = mock.Mock(name="old"), mock.Mock(name="new")
        registry.register("second", old)

        session = self._session()
        bind(session, "second")
        with self._default():
            self.assertIs(connection_for(registry, session), old)
            registry.register("second", new)
            self.assertIs(connection_for(registry, session), new)

    def test_sb_04_falls_back_to_the_default_when_not_attached(self):
        """SB-04: a stopped instance leaves its sessions somewhere real."""
        registry = InstanceRegistry()
        default = mock.Mock(name="default")
        registry.register(self.DEFAULT, default)

        session = self._session()
        bind(session, "second")
        with self._default():
            self.assertIs(connection_for(registry, session), default)

    def test_sb_05_binding_one_session_leaves_others_alone(self):
        """SB-05: per-session state, not a shared map keyed loosely."""
        moved, untouched = self._session(), self._session()
        bind(moved, "second")
        with self._default():
            self.assertEqual(instance_for(moved), "second")
            self.assertEqual(instance_for(untouched), self.DEFAULT)


class TestMovingASession(unittest.TestCase):
    """MV — moving a session between instances."""

    DEFAULT = "first"

    def _connection(self, factory):
        """A connection that records every admin send, and where it went."""
        connection = mock.Mock()
        connection.factory = factory
        connection.sent = []

        def send_admin(session, operation=None, **kwargs):
            # Recorded with the factory's current target, so a send left to
            # Evennia's global is distinguishable from a routed one (MV-05).
            connection.sent.append(
                (operation, kwargs, factory.server_connection)
            )

        connection.send_AdminPortal2Server = send_admin
        return connection

    def _world(self):
        """A registry holding the default instance and a second, one factory."""
        factory = mock.Mock()
        factory.server_connection = "evennias-global-choice"
        registry = InstanceRegistry()
        default = self._connection(factory)
        second = self._connection(factory)
        registry.register(self.DEFAULT, default)
        registry.register("second", second)
        return registry, default, second

    def _session(self):
        """A Portal session, recording any touch of its transport (MV-08)."""

        class FakeSession:
            def __init__(self):
                self.uid = 1
                self.logged_in = True
                self.puid = 7
                self.sessid = 1
                self.transport_calls = []

            def get_sync_data(self):
                return {"uid": self.uid, "logged_in": self.logged_in}

            def disconnect(self, *a, **kw):
                self.transport_calls.append("disconnect")

            @property
            def transport(self):
                self.transport_calls.append("transport")
                return mock.Mock()

        return FakeSession()

    def _default(self):
        """Patch both lookups.

        `binding` resolves the default to answer "which instance", and
        `registry` resolves it to answer "which connection". Each imported the
        name, so each holds its own reference and each needs patching.
        """
        return _patch_default(self.DEFAULT)

    def _move(self, registry, session, target):
        with self._default():
            return move_session(registry, session, target)

    def test_mv_01_the_instance_being_left_is_released(self):
        """MV-01: PDISCONN to where the session is now."""
        from evennia.server.portal.amp import PDISCONN

        registry, default, _second = self._world()
        session = self._session()
        self._move(registry, session, "second")
        self.assertEqual([op for op, _, _ in default.sent], [PDISCONN])

    def test_mv_02_the_destination_is_given_the_session(self):
        """MV-02: PCONN, carrying what the new Server needs to build one."""
        from evennia.server.portal.amp import PCONN

        registry, _default, second = self._world()
        session = self._session()
        self._move(registry, session, "second")
        operations = [op for op, _, _ in second.sent]
        self.assertEqual(operations, [PCONN])
        _op, kwargs, _target = second.sent[0]
        self.assertIn("sessiondata", kwargs)

    def test_mv_03_identity_is_cleared_before_the_destination_is_told(self):
        """MV-03: they are primary keys belonging to the Server being left.

        Order matters: cleared after the PCONN, the destination has already
        received the old uid in the sync data and the clearing achieves
        nothing.
        """
        registry, _default, second = self._world()
        session = self._session()
        self._move(registry, session, "second")

        self.assertIsNone(session.uid)
        self.assertFalse(session.logged_in)
        self.assertIsNone(session.puid)

        _op, kwargs, _target = second.sent[0]
        self.assertIsNone(kwargs["sessiondata"]["uid"])
        self.assertFalse(kwargs["sessiondata"]["logged_in"])

    def test_mv_04_the_session_is_rebound(self):
        """MV-04: its traffic goes to the destination from here on."""
        registry, _default, second = self._world()
        session = self._session()
        self._move(registry, session, "second")
        with self._default():
            self.assertEqual(instance_for(session), "second")
            self.assertIs(connection_for(registry, session), second)

    def test_mv_05_each_send_is_routed_to_its_own_instance(self):
        """MV-05: data_to_server ignores the object it was called on.

        So the factory's target at the moment of each send is what decides
        where it lands.
        """
        registry, default, second = self._world()
        session = self._session()
        self._move(registry, session, "second")
        self.assertEqual(default.sent[0][2], default)
        self.assertEqual(second.sent[0][2], second)

    def test_mv_06_an_unattached_destination_refuses(self):
        """MV-06: loud, because a fallback would look like success."""
        registry, default, _second = self._world()
        session = self._session()
        with self.assertRaises(NotAttached):
            self._move(registry, session, "absent")
        self.assertEqual(default.sent, [])
        self.assertEqual(session.uid, 1)

    def test_mv_07_moving_to_where_it_already_is_does_nothing(self):
        """MV-07: no sends, no clearing, and it says so."""
        registry, default, _second = self._world()
        session = self._session()
        self.assertFalse(self._move(registry, session, self.DEFAULT))
        self.assertEqual(default.sent, [])
        self.assertEqual(session.uid, 1)

    def test_mv_08_the_transport_is_never_touched(self):
        """MV-08: this is what makes it a move rather than a reconnect."""
        registry, _default, _second = self._world()
        session = self._session()
        self._move(registry, session, "second")
        self.assertEqual(session.transport_calls, [])
