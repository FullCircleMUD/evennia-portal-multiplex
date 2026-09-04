# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-portal-multiplex.

A case is agreed in docs/test-plan.md first, then the test is written here
against it, then the code. Every test carries its case ID as its
docstring, so the coverage trail reads in both directions.

Discovered by Django's test runner via runtests.py at the repository root.
"""

import unittest
from unittest import mock

from evennia.server.portal import amp as amp_module
from evennia.utils.utils import class_from_module
from twisted.internet import defer

from evennia_portal_multiplex.amp import make_amp_protocol, record_announcement
from evennia_portal_multiplex.amp_client import (
    make_amp_client_factory,
    make_amp_client_protocol,
)
from evennia_portal_multiplex.binding import bind, connection_for, instance_for
from evennia_portal_multiplex.launcher import server_start
from evennia_portal_multiplex.query import (
    MultiplexQueryRegistry,
    am_i_registered,
    query_registry,
)
from evennia_portal_multiplex.evennia_patch import install, make_patched_factory
from evennia_portal_multiplex.registry import InstanceRegistry
from evennia_portal_multiplex.startup import NotRegistered, check_registration
from evennia_portal_multiplex.routing import sending_to
from django.conf import settings

from evennia_portal_multiplex.services import (
    INSTANCE_KEY,
    make_portal_service,
    make_server_service,
)
from evennia_portal_multiplex.sessionhandler import make_session_handler
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
        """Call server_start with the launcher and subprocess both faked.

        `_server_came_up` is stubbed to the happy answer: it sleeps for real,
        and these cases are about what was launched, not what became of it.
        """
        with mock.patch.dict(
            "sys.modules", {"evennia.server.evennia_launcher": launcher}
        ), mock.patch("subprocess.Popen") as popen, mock.patch(
            "evennia_portal_multiplex.launcher._server_came_up", return_value=True
        ):
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

    def test_lc_06_a_server_that_did_not_come_up_is_reported(self):
        """LC-06: the operator types a command and nothing happens otherwise.

        twistd has daemonised by the time the Server refuses to start, so it
        has no stdout and the launcher has already returned to the prompt. The
        bar is saying something, not diagnosing: the reason is in the log, and
        the terminal's job is to send the reader there.

        Claiming success is the worse half of this. A message that says
        "Server started" when it did not is what makes the operator go looking
        somewhere else.
        """
        import contextlib
        import io

        launcher = self._launcher()
        printed = io.StringIO()
        with mock.patch.dict(
            "sys.modules", {"evennia.server.evennia_launcher": launcher}
        ), mock.patch("subprocess.Popen"), mock.patch(
            "evennia_portal_multiplex.launcher._server_came_up",
            return_value=False,
        ), contextlib.redirect_stdout(printed):
            server_start()

        output = printed.getvalue().lower()
        self.assertIn("did not start", output)
        self.assertIn("log", output)
        self.assertNotIn("server started", output)

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


class TestInstallation(unittest.TestCase):
    """IN — installation."""

    DEFAULT = "first"

    # -- Portal service -------------------------------------------------

    def _portal_base(self):
        """A stand-in for Evennia's Portal service.

        `register_amp` is what creates the AMP service, exactly as Evennia's
        does — so an override that touches the factory before calling super()
        finds nothing there (IN-03).
        """

        class FakePortalService:
            def __init__(self, *args, **kwargs):
                self.services = {}
                self.register_amp_calls = 0

            def register_amp(self):
                self.register_amp_calls += 1
                factory = mock.Mock()

                class EvenniasOwnProtocol:
                    pass

                factory.protocol = EvenniasOwnProtocol
                service = mock.Mock()
                service.args = (4006, factory)
                self.services["PortalAMPServer"] = service

            def getServiceNamed(self, name):
                return self.services[name]

        return FakePortalService

    def test_in_01_the_portal_service_holds_the_registry_it_was_given(self):
        """IN-01: not one of its own — see IN-09."""
        registry = InstanceRegistry()
        service = make_portal_service(self._portal_base(), registry)()
        self.assertIs(service.registry, registry)

    def test_in_02_register_amp_puts_our_protocol_on_the_factory(self):
        """IN-02: without this the Portal records nothing, silently."""
        service = make_portal_service(self._portal_base(), InstanceRegistry())()
        service.register_amp()
        factory = service.getServiceNamed("PortalAMPServer").args[1]
        self.assertEqual(factory.protocol.__name__, "MultiplexAMPServerProtocol")
        # Layered over whatever Evennia was going to build, not replacing it.
        self.assertEqual(
            factory.protocol.__mro__[1].__name__, "EvenniasOwnProtocol"
        )

    def test_in_03_register_amp_calls_super_first(self):
        """IN-03: the factory does not exist until Evennia's has run.

        Touching it earlier is an AttributeError on something absent, caught
        and shrugged off — leaving a Portal that runs and records nothing.
        """
        service = make_portal_service(self._portal_base(), InstanceRegistry())()
        service.register_amp()
        self.assertEqual(service.register_amp_calls, 1)

    # -- Session handler ------------------------------------------------

    def _handler_base(self):
        """A stand-in for PortalSessionHandler, recording where a send landed."""

        class FakeSessionHandler:
            def __init__(self, factory):
                self.factory = factory
                self.sent = []

            def _record(self, what, session):
                # Evennia's reads factory.server_connection at this moment.
                self.sent.append((session, self.factory.server_connection, what))

            def data_in(self, session, **kwargs):
                self._record("data_in", session)

            def connect(self, session):
                self._record("connect", session)

            def sync(self, session):
                self._record("sync", session)

            def disconnect(self, session):
                self._record("disconnect", session)

            def disconnect_all(self):
                # Evennia's sends one message and closes every socket in the
                # callback attached to it. Skipping it leaves them open.
                self._record("disconnect_all", None)

        return FakeSessionHandler

    def _handler_world(self):
        factory = mock.Mock()
        factory.server_connection = "evennias-global-choice"
        registry = InstanceRegistry()
        default, second = mock.Mock(name="default"), mock.Mock(name="second")
        for connection in (default, second):
            connection.factory = factory
        registry.register(self.DEFAULT, default)
        registry.register("second", second)
        handler = make_session_handler(self._handler_base(), registry)(factory)
        return handler, default, second

    def _session(self):
        class FakeSession:
            pass

        return FakeSession()

    def test_in_04_input_goes_to_the_instance_the_session_is_bound_to(self):
        """IN-04: what the player types follows the binding."""
        handler, _default, second = self._handler_world()
        session = self._session()
        bind(session, "second")
        with _patch_default(self.DEFAULT):
            handler.data_in(session, text="look")
        self.assertEqual(handler.sent[0][1], second)

    def test_in_05_the_handler_calls_the_base(self):
        """IN-05: replacing it skips clean_senddata and malforms the message."""
        handler, _default, _second = self._handler_world()
        session = self._session()
        with _patch_default(self.DEFAULT):
            handler.data_in(session, text="look")
        self.assertEqual(handler.sent[0][0], session)

    def test_in_06_an_unbound_session_goes_to_the_default(self):
        """IN-06: not to whichever Server attached most recently."""
        handler, default, _second = self._handler_world()
        with _patch_default(self.DEFAULT):
            handler.data_in(self._session(), text="look")
        self.assertEqual(handler.sent[0][1], default)

    def test_in_13_a_new_session_is_announced_where_its_input_goes(self):
        """IN-13: announce and input have to agree.

        Unrouted, the announce went to whichever Server spoke to the Portal
        most recently, while everything typed went to the default. The session
        is then created on one Server and spoken to on another, which has
        never heard of it — a login screen, then nothing works.
        """
        handler, default, _second = self._handler_world()
        with _patch_default(self.DEFAULT):
            handler.connect(self._session())
        self.assertEqual(handler.sent[0][1], default)

    def test_in_14_sync_follows_the_same_connection(self):
        """IN-14: telnet negotiates after connecting, and calls this.

        Terminal type, width and compression settle once the session already
        exists, and the Server holding it is the one that needs them.
        """
        handler, _default, second = self._handler_world()
        session = self._session()
        bind(session, "second")
        with _patch_default(self.DEFAULT):
            handler.sync(session)
        self.assertEqual(handler.sent[0][1], second)

    def test_in_15_disconnect_tells_the_instance_holding_it(self):
        """IN-15: not the last Server to speak, which never had the session."""
        handler, _default, second = self._handler_world()
        session = self._session()
        bind(session, "second")
        with _patch_default(self.DEFAULT):
            handler.disconnect(session)
        self.assertEqual(handler.sent[0][1], second)

    def test_in_16_disconnect_all_reaches_every_instance(self):
        """IN-16: a Portal shutting down speaks to every Server it has.

        Sent once, the other instances carry on believing their players are
        still connected — characters standing in rooms with nobody at the
        keyboard.
        """
        from evennia.server.portal.amp import PDISCONNALL

        handler, default, second = self._handler_world()
        with _patch_default(self.DEFAULT):
            handler.disconnect_all()
        for connection in (default, second):
            self.assertEqual(
                connection.send_AdminPortal2Server.call_args.kwargs["operation"],
                PDISCONNALL,
            )

    def test_in_17_disconnect_all_still_closes_the_sockets(self):
        """IN-17: Evennia welds the send to the teardown.

        The callback that closes the Portal's own sockets is attached to that
        send's Deferred, so skipping `super()` would leave every socket open.
        Its message lands on a Server that has already dropped everything and
        finds nothing to do.
        """
        handler, _default, _second = self._handler_world()
        with _patch_default(self.DEFAULT):
            handler.disconnect_all()
        self.assertIn("disconnect_all", [sent[2] for sent in handler.sent])

    # -- AppConfig ------------------------------------------------------

    def test_in_07_ready_stashes_and_repoints_each_setting(self):
        """IN-07: Evennia resolves these later, by string, in _init()."""
        from django.apps import apps as django_apps
        from django.test import override_settings

        config = django_apps.get_app_config("evennia_portal_multiplex")
        # Evennia's own defaults, which is what a consumer has unless they
        # have layered something of their own. They must be importable: the
        # installer resolves each one to build on top of it.
        portal_class = "evennia.server.portal.service.EvenniaPortalService"
        server_class = "evennia.server.service.EvenniaServerService"
        handler_class = (
            "evennia.server.portal.portalsessionhandler.PortalSessionHandler"
        )
        with override_settings(
            EVENNIA_PORTAL_SERVICE_CLASS=portal_class,
            EVENNIA_SERVER_SERVICE_CLASS=server_class,
            PORTAL_SESSION_HANDLER_CLASS=handler_class,
        ):
            config.ready()
            self.assertEqual(
                settings.EVENNIA_PORTAL_SERVICE_CLASS,
                "evennia_portal_multiplex.services.MultiplexPortalService",
            )
            self.assertEqual(
                settings.EVENNIA_SERVER_SERVICE_CLASS,
                "evennia_portal_multiplex.services.MultiplexServerService",
            )
            self.assertEqual(
                settings.PORTAL_SESSION_HANDLER_CLASS,
                "evennia_portal_multiplex.sessionhandler."
                "MultiplexPortalSessionHandler",
            )
            # Stashed, so a consumer's own class is not simply lost.
            self.assertEqual(
                settings._MULTIPLEX_ORIGINAL_PORTAL_SERVICE, portal_class
            )
            self.assertEqual(
                settings._MULTIPLEX_ORIGINAL_SERVER_SERVICE, server_class
            )
            self.assertEqual(
                settings._MULTIPLEX_ORIGINAL_SESSION_HANDLER, handler_class
            )

    def test_in_08_each_class_subclasses_what_the_consumer_had(self):
        """IN-08: a consumer's own class stays underneath ours."""
        portal_base = self._portal_base()
        handler_base = self._handler_base()
        self.assertTrue(
            issubclass(
                make_portal_service(portal_base, InstanceRegistry()), portal_base
            )
        )
        self.assertTrue(
            issubclass(make_session_handler(handler_base, InstanceRegistry()),
                       handler_base)
        )

    def test_in_09_all_three_share_one_registry(self):
        """IN-09: one object, passed to every factory that needs it.

        Two registries is not a visible failure. The AMP protocol records into
        the service's while the handler consults its own empty one, so every
        session routes to the default forever and nothing raises.

        Asserted at the installer, because that is where the guarantee lives —
        the handler's copy is a closure and not reachable from the class.
        """
        from django.apps import apps as django_apps
        from django.test import override_settings

        from evennia_portal_multiplex import services, sessionhandler

        config = django_apps.get_app_config("evennia_portal_multiplex")
        with override_settings(
            EVENNIA_PORTAL_SERVICE_CLASS=(
                "evennia.server.portal.service.EvenniaPortalService"
            ),
            EVENNIA_SERVER_SERVICE_CLASS=(
                "evennia.server.service.EvenniaServerService"
            ),
            PORTAL_SESSION_HANDLER_CLASS=(
                "evennia.server.portal.portalsessionhandler.PortalSessionHandler"
            ),
        ), mock.patch.object(
            services, "make_portal_service"
        ) as portal_factory, mock.patch.object(
            sessionhandler, "make_session_handler"
        ) as handler_factory:
            config.ready()

        portal_registry = portal_factory.call_args.args[1]
        handler_registry = handler_factory.call_args.args[1]
        self.assertIsInstance(portal_registry, InstanceRegistry)
        self.assertIs(portal_registry, handler_registry)

    def test_in_12_ready_layers_over_the_client_factory(self):
        """IN-12: no setting names this class, so the module is the handle.

        Order is the substance of this case. Layered before the patch, the
        patch would subclass ours and `buildProtocol` would still be Evennia's
        broken one — everything would look installed and the client protocol
        setting would go on being ignored.

        Restored afterwards: the module attribute is process-wide.
        """
        import inspect

        from django.apps import apps as django_apps
        from evennia.server import amp_client as evennias_module

        config = django_apps.get_app_config("evennia_portal_multiplex")
        original = evennias_module.AMPClientFactory
        try:
            config.ready()
            installed = evennias_module.AMPClientFactory
            self.assertEqual(installed.__name__, "MultiplexAMPClientFactory")
            # The patch is underneath, not on top: buildProtocol reads the
            # setting rather than naming the class.
            self.assertIn(
                "self.protocol()", inspect.getsource(installed.buildProtocol)
            )
        finally:
            evennias_module.AMPClientFactory = original

    def test_in_11_ready_layers_over_the_client_protocol(self):
        """IN-11: without this the startup check has nowhere to run.

        The same mechanism as the other three, and the one that depends on
        IN-10 having run first — the setting reaches nothing on an unpatched
        Evennia.
        """
        from django.apps import apps as django_apps
        from django.test import override_settings

        config = django_apps.get_app_config("evennia_portal_multiplex")
        evennias_own = "evennia.server.amp_client.AMPServerClientProtocol"
        with override_settings(AMP_CLIENT_PROTOCOL_CLASS=evennias_own):
            config.ready()
            self.assertEqual(
                settings.AMP_CLIENT_PROTOCOL_CLASS,
                "evennia_portal_multiplex.amp_client."
                "MultiplexAMPClientProtocol",
            )
            self.assertEqual(
                settings._MULTIPLEX_ORIGINAL_AMP_CLIENT_PROTOCOL, evennias_own
            )
            # The dotted path has to resolve to a real class: Evennia looks it
            # up by string, and a placeholder still holding None is an
            # unhelpful TypeError inside buildProtocol.
            from evennia_portal_multiplex import amp_client

            self.assertTrue(
                issubclass(
                    amp_client.MultiplexAMPClientProtocol,
                    class_from_module(evennias_own),
                )
            )

    def test_in_10_ready_installs_the_evennia_patch(self):
        """IN-10: without the call, AMP_CLIENT_PROTOCOL_CLASS stays ignored.

        Asserted on the factory's behaviour rather than on the call, because
        the guarantee is that the class Evennia will construct reads the
        setting — see PT-01. Checked by source, since the patched class is
        generated and there is no other stable identity to compare against.

        Restored afterwards: the module attribute is process-wide, and PT-04
        reads Evennia's own `buildProtocol` off it.
        """
        import inspect

        from django.apps import apps as django_apps
        from django.test import override_settings
        from evennia.server import amp_client

        config = django_apps.get_app_config("evennia_portal_multiplex")
        original = amp_client.AMPClientFactory
        try:
            with override_settings(
                EVENNIA_PORTAL_SERVICE_CLASS=(
                    "evennia.server.portal.service.EvenniaPortalService"
                ),
                EVENNIA_SERVER_SERVICE_CLASS=(
                    "evennia.server.service.EvenniaServerService"
                ),
                PORTAL_SESSION_HANDLER_CLASS=(
                    "evennia.server.portal.portalsessionhandler."
                    "PortalSessionHandler"
                ),
            ):
                config.ready()
            source = inspect.getsource(
                amp_client.AMPClientFactory.buildProtocol
            )
            self.assertIn("self.protocol()", source)
        finally:
            amp_client.AMPClientFactory = original


