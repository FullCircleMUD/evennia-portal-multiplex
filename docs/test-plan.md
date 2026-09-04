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
| `PT` | A local patch for an Evennia bug |
| `QY` | Asking the Portal about its state |
| `RT` | Routing one send to one instance |
| `SR` | An instance checking its own registration |
| `ST` | The startup check that acts on it |
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

**A build that fails puts the session back.** The origin has already let go by then, so a session left
alone is a player connected to no Server at all. Instead the identity captured before it was cleared
is restored, the session is rebound to the origin, and the same build step runs again pointing there.

That rollback is the build step, not a second path. The one thing it varies is whether the identity is
wiped or supplied — wiped moving away, supplied coming back. Nothing is sent to the destination, which
never built anything to release.

**Rebuilding on the origin is Evennia's own reload.** When a Server reconnects, the Portal hands back
every session's sync data and they come back logged in and re-puppeted. Restoring `uid`, `logged_in`
and `puid` and sending `PCONN` is the same operation on one session, which is why it can be relied on
rather than hoped for.

**Release first, then build — not the other way round.** Building at the destination before releasing
the origin would avoid stranding anyone, but it leaves a window where the session exists on two Servers
at once; a release that then failed would leave a ghost standing in the origin's world. Releasing first
trades that for a stranded player, which the rollback recovers.

**Knowing the build failed makes the move asynchronous.** The Deferred behind each send is what says
whether the far end took the message, so the move resolves to its outcome rather than returning it. A
responder can return a Deferred, so the command's reply waits on it.

**One shape for every outcome.** Moved, already there, and refused all come back the same way, through
the Deferred. The destination check still runs first and still stops everything else — what it does
not do is answer by a different route from the answers that had to wait. A caller with one way to
receive an outcome cannot forget which failures arrive which way.

**Five outcomes, named.** `MOVED`, `ALREADY_THERE`, `NOT_ATTACHED`, `REJECTED`, `STRANDED`. A boolean
cannot carry them, and the consumer decides what each one means for the game — a refusal might be a
message to the player, a retry, or nothing at all. They cross to the Server as the command's declared
response, unchanged.

The names describe what happened to the session, not what this library did about it. A destination
that would not take the session **rejected** it; that we then put the session back is bookkeeping the
consumer has no use for. `STRANDED` is the one that has no recovery: released by the origin, refused
by the destination, and the origin would not take it back either.

**The move resolves to `(moved, outcome)`.** `moved` is true for `MOVED` and nothing else — including
`ALREADY_THERE`, which is a consumer asking to send a session where it already is, and so a bug in
their logic worth surfacing rather than a quiet success.

**A rollback that also fails is logged and left.** Both Servers unreachable in the same instant is a
different failure, and there is nowhere left to put the session. The player reconnects.

| ID | Case | Test function |
|---|---|---|
| MV-01 | The instance being left is sent `PDISCONN` for that session | test_mv_01_the_instance_being_left_is_released |
| MV-02 | The destination is sent `PCONN` carrying the session's sync data | test_mv_02_the_destination_is_given_the_session |
| MV-03 | `uid`, `logged_in` and `puid` are cleared before the destination is told | test_mv_03_identity_is_cleared_before_the_destination_is_told |
| MV-04 | The session is rebound to the destination | test_mv_04_the_session_is_rebound |
| MV-05 | Each send is routed to its own instance rather than left to Evennia's global | test_mv_05_each_send_is_routed_to_its_own_instance |
| MV-06 | Moving to an instance that is not attached does nothing and reports it, through the same Deferred as every other outcome | test_mv_06_an_unattached_destination_refuses |
| MV-07 | Moving to where the session already is does nothing | test_mv_07_moving_to_where_it_already_is_does_nothing |
| MV-08 | The session's transport is never touched — no disconnect, no close | test_mv_08_the_transport_is_never_touched |
| MV-09 | The move resolves to its outcome rather than returning it, so a failed build can be acted on | test_mv_09_the_move_resolves_to_its_outcome |
| MV-10 | A destination that fails to build puts the session back on the origin, with the identity it had | test_mv_10_a_failed_build_puts_the_session_back |
| MV-11 | The rollback sends nothing to the destination, which never built anything to release | test_mv_11_the_rollback_leaves_the_destination_alone |
| MV-12 | A rollback that also fails is logged, and the session is left where it is | test_mv_12_a_failed_rollback_is_logged |

