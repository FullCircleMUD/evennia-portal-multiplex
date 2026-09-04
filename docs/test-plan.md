# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it. Every test
function carries its case ID as its docstring, so the trail reads in both directions.

All test functions live in `src/evennia_portal_multiplex/tests.py`.

Behaviour is agreed here first, before any test or code — see
[test-first-process.md](../../../design/test-first-process.md).

| Prefix | Covers |
|---|---|
| `AR` | The AMP responder that records an announcement |
| `IA` | An instance announcing its name to the Portal |
| `IN` | Installing the machinery into a running Evennia |
| `IR` | The instance registry — which AMP connection belongs to which instance |
| `LC` | Launcher commands the library adds to `evennia` |
| `MV` | Moving a session between instances |
| `RT` | Routing one send to one instance |
| `SB` | Which instance a session belongs to |

## Fixtures

The fake objects the suite needs, named and purposed.

| Fixture | Purpose |
|---|---|
| `_patch_default()` | Patches the default-instance lookup in both `binding` and `registry`. Each imported the name, so each holds its own reference |

## Cases

One section per function or surface, each with its own prefix and its own table.

### IR — the instance registry

A Portal serving more than one Server needs to know which AMP connection belongs to which instance.
Evennia keeps a single `portal.amp_protocol` and a single `factory.server_connection`, both of which
name whichever Server attached or spoke most recently — so with two Servers attached there is nothing
that distinguishes them, and everything lands on the last one to speak.

The registry is that distinction and nothing more: a mapping from instance id to live connection. It
holds no session state, makes no routing decisions and sends nothing. Everything above it — routing a
send, moving a session — asks it which connection a name resolves to.

**An instance names itself.** The id comes from `MULTIPLEX_INSTANCE_ID`, declared by this library so
it depends on nothing but Evennia. A consumer that already names its instances aliases that setting,
keeping one name across whatever else it runs. An instance announces the name in the `info_dict` it
already sends on its `PSYNC` handshake, and the registry records it against the connection that
handshake arrived on.

**Removal is by connection, not by name.** On disconnect the connection is what is in hand, and a
reconnecting instance can register its replacement before the old connection's loss is noticed. Deleting
by name would then delete the live entry and leave the instance unreachable while it is in fact attached.

| ID | Case | Test function |
|---|---|---|
| IR-01 | Registering a connection under an instance id makes it retrievable by that id | test_ir_01_registers_a_connection_under_its_instance_id |
| IR-02 | An instance that reconnects replaces its own entry rather than adding a second | test_ir_02_reconnecting_replaces_rather_than_duplicates |
| IR-03 | Registering without an instance id records nothing — most admin messages carry none | test_ir_03_registering_without_an_id_records_nothing |
| IR-04 | A connection that drops is removed from the registry | test_ir_04_a_dropped_connection_is_removed |
| IR-05 | Removal is by connection identity, so a stale disconnect cannot delete the entry that replaced it | test_ir_05_a_stale_disconnect_cannot_delete_its_replacement |
| IR-06 | Looking up an instance that is not attached is distinguishable from one that is | test_ir_06_an_unattached_instance_returns_none |
| IR-07 | The default instance is retrievable by role, without a caller having to know its configured id | test_ir_07_the_default_instance_is_retrievable_by_role |
| IR-08 | The registry can report every attached instance, so what a Portal holds can be inspected | test_ir_08_reports_every_attached_instance |
| IR-09 | A Portal whose default instance has not attached has no default connection | test_ir_09_default_connection_is_none_when_it_is_not_attached |

### IA — announcing an instance's name

The registry can only tell connections apart if each Server says who it is. Evennia already gives it
somewhere to say so: a Server assembles an `info_dict` as it boots and sends it to the Portal with its
`PSYNC` handshake, where it is stored and read back by the launcher for the lines printed at startup.
Nothing depends on its contents, so adding a key is safe, and the message already crosses — no new
protocol, no second round trip.

The name is `MULTIPLEX_INSTANCE_ID`, read through `config.get_instance_id`.

**No defensive handling around resolving it.** That lookup raises when the setting is unset, and it is
meant to: two Servers attaching to one Portal without distinct names is not a state to continue from.
Swallowing it here would hide the misconfiguration at the one moment the Portal is deciding who it is
talking to, and the symptom would surface much later as sessions arriving at the wrong instance.

**The returned dict is a copy.** Evennia's `get_info_dict` hands back the live `info_dict` off the
service, so writing into it mutates what the service holds — the key would accumulate across calls and
appear in Evennia's own view of its state. Copying keeps the announcement to the wire.