class TestPortalQuery(unittest.TestCase):
    """QY — asking the Portal which instances are attached."""

    def _base(self):
        """A stand-in for Evennia's AMP protocol.

        Carries what `make_amp_protocol`'s overrides call through to. Not a
        CommandLocator — QY-07 uses Evennia's real class, because the dispatch
        table is the thing under test there.
        """

        class FakeAMPProtocol:
            def data_in(self, packed_data):
                return packed_data

            def portal_receive_adminserver2portal(self, packed_data):
                return None

            def connectionLost(self, reason):
                return None

        return FakeAMPProtocol

    def _protocol(self, *names):
        registry = InstanceRegistry()
        for name in names:
            registry.register(name, mock.Mock(name=name))
        return make_amp_protocol(self._base(), registry)(), registry

    def _attached(self, protocol):
        return amp_module.loads(
            protocol.portal_receive_query_registry()["attached"]
        )

    def test_qy_01_answers_with_every_attached_instance(self):
        """QY-01: the fact only the Portal holds."""
        protocol, _registry = self._protocol("first", "second")
        self.assertEqual(self._attached(protocol), ["first", "second"])

    def test_qy_02_an_empty_portal_answers_with_an_empty_list(self):
        """QY-02: nothing attached is an answer, not a failure."""
        protocol, _registry = self._protocol()
        self.assertEqual(self._attached(protocol), [])

    def test_qy_03_reads_the_registry_when_the_question_arrives(self):
        """QY-03: not a copy taken when the protocol class was built.

        A captured list would read correctly on the first query and be wrong
        on every one after — the shape that looks like it works.
        """
        protocol, registry = self._protocol("first")
        self.assertEqual(self._attached(protocol), ["first"])
        registry.register("second", mock.Mock())
        self.assertEqual(self._attached(protocol), ["first", "second"])

    def test_qy_05_a_server_asking_receives_the_decoded_answer(self):
        """QY-05: what comes back is data, not a line in a log."""
        connection = mock.Mock()
        connection.callRemote.return_value = defer.succeed(
            {"attached": amp_module.dumps(["first", "second"])}
        )
        received = []
        query_registry(connection).addCallback(received.append)
        self.assertEqual(received, [["first", "second"]])
        self.assertEqual(
            connection.callRemote.call_args.args[0], MultiplexQueryRegistry
        )

    def test_qy_07_the_responder_is_registered_under_the_commands_key(self):
        """QY-07: forget the decorator and the method is never called.

        Nothing raises: it sits on the class, AMP routes by its own table, and
        the query fails as an unhandled command. QY-01 would not catch it,
        because it calls the method directly.
        """
        from evennia.server.portal.amp_server import AMPServerProtocol

        generated = make_amp_protocol(AMPServerProtocol, InstanceRegistry())
        key = MultiplexQueryRegistry.commandName
        _command, responder = generated._commandDispatch[key]
        self.assertIs(responder, generated.portal_receive_query_registry)