### MC — the move command

`move_session` runs on the Portal, because the Portal is what holds the sessions and the connections.
The decision to move one is the game's, and the game runs on a Server. This is the command that
crosses between them.

One class, imported by both processes: AMP matches on the command's key, so the Portal's responder and
the Server's `callRemote` need the same definition, not two that agree.

**The arguments are declared types, and that is the point of testing them.** A session id is an
integer and a destination is a name; a type declared wrongly does not fail where it is written, it
fails on the wire, at the moment somebody tries to move. The round trip is what catches it.

**The response carries both halves of the outcome** — whether the session moved, and which of the five
outcomes it was. It travels as declared fields rather than a pickled blob, so a Server reading it is
reading types AMP checked.

It lives in `move.py`, with the outcome constants it carries. The responder lives in `amp.py`, with
the Portal's other one.

**A session id the Portal does not hold is an outcome, not an error.** The usual cause is a player
disconnecting between the game deciding to move them and the command arriving — a race, not a bad
request. `NO_SUCH_SESSION` reports it the same way as the rest, and the Portal logs it too, because
the Portal is the only side that knows which ids it does have.

**The responder returns the move's Deferred**, so the reply carries the outcome rather than an
acknowledgement that the message arrived. AMP waits on a Deferred a responder gives back.

**Registered with the decorator, like every other responder.** Twisted builds the dispatch table at
class creation; a method without it sits on the class and is never called. MC-06 is the same case as
AR-07 and QY-07, and exists for the same reason.

**`send_session` is the consumer's whole API, and it moves one session.** A move hands one socket from
one Server to another. An account can hold several sessions, and whether they all follow is a game
decision — the same reasoning that keeps rooms and characters out of this library keeps accounts out.
A consumer wanting to move an account loops its sessions and decides for itself what to do when the
third comes back refused after the first two moved.

It takes a session and a destination name, and nothing about AMP: the Portal connection is the
Server's own, and a consumer should not have to know it exists.

**An optional payload rides with the move.** A destination Server often needs to know something about
an arriving session that the session itself does not carry — which archive to rebuild it from, say.
The command carries it from the Server to the Portal, the Portal stamps it onto the session's
`server_data`, and `SESSION_SYNC_ATTRS` already sends that with the `PCONN`. Two hops, one field.

**A dict in, a string out, and we never look inside it.** The consumer passes a dict; it is
`json.dumps`ed onto the command and the string is what lands in `server_data`. Nothing of ours
deserialises it, because **nothing of ours runs on the destination** — the session there is built by
Evennia from the sync data, so the consumer's own code is the first thing of anyone's to see it, and
`json.loads` is theirs to call. JSON types only: strings, numbers, booleans, lists, dicts and null.

**It is not a ticket.** A moved session never leaves the Portal, so there is no untrusted hop — the
destination trusts the instruction because it came from the Portal it is already attached to. The
payload is context, not proof.

**An optional payload rides with the move.** A destination Server often needs to know something about
an arriving session that the session itself does not carry — which archive to rebuild it from, say.
The command carries it from the Server to the Portal, and the Portal stamps it onto the session's
`server_data`, which `SESSION_SYNC_ATTRS` already sends with the `PCONN`. Two hops, one field.

**It is opaque, and it is not a ticket.** The library never looks inside it: a string, encoded and
decoded by the consumer's own code at both ends. Accepting a dict would mean choosing a serialisation
format for data we do not read, and owning it afterwards.