| ID | Case | Test function |
|---|---|---|
| IA-01 | The instance id is announced under the library's key | test_ia_01_announces_the_instance_id |
| IA-02 | Everything Evennia's own `info_dict` carried is still there | test_ia_02_leaves_evennias_own_keys_intact |
| IA-03 | The service's stored `info_dict` is left unmutated, so repeated calls do not accumulate | test_ia_03_does_not_mutate_the_services_own_dict |
| IA-04 | The generated class subclasses whatever service class the consumer had configured | test_ia_04_subclasses_the_consumers_service_class |

### AR — recording an announcement

The Portal side of IA. A Server announces its name on the `PSYNC` handshake; this is what hears it and
writes it into the registry, against the connection the message arrived on. It also drops a connection
from the registry when it is lost.

**An AMP responder must be re-registered, not overridden.** Twisted builds `_commandDispatch` as a
class attribute when the class is created, mapping each command to the function its
`@Command.responder` decorator was applied to. A subclass inherits that table and, unless it applies
the decorator itself, the entry still points at the *parent's* function. So an ordinary override
compiles, installs, sits on the instance, and is never called — with nothing raised and nothing logged.
That is not a subtlety to note in passing; it is the failure mode this whole section exists to pin
down, and AR-07 is the case that catches it.

The decision is kept out of the responder. Given the unpacked message, deciding what the registry
should do is plain data handling and is tested as such; the responder itself unpacks, delegates, and
calls `super()`. Registering an absent name is already a no-op (IR-03), so there is no second guard.

| ID | Case | Test function |
|---|---|---|
| AR-01 | A message announcing a name registers that connection under it | test_ar_01_an_announcement_registers_the_connection |
| AR-02 | A message carrying no `info_dict` registers nothing | test_ar_02_a_message_without_an_info_dict_registers_nothing |
| AR-03 | An `info_dict` without the library's key registers nothing | test_ar_03_an_info_dict_without_our_key_registers_nothing |
| AR-04 | Evennia's own handling of the message still runs, and its return value is passed back | test_ar_04_evennias_own_handling_still_runs |
| AR-05 | A connection that is lost is forgotten | test_ar_05_a_lost_connection_is_forgotten |
| AR-06 | Losing a connection still calls Evennia's own `connectionLost` | test_ar_06_losing_a_connection_still_calls_the_base |
| AR-07 | The responder is registered in the subclass's own dispatch table, not inherited from the base | test_ar_07_the_responder_is_registered_not_merely_overridden |
| AR-08 | The generated class subclasses whatever protocol class the factory was given | test_ar_08_subclasses_the_class_it_was_given |

### RT — routing a send

Every message the Portal sends to a Server goes through `AMPServerProtocol.data_to_server`, and that
method **ignores the connection object it was called on**:

    if self.factory.server_connection:
        return self.factory.server_connection.callRemote(...)

So `connection.send_AdminPortal2Server(...)` does not send to `connection`. It sends to whatever
`factory.server_connection` holds — and Evennia assigns that on *every* inbound admin message, so it
names whichever Server spoke most recently. With one Server that is always the right answer and the
indirection is invisible. With two it is never reliably the right answer.

Routing is therefore not choosing which object to call. It is pointing that one reference at the
instance we mean, for the duration of one call, and putting it back.

Safe because the Portal is a single-threaded reactor: nothing else runs between the swap and the
restore. That is a property of the environment rather than of this code, so it is worth stating
plainly — on a threaded portal this approach would be wrong.

**`portal.amp_protocol` is deliberately not touched.** `data_in` and `connect` read it only to check it
is truthy before sending; the send itself goes through `data_to_server`. Swapping it as well was tried
and proved unnecessary, and RT-05 keeps that a decision rather than something that quietly comes back.

| ID | Case | Test function |
|---|---|---|
| RT-01 | While routed, the Portal's outbound reference names the given connection | test_rt_01_points_the_outbound_reference_at_the_connection |
| RT-02 | Whatever the reference held before is restored afterwards | test_rt_02_restores_what_was_there_before |
| RT-03 | It is restored even when the wrapped call raises | test_rt_03_restores_even_when_the_block_raises |
| RT-04 | Routing to nothing leaves Evennia's own choice untouched, rather than clearing it | test_rt_04_routing_to_nothing_leaves_evennias_choice_alone |
| RT-05 | `portal.amp_protocol` is not written to | test_rt_05_does_not_write_to_amp_protocol |

### SB — which instance a session belongs to

Routing points one send at one instance; this is what decides which instance that is for a given
session. It is the only per-session state the Portal keeps, and it holds a **name**, not a connection.