class TestSelfRegistration(unittest.TestCase):
    """SR — an instance checking its own registration."""

    def _me(self, name):
        """This instance's configured name, as `config` resolves it."""
        return mock.patch(
            "evennia_portal_multiplex.query.get_instance_id", return_value=name
        )

    def test_sr_01_true_when_this_instance_is_in_the_answer(self):
        """SR-01: the announcement landed."""
        with self._me("second"):
            self.assertTrue(am_i_registered(["first", "second"]))

    def test_sr_02_false_when_it_is_not(self):
        """SR-02: the handshake did not take, which nothing else would say."""
        with self._me("second"):
            self.assertFalse(am_i_registered(["first", "third"]))
            self.assertFalse(am_i_registered([]))


class TestStartupCheck(unittest.TestCase):
    """ST — the startup check."""

    def _me(self, name):
        """Patch both lookups.

        `query` resolves this instance's name to answer the check; `startup`
        resolves it again to name it in the failure. Each imported the name,
        so each holds its own reference — the same shape as _patch_default.
        """
        query_patch = mock.patch(
            "evennia_portal_multiplex.query.get_instance_id", return_value=name
        )
        startup_patch = mock.patch(
            "evennia_portal_multiplex.startup.get_instance_id", return_value=name
        )

        class _Both:
            def __enter__(self):
                query_patch.start()
                startup_patch.start()
                return self

            def __exit__(self, *exc):
                startup_patch.stop()
                query_patch.stop()
                return False

        return _Both()

    def _log(self):
        return mock.patch("evennia_portal_multiplex.startup.portal_multiplex_log")

    def test_st_02_logs_before_it_raises(self):
        """ST-02: the exception may be caught; the line stays."""
        with self._me("second"), self._log() as logged:
            with self.assertRaises(NotRegistered):
                check_registration(["first", "third"])
        self.assertTrue(logged.called)

    def test_st_03_an_unregistered_instance_does_not_start(self):
        """ST-03: raised, not returned — a Server nobody can reach is not up.

        And it returns quietly when the instance *is* there, so the check is
        invisible on the ordinary path.
        """
        with self._me("second"), self._log():
            with self.assertRaises(NotRegistered):
                check_registration(["first"])
            self.assertIsNone(check_registration(["first", "second"]))

    def test_st_04_the_failure_names_this_instance_and_the_answer(self):
        """ST-04: enough in the line to act on without reading the code."""
        with self._me("second"), self._log():
            with self.assertRaises(NotRegistered) as raised:
                check_registration(["first", "third"])
        message = str(raised.exception)
        self.assertIn("second", message)
        self.assertIn("first", message)
        self.assertIn("third", message)