Nor does it authenticate anything. A moved session never leaves the Portal, so there is no untrusted
hop — the destination trusts the instruction because it came from the Portal it is already attached
to. The payload is context, not proof, and building ticket checking on top of it would be solving a
problem this transport does not have.

| ID | Case | Test function |
|---|---|---|
| MC-01 | The session id and the destination survive the round trip | test_mc_01_the_arguments_survive_the_round_trip |
| MC-02 | The outcome survives the round trip, both halves of it | test_mc_02_the_outcome_survives_the_round_trip |
| MC-03 | The responder moves the session the id names, to the destination named | test_mc_03_the_responder_moves_the_named_session |
| MC-04 | The reply carries the move's own outcome, waiting for it | test_mc_04_the_reply_carries_the_moves_outcome |
| MC-05 | A session id the Portal does not hold is reported, and nothing is moved | test_mc_05_an_unknown_session_is_reported |
| MC-06 | The responder is registered under the command's key | test_mc_06_the_responder_is_registered_under_the_commands_key |
| MC-07 | `send_session` asks this Server's Portal to move that session, by id, to the instance named | test_mc_07_send_session_asks_its_portal_to_move_it |
| MC-08 | It resolves to the outcome the Portal reported | test_mc_08_send_session_resolves_to_the_reported_outcome |
| MC-09 | A payload is carried as JSON on the command, and a move without one carries nothing | test_mc_09_a_payload_is_carried_as_json |
| MC-10 | The responder puts the payload where the sync data will carry it to the destination | test_mc_10_the_payload_is_put_where_the_sync_data_carries_it |
| MC-11 | A move with no payload leaves the session's existing data untouched | test_mc_11_no_payload_leaves_the_session_alone |

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

**A Server that does not come up is said so at the terminal.** The Server refuses to start when it is
not registered (ST), and twistd has daemonised by then — no stdout, and the launcher has already
returned to the prompt. So the operator types a command, nothing happens, and the only trail is a log
file they have no reason to suspect. Saying "it did not start, read the log" is the whole requirement;
carrying the reason across process boundaries is not.

**The signal is the pidfile, not the exit code.** twistd forks and the process we spawned exits 0
almost immediately, whatever became of the Server. Its status says nothing.

| ID | Case | Test function |
|---|---|---|
| LC-01 | `server_start` runs the Server command Evennia's own launcher would build, rather than one assembled here | test_lc_01_runs_the_command_evennia_would_build |
| LC-02 | It runs the Portal's command under no circumstances — `_get_twistd_cmdline` returns both, and only the Server's is wanted | test_lc_02_never_runs_the_portals_command |
| LC-03 | The process is started with the launcher's environment, so the gamedir and settings reach the child | test_lc_03_runs_it_with_the_launchers_environment |
| LC-04 | Nothing is sent to a Portal — no instruction is issued, so an attached Server is not stopped | test_lc_04_sends_nothing_to_a_portal |
| LC-05 | The callable is importable at the dotted path a consumer names in `EXTRA_LAUNCHER_COMMANDS` | test_lc_05_resolves_at_the_configured_dotted_path |
| LC-06 | A Server that did not come up is reported at the terminal, pointing at the log, and success is not claimed | test_lc_06_a_server_that_did_not_come_up_is_reported |


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

**Four settings, one mechanism.** `AMP_CLIENT_PROTOCOL_CLASS` is layered the same way as the other
three, and it is the setting that gives the startup check somewhere to run — see CP. It only reaches
anything because `evennia_patch` restored it first, which is why the install goes above the layering.

**The client factory is layered the same way the patch is installed**, by rebinding
`amp_client.AMPClientFactory` — no setting names it. Order matters: it goes on *after* the patch, so
ours is the leaf and the patched class is underneath. Layered first, the patch would subclass ours and
`buildProtocol` would still be Evennia's broken one.