**A name, because a connection goes stale.** The Portal deliberately outlives Servers — that is how
`reload` works, and why a telnet session survives one. A Server that restarts comes back on a *new*
AMP connection, and the registry replaces its entry. A session holding the old connection object would
then be writing into a dead one, silently; a session holding the name follows the replacement without
noticing. The lookup that costs is a dict access against a message that has already crossed a socket.

**An unbound session belongs to the default instance.** Not to "whatever Evennia's global happens to hold" — that
names whichever Server attached most recently, so a player connecting to the default instance while an instance is
starting would be handed to the instance. The default has to be a decision rather than a leftover.

**The binding and the fallback come from the same place.** Asking "where is this session" and asking
"where does this session's traffic go" must give one answer. The spike had them reading different
variables, and they agreed only for as long as both were maintained — when one stopped being written,
a session reported itself as being wherever the newest instance was while its traffic went to the default instance.
Nothing failed; the two questions simply diverged. Both resolve through the registry here.

| ID | Case | Test function |
|---|---|---|
| SB-01 | A session with no binding belongs to the default instance | test_sb_01_an_unbound_session_belongs_to_the_default |
| SB-02 | Binding a session to an instance is what it then belongs to | test_sb_02_a_bound_session_belongs_where_it_was_bound |
| SB-03 | The binding is stored as a name, so a reconnecting instance is followed rather than a dead connection held | test_sb_03_follows_an_instance_that_reconnects |
| SB-04 | A session bound to an instance that is not attached falls back to the default instance rather than to nothing | test_sb_04_falls_back_to_the_default_when_not_attached |
| SB-05 | Binding one session leaves every other session's binding alone | test_sb_05_binding_one_session_leaves_others_alone |

### MV — moving a session between instances

The act itself. Changing a session's binding alone only points its traffic at a Server that has never
heard of it; the move is what makes the destination have a session to receive it.

Three steps, no socket operations anywhere in them:

1. `PDISCONN` to the instance being left, so its Server releases the session.
2. Clear the identity fields, and rebind.
3. `PCONN` to the destination, carrying the session's sync data, so its Server builds one.

Sent directly rather than through `sessionhandler.disconnect()` and `.connect()`: those also drop the
session from the Portal's own handler and close the transport, which is the one thing this must not do.

**Clearing `uid`, `logged_in` and `puid` is not optional.** All three are on `SESSION_SYNC_ATTRS`, and
all three are primary keys belonging to the Server being left. Carried across, the destination believes
the session is already authenticated as whatever account holds that id over there — which is a
different person, or nobody. The spike left them in place deliberately so a test session stayed logged
in, and it appeared to work only because both demo databases number their superuser identically. That
coincidence is the hazard the case exists to remove.

**Each send is routed.** `data_to_server` sends via `factory.server_connection` regardless of which
connection object the method is called on, so calling `send_AdminPortal2Server` on the destination
decides nothing by itself. Both sends are wrapped in `sending_to`.

**The two ends are independent.** `PDISCONN` and `PCONN` are separate messages to separate Servers, so
the destination can build its session before the origin has released its own. Nothing here may assume
the release completes first.

| ID | Case | Test function |
|---|---|---|
| MV-01 | The instance being left is sent `PDISCONN` for that session | test_mv_01_the_instance_being_left_is_released |
| MV-02 | The destination is sent `PCONN` carrying the session's sync data | test_mv_02_the_destination_is_given_the_session |
| MV-03 | `uid`, `logged_in` and `puid` are cleared before the destination is told | test_mv_03_identity_is_cleared_before_the_destination_is_told |
| MV-04 | The session is rebound to the destination | test_mv_04_the_session_is_rebound |
| MV-05 | Each send is routed to its own instance rather than left to Evennia's global | test_mv_05_each_send_is_routed_to_its_own_instance |
| MV-06 | Moving to an instance that is not attached does nothing and reports it | test_mv_06_an_unattached_destination_refuses |
| MV-07 | Moving to where the session already is does nothing | test_mv_07_moving_to_where_it_already_is_does_nothing |
| MV-08 | The session's transport is never touched — no disconnect, no close | test_mv_08_the_transport_is_never_touched |

### LC — launcher commands

An instance runs a Server attached to another instance's Portal, and no stock launcher verb starts one.
`start` brings up a Portal as well, which collides on the AMP port. `istart` tells the Portal to stop
its current Server before starting its own — so on a shared Portal, starting a second Server shuts down the first. That is not a quirk to work around: it is `istart` doing exactly what it is for.