class TestAmpClientProtocol(unittest.TestCase):
    """CP — the Server's AMP client protocol."""

    def _base(self, events):
        """A stand-in for Evennia's AMP client protocol.

        Its `connectionMade` is what sends `PSYNC`, so it records that it ran
        — CP-01 is about the order, not the content.
        """

        class FakeClientProtocol:
            def connectionMade(self):
                events.append("handshake")

        return FakeClientProtocol

    def _protocol(self, events, attached=("me",)):
        """A built protocol, with the query and the check stood in for.

        The query returns a Deferred already fired, because what this unit
        does with the answer is the point and Twisted's reactor is not.
        """
        protocol = make_amp_client_protocol(self._base(events))()
        query = mock.patch(
            "evennia_portal_multiplex.amp_client.query_registry",
            side_effect=lambda connection: (
                events.append("query") or defer.succeed(list(attached))
            ),
        )
        check = mock.patch(
            "evennia_portal_multiplex.amp_client.check_registration"
        )
        return protocol, query, check

    def _failing(self, error):
        """A built protocol whose check raises `error`, with the reactor faked.

        Returns the protocol, the patched reactor and the patched log, so a
        case can assert on what was said and on what was stopped.
        """
        protocol = make_amp_client_protocol(self._base([]))()
        return protocol, mock.patch(
            "evennia_portal_multiplex.amp_client.query_registry",
            side_effect=lambda connection: defer.succeed(["somebody-else"]),
        ), mock.patch(
            "evennia_portal_multiplex.amp_client.check_registration",
            side_effect=error,
        ), mock.patch(
            "evennia_portal_multiplex.amp_client.reactor"
        ), mock.patch(
            "evennia_portal_multiplex.amp_client.portal_multiplex_log"
        )

    def test_cp_05_a_failure_stops_the_reactor(self):
        """CP-05: raising alone is not a refusal.

        Twisted logs the traceback out of `connectionMade` and the reactor
        carries on, which leaves a Server running that nobody can reach — the
        exact state the check exists to prevent.
        """
        protocol, query, check, reactor, _log = self._failing(
            NotRegistered("not in the list")
        )
        with query, check, reactor as reactor_mock, _log:
            protocol.connectionMade()
        reactor_mock.stop.assert_called_once()

    def test_cp_06_the_reason_is_logged_before_the_shutdown(self):
        """CP-06: the log is the only place the reason survives.

        The launcher says *that* it failed at the terminal (LC-06); nothing
        carries *why* across the process boundary, so it has to be on disk
        before the reactor comes down.
        """
        protocol, query, check, reactor, log = self._failing(
            NotRegistered("'shard1' is not registered with its Portal")
        )
        with query, check, reactor, log as logging:
            protocol.connectionMade()
        message, kwargs = logging.call_args.args[0], logging.call_args.kwargs
        self.assertIn("shard1", message)
        self.assertEqual(kwargs.get("level"), "ERROR")

    def test_cp_07_a_portal_without_the_library_is_named_as_that(self):
        """CP-07: a different fix from an announcement that did not land.

        Both refuse. Reading the same in the log would send somebody looking
        at instance ids when the Portal simply is not running this library.
        """
        from twisted.protocols.amp import UnhandledCommand

        protocol, query, check, reactor, log = self._failing(
            UnhandledCommand("MultiplexQueryRegistry")
        )
        with query, check, reactor as reactor_mock, log as logging:
            protocol.connectionMade()
        self.assertIn(
            "not running", " ".join(str(a) for a in logging.call_args.args)
        )
        reactor_mock.stop.assert_called_once()

    def test_cp_09_the_refusal_exits_non_zero(self):
        """CP-09: a process manager decides by exit code.

        Zero reads as "stopped cleanly, leave it", which after a reboot is
        wrong: the instance holding the Portal may simply not be listening
        yet, and a retry would succeed.

        Registered after shutdown, so it runs once the services are down and
        the log has flushed — the log is the only place the reason exists.
        """
        protocol, query, check, reactor, log = self._failing(
            NotRegistered("not in the list")
        )
        with query, check, reactor as reactor_mock, log:
            protocol.connectionMade()

        when, event, exiting = reactor_mock.addSystemEventTrigger.call_args.args
        self.assertEqual((when, event), ("after", "shutdown"))
        with mock.patch("os._exit") as underlying:
            exiting()
        underlying.assert_called_once_with(1)

    def test_cp_08_a_successful_check_stops_nothing(self):
        """CP-08: the errback is reached by failures and nothing else."""
        protocol = make_amp_client_protocol(self._base([]))()
        with mock.patch(
            "evennia_portal_multiplex.amp_client.query_registry",
            side_effect=lambda connection: defer.succeed(["me"]),
        ), mock.patch(
            "evennia_portal_multiplex.amp_client.check_registration"
        ), mock.patch(
            "evennia_portal_multiplex.amp_client.reactor"
        ) as reactor_mock:
            protocol.connectionMade()
        reactor_mock.stop.assert_not_called()

    def test_cp_01_the_handshake_is_sent_before_the_query(self):
        """CP-01: query first and the Portal has not been told who this is.

        The answer would be "not registered" every time, and every Server
        would refuse to start.
        """
        events = []
        protocol, query, check = self._protocol(events)
        with query, check:
            protocol.connectionMade()
        self.assertEqual(events, ["handshake", "query"])

    def test_cp_02_the_query_goes_down_this_connection(self):
        """CP-02: the same connection the handshake went down.

        A query on any other connection loses the ordering guarantee that
        makes one check enough — see ST.
        """
        events = []
        protocol, query, check = self._protocol(events)
        with query as querying, check:
            protocol.connectionMade()
        self.assertIs(querying.call_args.args[0], protocol)

    def test_cp_03_the_answer_is_handed_to_the_check(self):
        """CP-03: querying and not reading the answer checks nothing."""
        events = []
        protocol, query, check = self._protocol(events, attached=("me", "you"))
        with query, check as checking:
            protocol.connectionMade()
        self.assertEqual(checking.call_args.args[0], ["me", "you"])

    def test_cp_04_subclasses_whatever_the_setting_named(self):
        """CP-04: a consumer's own protocol class stays underneath ours."""
        base = self._base([])
        self.assertTrue(issubclass(make_amp_client_protocol(base), base))