**The Evennia patch is installed from here too.** It is not a class setting, so it does not go through
the same mechanism — Evennia's Server service looks `amp_client.AMPClientFactory` up by name at call
time, and `install()` rebinds it. `ready()` is still the right place: it runs before any service is
built, in both processes. The Portal never constructs an AMP *client* factory, so the install costs it
a class object and nothing else.

**`data_in` is wrapped, never replaced.** Evennia's applies a character limit, a command-rate limit,
`clean_senddata` and a local echo before sending. Replacing it and sending directly puts a malformed
message on the wire, which surfaces inside the Server's input handling as `too many values to unpack` —
nowhere near the cause.

**Every message about a session follows the same rule.** `data_in` routes what a player types;
`connect`, `sync` and `disconnect` are the other three things the Portal says about a session, and
they were going to whichever Server spoke to the Portal most recently. Announce and input then
disagree: the session is created on one Server while everything typed goes to another, which has never
heard of it. The player sees a login screen and then nothing they type does anything. All four now
resolve through `connection_for`, so they cannot disagree by construction.

`connect` routes on the session it was handed, while Evennia's own may announce a *different* one off
its connection queue. Both are unbound at that point and so resolve to the same default; a session is
only ever bound later, by a move.

**`disconnect_all` is a broadcast, not a routed send.** It is one message telling a Server to drop
everything it holds, and the Portal calls it when it shuts down. Sent once, the other instances carry
on believing their players are still connected — characters standing in rooms with nobody at the
keyboard. So it goes to every attached connection.

**Then `super()` runs, and sends one more.** Evennia welds the send to the teardown: the callback that
closes the Portal's own sockets is attached to that send's Deferred, so skipping it would leave every
socket open. The extra message lands on a Server that has already dropped everything and finds nothing
to do. A redundant message is cheaper than a copy of Evennia's teardown, which would go stale silently
the first time they changed it.

`announce_all` needs none of this. It writes to the Portal's own sockets and never involves a Server,
so it already reaches every player on every instance.

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
| IN-10 | `ready()` installs the Evennia patch, so the factory Evennia constructs reads `AMP_CLIENT_PROTOCOL_CLASS` | test_in_10_ready_installs_the_evennia_patch |
| IN-11 | `ready()` layers the client protocol over `AMP_CLIENT_PROTOCOL_CLASS`, so the startup check has a call site | test_in_11_ready_layers_over_the_client_protocol |
| IN-12 | `ready()` layers the client factory onto Evennia's module, above the patch rather than below it | test_in_12_ready_layers_over_the_client_factory |
| IN-13 | `connect` announces a new session down the connection its input will use | test_in_13_a_new_session_is_announced_where_its_input_goes |
| IN-14 | `sync` follows the same connection, so a telnet client's negotiated flags reach the Server holding the session | test_in_14_sync_follows_the_same_connection |
| IN-15 | `disconnect` tells the instance actually holding the session | test_in_15_disconnect_tells_the_instance_holding_it |
| IN-16 | `disconnect_all` reaches every attached instance, not just one | test_in_16_disconnect_all_reaches_every_instance |
| IN-17 | `disconnect_all` still calls `super()`, which is what closes the Portal's own sockets | test_in_17_disconnect_all_still_closes_the_sockets |

### QY — asking the Portal which instances are attached

A Server can see its own side of the AMP link and nothing else. Whether its announcement was recorded,
and what else is attached, are facts only the Portal holds — so a Server that failed to register looks
exactly like one that succeeded, until something tries to reach it.

This is the round trip that closes that, and the first thing this library adds to the AMP protocol
rather than intercepts on it.