`server_start` does the two things `istart` does that we want and omits the one we do not. It asks
Evennia for the twistd command it would use for this gamedir, and runs it. Nothing is sent to any
Portal, so whatever Servers are already attached stay attached.

It reaches the launcher through Evennia's own extension point, named in the consumer's settings::

    EXTRA_LAUNCHER_COMMANDS = {"server_start": "evennia_portal_multiplex.launcher.server_start"}

The launcher resolves the gamedir and settings before it looks for custom commands, so the callable
runs with the launcher's own globals already populated — which is what makes reusing its command
construction possible rather than reimplementing it.

**The command is borrowed, not rebuilt.** `_get_twistd_cmdline` is private, and using it accepts that
an Evennia upgrade could move it. The alternative is our own copy of the twistd invocation, which goes
stale silently the first time Evennia changes theirs; a borrowed private helper at least breaks loudly.

| ID | Case | Test function |
|---|---|---|
| LC-01 | `server_start` runs the Server command Evennia's own launcher would build, rather than one assembled here | test_lc_01_runs_the_command_evennia_would_build |
| LC-02 | It runs the Portal's command under no circumstances — `_get_twistd_cmdline` returns both, and only the Server's is wanted | test_lc_02_never_runs_the_portals_command |
| LC-03 | The process is started with the launcher's environment, so the gamedir and settings reach the child | test_lc_03_runs_it_with_the_launchers_environment |
| LC-04 | Nothing is sent to a Portal — no instruction is issued, so an attached Server is not stopped | test_lc_04_sends_nothing_to_a_portal |
| LC-05 | The callable is importable at the dotted path a consumer names in `EXTRA_LAUNCHER_COMMANDS` | test_lc_05_resolves_at_the_configured_dotted_path |


## Open decisions

Open questions land here as `[TBD — needs discussion: …]` against the specific case they block,
collected in this section. A case with open behaviour is still listed, but it does not pass.

### IN — installation

What makes any of the preceding sections run. Nothing above this imports anything else in the library:
the registry is passed in, the routing is a context manager, the move takes a registry and a session.
This is where they are joined and handed to Evennia.

**A library's only way into the Portal process is `AppConfig.ready()`.** There is no plugin registry it
can join — `PORTAL_SERVICES_PLUGIN_MODULES` names a gamedir module, so a consumer would have to wire it
themselves. `ready()` runs during `django.setup()`, and Evennia resolves these class settings later in
`_init()`, so repointing them there is early enough and nothing needs patching at runtime.

**One registry, created in `ready()` and passed to all three.** The Portal service holds it, the AMP
protocol writes into it, the session handler reads from it — and they must be the same object. A
service that built its own would be recorded into while the handler consulted an empty one, so every
session would route to the default forever and nothing would fail. Every factory that needs the
registry takes it as an argument for exactly that reason. Module state would also work, and would leak
between tests.

**`register_amp` calls `super()` first.** The factory does not exist until it has. Patching before is
not a wrong order that fails loudly; it is an `AttributeError` on a factory that is not there, and a
Portal that runs perfectly while recording nothing.

**`data_in` is wrapped, never replaced.** Evennia's applies a character limit, a command-rate limit,
`clean_senddata` and a local echo before sending. Replacing it and sending directly puts a malformed
message on the wire, which surfaces inside the Server's input handling as `too many values to unpack` —
nowhere near the cause.

| ID | Case | Test function |
|---|---|---|
| IN-01 | The Portal service holds the registry it was given, for the life of the process | test_in_01_the_portal_service_holds_the_registry_it_was_given |
| IN-02 | `register_amp` puts the recording protocol class on the AMP factory | test_in_02_register_amp_puts_our_protocol_on_the_factory |
| IN-03 | `register_amp` calls `super()` before touching the factory, which does not exist until then | test_in_03_register_amp_calls_super_first |
| IN-04 | The session handler sends a session's input to the instance it is bound to | test_in_04_input_goes_to_the_instance_the_session_is_bound_to |
| IN-05 | The session handler calls `super()`, so Evennia's own preprocessing still runs | test_in_05_the_handler_calls_the_base |
| IN-06 | An unbound session's input goes to the default instance | test_in_06_an_unbound_session_goes_to_the_default |
| IN-07 | `ready()` stashes the class each setting named before repointing it | test_in_07_ready_stashes_and_repoints_each_setting |
| IN-08 | Each generated class subclasses whatever the consumer had configured | test_in_08_each_class_subclasses_what_the_consumer_had |
| IN-09 | The Portal service, the AMP protocol and the session handler share one registry | test_in_09_all_three_share_one_registry |