class TestAmpClientFactory(unittest.TestCase):
    """FC — the Server's AMP client factory."""

    def _base(self, calls):
        """Evennia's factory, reduced to the method being layered over."""

        class FakeAMPClientFactory:
            def clientConnectionFailed(self, connector, reason):
                calls.append((connector, reason))

        return FakeAMPClientFactory

    def _connector(self, host="10.0.1.7", port=4006):
        """A Twisted connector, which is where the address comes from."""
        connector = mock.Mock()
        connector.getDestination.return_value = mock.Mock(host=host, port=port)
        return connector

    def _fail(self, calls):
        """Report a failed connection attempt, with the log captured."""
        factory = make_amp_client_factory(self._base(calls))()
        with mock.patch(
            "evennia_portal_multiplex.amp_client.portal_multiplex_log"
        ) as logging:
            factory.clientConnectionFailed(self._connector(), "no route to host")
        return logging

    def test_fc_01_the_address_that_could_not_be_reached_is_logged(self):
        """FC-01, and ST-05: Evennia's own line names no address.

        With one Server there is only one Portal it could mean. With several
        instances and a mistyped AMP_HOST, "attempting to reconnect" says
        nothing about which one is wrong.
        """
        logging = self._fail([])
        message = logging.call_args.args[0]
        self.assertIn("10.0.1.7", message)
        self.assertIn("4006", message)

    def test_fc_02_the_retry_still_happens(self):
        """FC-02: the backoff is Twisted's and is the right behaviour.

        A Portal that is not up yet usually will be shortly. This adds a line
        to the log and changes nothing else.
        """
        calls = []
        self._fail(calls)
        self.assertEqual(len(calls), 1)

    def test_fc_03_subclasses_whatever_is_bound(self):
        """FC-03: not `PatchedAMPClientFactory` by name.

        Naming the patched class would make the patch load-bearing, and it
        exists to be deleted when Evennia fixes the bug.
        """
        base = self._base([])
        self.assertTrue(issubclass(make_amp_client_factory(base), base))