**One command, one question, one answer.** AMP is already a command-dispatch protocol: a key, typed
arguments, a declared response, and a table that routes by command. A generic query command carrying a
question field would rebuild that a layer up and worse — one response shape forced to serve every
question, so a pickled blob rather than declared types, and an unknown-question case of our own to get
wrong. Another question later is another command of this shape, a dozen lines in the obvious place.

Because the command *is* the question, there is no branching to test. What was going to be a decision
function is now `registry.attached()`, already covered by IR-08 — so these cases aim one layer down, at
the responder itself. That is where the only new code is.

Reading that answer is a separate unit, covered separately: this section ends at *having* the list.
What an instance concludes from it — most usefully, whether its own announcement landed — takes the
answer as an argument and asks the Portal nothing.

There is deliberately no pre-move check. `move_session` already refuses an unattached destination from
the Portal's own registry, with no round trip at all — asking first would buy nothing unless the game
wanted to make a different decision rather than report the failure.

| ID | Case | Test function |
|---|---|---|
| QY-01 | The responder answers with every instance currently attached | test_qy_01_answers_with_every_attached_instance |
| QY-02 | A Portal with nothing attached answers with an empty list, not an error | test_qy_02_an_empty_portal_answers_with_an_empty_list |
| QY-03 | The registry is read when the question arrives, so a registration made since is included | test_qy_03_reads_the_registry_when_the_question_arrives |
| QY-05 | A Server asking receives the list back, decoded | test_qy_05_a_server_asking_receives_the_decoded_answer |
| QY-07 | The responder is registered under the command's key in the class's dispatch table | test_qy_07_the_responder_is_registered_under_the_commands_key |

### SR — an instance checking its own registration

The other half of QY, and deliberately separate from it. QY ends at *having* the list; this reads it.

**It asks the Portal nothing.** The answer is passed in, so a caller that already queried for other
reasons pays for one round trip rather than two, and this stays testable with no AMP anywhere near it.

**"Am I registered" rather than "is everyone".** No instance knows what order the others boot in, so
"is everyone here" is unanswerable at startup and would only produce a retry loop. Whether an
instance's own announcement landed is self-contained, and something it can act on: a Server that finds
itself missing knows its handshake did not take, which is otherwise indistinguishable from a Portal
that has simply not been asked.

**The comparison is against `MULTIPLEX_INSTANCE_ID`**, resolved through `config`, so a caller does not
have to know which setting names an instance. That is most of what this function is for — the check
itself is one containment test.

What an instance *does* with the answer is a separate unit — see ST. This is the read, and nothing
else: three lines and one containment test.

| ID | Case | Test function |
|---|---|---|
| SR-01 | True when this instance's name is in the answer | test_sr_01_true_when_this_instance_is_in_the_answer |
| SR-02 | False when it is not | test_sr_02_false_when_it_is_not |

### ST — the startup check

`am_i_registered` answers whether. This decides what to do about it, and it is where the retry lives —
not in the read, which stays a yes/no.

**An instance that finds itself unregistered does not start.** One check, no retries, and the failure
raised rather than logged and shrugged off. A Server nobody can reach is not started in any useful
sense, and failing at boot beats running unreachable while somebody works out why players never
arrive.

**There are no retries because there is no window one would close.** The two failures are already
covered:

- **The connection is down** — then there is nothing to query, and `AMPClientFactory` is a Twisted
  `ReconnectingClientFactory` that is already redialling with backoff. A retry of ours would be a
  worse copy of something running anyway.
- **The connection is up and this instance is not in the list** — the handshake went down that same
  connection before the query, AMP delivers in order, and the Portal records synchronously. So the
  answer cannot mean "not yet". It means something is broken, and asking again will not change it.

Retries can be added if experience says otherwise. They are not being built on a guess.

**Each failure line says which kind it was**, because the two mean different things and are cheaply
distinguishable — the Portal unreachable, with the address named, or the Portal answering without this
instance in its list.

**It runs from the AMP client's `connectionMade`** — the method that sends the handshake, so the query
follows it down the same connection. See CP for that call site and what it does with a failure.

| ID | Case | Test function |
|---|---|---|
| ST-02 | A check that finds this instance missing is logged before it raises | test_st_02_logs_before_it_raises |
| ST-03 | An instance that is not registered does not finish starting | test_st_03_an_unregistered_instance_does_not_start |
| ST-04 | The failure names this instance and what the Portal did report, so the line is actionable | test_st_04_the_failure_names_this_instance_and_the_answer |
| ST-05 | A Portal that could not be reached at all is reported as that, naming the address tried | test_fc_01_the_address_that_could_not_be_reached_is_logged |

**ST-01 is retired.** It covered a retry the design no longer has. The ID is not reused.

ST-05 is answered on the factory, not here — a Portal that was never reached never reaches this
check. See FC.

### CP — the Server's AMP client protocol

The seam ST describes. `check_registration` decides what an unregistered instance does; this is the
one place it can be called from and have that decision mean anything.

**It has to be `connectionMade`.** That is the method that sends the handshake, so a query issued from
it goes down the same connection, immediately after, and AMP delivers in order. Every other candidate —
a timer, a service hook, an `at_server_start` — loses that guarantee and with it the single check: the
answer could then mean "not yet", and the design would need the retries it deliberately does not have.

**`super()` first, always.** Evennia's `connectionMade` is what sends `PSYNC`. Query before it and the
Portal has not been told who this is, so the answer is "not registered" every time and every Server
refuses to start.

**The subclass is reached through `AMP_CLIENT_PROTOCOL_CLASS`**, the documented way, layered over
whatever the setting already named — Evennia's default, or a consumer's own protocol class. That
setting only works because `evennia_patch` restored it; see PT.

**The Deferred is the branch, not an `if`.** `check_registration` returns nothing when all is well and
raises when it is not, so the errback is reached by exactly the failures worth refusing on — this
instance missing from the answer, a Portal that does not speak the query, a connection that dropped
mid-question. All three mean the same thing: this Server cannot confirm anybody can reach it.

**Log everything known, then stop the reactor.** Raising inside `connectionMade` is not a refusal —
Twisted logs the traceback and the reactor carries on, leaving a Server running unreachable. Stopping
the reactor is the graceful version: services come down in order and the log line reaches disk, which
matters because the log is the only place the reason exists. The launcher reports the *fact* of the
failure at the terminal (LC-06); this is where the *reason* is written down.

**The cause is named where it can be told apart.** A Portal that answers `UnhandledCommand` is not
running this library, which is a different fix from an instance whose announcement did not land. Both
refuse; they do not read the same in the log.

**The refusal exits non-zero.** Started from a terminal that changes nothing. Started by a process
manager after a reboot it is the difference between being retried and staying down — and after a
reboot "not registered" is usually transient, because the instance holding the Portal may not be
listening yet. A retry succeeds where giving up does not. A real misconfiguration still stops, because
a process manager's own retry limit gives up after a few attempts.

It goes on an after-shutdown trigger rather than a `sys.exit`, which inside an errback only raises
`SystemExit` into the Deferred and is swallowed.

| ID | Case | Test function |
|---|---|---|
| CP-01 | `connectionMade` calls `super()` before querying, so the handshake is sent first | test_cp_01_the_handshake_is_sent_before_the_query |
| CP-02 | The query goes down this connection, the one the handshake went down | test_cp_02_the_query_goes_down_this_connection |
| CP-03 | The Portal's answer is handed to `check_registration` | test_cp_03_the_answer_is_handed_to_the_check |
| CP-04 | The generated class subclasses whatever the setting named | test_cp_04_subclasses_whatever_the_setting_named |
| CP-05 | A failure stops the reactor, so the Server does not go on running unreachable | test_cp_05_a_failure_stops_the_reactor |
| CP-06 | The failure is logged with its reason before the shutdown | test_cp_06_the_reason_is_logged_before_the_shutdown |
| CP-07 | A Portal that does not speak the query is logged as not running this library | test_cp_07_a_portal_without_the_library_is_named_as_that |
| CP-08 | A successful check stops nothing | test_cp_08_a_successful_check_stops_nothing |
| CP-09 | The refusal exits non-zero, after the shutdown, so a process manager sees a failure | test_cp_09_the_refusal_exits_non_zero |