class TestEvenniaPatch(unittest.TestCase):
    """PT — a local patch for an Evennia bug."""

    def _configured(self):
        """A protocol class standing in for whatever the setting names."""

        class ConfiguredProtocol:
            pass

        return ConfiguredProtocol

    def _base(self, configured):
        """Evennia's factory, reduced to the parts buildProtocol touches."""

        class FakeAMPClientFactory:
            def __init__(self, server):
                self.server = server
                self.protocol = configured
                self.reset_calls = 0

            def resetDelay(self):
                self.reset_calls += 1

        return FakeAMPClientFactory

    def test_pt_01_builds_the_class_the_setting_names(self):
        """PT-01: the whole point — the setting is honoured again."""
        configured = self._configured()
        factory = make_patched_factory(self._base(configured))(mock.Mock())
        self.assertIsInstance(factory.buildProtocol(None), configured)

    def test_pt_02_install_replaces_the_factory_evennia_will_construct(self):
        """PT-02: service.py looks the name up at call time, so this reaches it."""
        from evennia.server import amp_client

        original = amp_client.AMPClientFactory
        try:
            install()
            self.assertIsNot(amp_client.AMPClientFactory, original)
            self.assertTrue(issubclass(amp_client.AMPClientFactory, original))
        finally:
            amp_client.AMPClientFactory = original

    def test_pt_03_does_everything_evennias_buildprotocol_did(self):
        """PT-03: we reimplement it, so it has to do the same bookkeeping.

        Miss the reconnect-delay reset and a flapping connection stops backing
        off; miss the assignment and the Server has no protocol to send on.
        """
        configured = self._configured()
        server = mock.Mock()
        factory = make_patched_factory(self._base(configured))(server)

        built = factory.buildProtocol(None)

        self.assertEqual(factory.reset_calls, 1)
        self.assertIs(server.amp_protocol, built)
        self.assertIs(built.factory, factory)

    def test_pt_04_canary_evennias_factory_still_ignores_the_setting(self):
        """PT-04: passes while the bug exists. Failing here is good news.

        When this goes red, Evennia has been fixed and `evennia_patch` should
        be deleted along with its call in AppConfig.ready().

        **Read Evennia's own class, not whatever is currently bound.**
        `AppConfig.ready()` runs during `django.setup()` — which the test
        bootstrap does — so by the time any test runs, `install()` has already
        rebound `amp_client.AMPClientFactory` to our subclass. Inspecting the
        module attribute would read *our* `buildProtocol` and report the bug
        fixed, which is the one wrong answer this test must never give.

        The patched class subclasses whatever was bound, so Evennia's own class
        is always in the MRO. Finding it by module works patched,
        double-patched or not patched at all, and a class that moved module
        raises `StopIteration` rather than quietly matching nothing.
        """
        import inspect

        from evennia.server import amp_client

        evennias_own = next(
            klass
            for klass in amp_client.AMPClientFactory.__mro__
            if klass.__module__ == "evennia.server.amp_client"
        )
        source = inspect.getsource(evennias_own.buildProtocol)
        self.assertIn("AMPServerClientProtocol()", source)
        self.assertNotIn("self.protocol()", source)