### FC — the Server's AMP client factory

A Portal that cannot be reached at all never gets as far as CP. `connectionMade` only runs on a
connection that formed, so the check, the query and the errback are all off the path. Twisted calls
`clientConnectionFailed` on the factory instead.

Evennia handles that already — it logs and lets `ReconnectingClientFactory` retry with backoff — but
its line names no address. With one Server that is enough, because there is only one Portal it could
mean. With several instances and a mistyped `AMP_HOST`, it says nothing about which one is wrong,
which is the whole question being asked.

**`super()` still runs.** The retry belongs to Twisted and is the correct behaviour: a Portal that is
not up yet usually will be shortly. This adds a line to the log and changes nothing else.

**Layered over whatever is bound, not over the patched class by name.** Nothing names this class in
settings, so a consumer cannot override it and there is no consumer class to preserve. The reason to
read the current binding is `evennia_patch`: naming `PatchedAMPClientFactory` would make the patch
load-bearing, and it exists to be deleted.

| ID | Case | Test function |
|---|---|---|
| FC-01 | A failed connection is logged with the address that could not be reached | test_fc_01_the_address_that_could_not_be_reached_is_logged |
| FC-02 | `super()` still runs, so Twisted's reconnect backoff is untouched | test_fc_02_the_retry_still_happens |
| FC-03 | The generated class subclasses whatever is bound, so the patch stays deletable | test_fc_03_subclasses_whatever_is_bound |

### PT — a local patch for an Evennia bug

`AMPClientFactory.__init__` resolves `settings.AMP_CLIENT_PROTOCOL_CLASS` into `self.protocol` and then
never reads it: `buildProtocol` names `AMPServerClientProtocol` directly. So pointing that setting at a
subclass has no effect, and nothing is raised or logged. The Portal-side twin in `amp_server.py` does
use `self.protocol()`, which is what makes it a slip rather than a decision. Reproduced on 6.1.0 and
present on `main`; reported upstream.

**The patch restores the setting rather than routing around it.** A subclassed factory whose
`buildProtocol` uses `self.protocol()`, installed by replacing the module attribute Evennia's Server
service looks up. Everything else in this library then configures itself through
`AMP_CLIENT_PROTOCOL_CLASS` the documented way, alongside the other class settings.

**That is what makes it removable.** The library sets the setting whether or not the patch is
installed. On a fixed Evennia, deleting the installer line changes nothing: Evennia honours the
setting we were already setting, and builds the same class we were building. A patch that *replaced*
the protocol class directly would have skipped the setting entirely, and removing it would have been a
behaviour change.

**PT-04 is a canary.** It asserts the bug is still present, so it passes today and fails the moment we
upgrade to a fixed Evennia — which is the signal to delete the patch. A failure there is good news,
and its name says so.

| ID | Case | Test function |
|---|---|---|
| PT-01 | The patched factory builds the class the setting names | test_pt_01_builds_the_class_the_setting_names |
| PT-02 | Installing it replaces the factory Evennia's Server service will construct | test_pt_02_install_replaces_the_factory_evennia_will_construct |
| PT-03 | The patched `buildProtocol` does everything Evennia's did — reset the delay, hold the protocol on the service, set its factory, return it | test_pt_03_does_everything_evennias_buildprotocol_did |
| PT-04 | Canary: Evennia's own factory still ignores the setting, so the patch is still needed | test_pt_04_canary_evennias_factory_still_ignores_the_setting |
