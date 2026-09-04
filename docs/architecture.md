# Architecture

How the library is put together, which module does what, and what is not built yet.

Four processes make up everything it does: **a Server booting and registering**, **a player
connecting**, **moving a session between Servers**, and **announcing to every player**. Each has its
own section below, and each starts with the steps in order before the prose explaining them. All four
are complete; none has been run against live instances.

Two functions are the whole consumer API: `send_session` and `broadcast_to_all_instances`.

## The problem

Evennia runs as two processes. The **Portal** holds every player's socket; the **Server** runs the
game. They talk over AMP, and the Portal deliberately outlives the Server — which is why a telnet
session survives `evennia reload`.

Evennia assumes exactly one Server. It keeps a single `portal.amp_protocol` and a single
`factory.server_connection`, both naming whichever Server attached or spoke most recently. With one
Server that is always the right answer and the indirection is invisible. With two, everything lands on
the last one to speak.

This library makes that assumption configurable: several Servers behind one Portal, each addressable,
and a session handed from one to another without its socket noticing.

## The modules

Nothing above the registry imports anything else in the library. Each takes what it needs as an
argument, which is why they test as plain data handling.

| Module | Does |
|---|---|
| `config.py` | The two settings this library reads |
| `registry.py` | Instance id → live AMP connection. No decisions, no sends |
| `services.py` | Server side: announces this instance's name. Portal side: owns the registry, installs the recording protocol |
| `amp.py` | The Portal's AMP protocol: records an instance on its handshake, forgets it on disconnect, answers the registry query, and carries out a move |
| `routing.py` | Points one send at one instance for the duration of a call |
| `binding.py` | Which instance a session belongs to, and which connection that resolves to |
| `sessionhandler.py` | Routes everything the Portal says about a session to the instance holding it |
| `move.py` | The move, its outcomes, the command that asks for one, and `send_session` |
| `query.py` | `MultiplexQueryRegistry` — a Server asking its Portal what is attached |
| `announce.py` | `MultiplexAnnounce` and `broadcast_to_all_instances` — reaching every player at once |
| `startup.py` | Refusing to start when this instance is not registered |
| `amp_client.py` | The Server's side of the AMP link: runs that check on connect, and names a Portal it could not reach |
| `launcher.py` | `evennia server_start` — starts a Server without stopping another |
| `evennia_patch.py` | A local fix for an Evennia bug. Deletable |
| `apps.py` | The installer. The library's only way into either process |

## Three facts about Evennia that shape everything

**An AMP responder must be re-registered, not overridden.** Twisted builds `_commandDispatch` as a
class attribute at class-creation time, mapping each command to the function its `@Command.responder`
decorator was applied to. A subclass inherits that table, so redefining the method without the
decorator leaves the entry pointing at the parent's function. The override compiles, installs, sits on
the instance and is never called — nothing raised, nothing logged. AR-07 and QY-07 exist to catch it.

**`factory.server_connection` is the routing variable, not `portal.amp_protocol`.** Every send goes
through `AMPServerProtocol.data_to_server`, which ignores the connection object it was called on and
uses `self.factory.server_connection`. Evennia reassigns that on every inbound admin message, so it
names whichever Server spoke last. Calling `send_AdminPortal2Server` on a particular connection
decides nothing.

**`PortalSessionHandler` methods must be wrapped, not replaced.** `data_in` applies a character limit,
a command-rate limit, `clean_senddata` and a local echo before sending; `connect` throttles and
assigns session ids. Replacing one and sending directly puts a malformed message on the wire, which
surfaces inside the Server's input handling as `too many values to unpack` — nowhere near the cause.

# Process one — a Server booting and registering

Every step from starting a Server to it being reachable, and who owns each one — **[library]** for
this library, **[Evennia]** for Evennia or Twisted. No gaps: this process is complete.

- **[Evennia]** `django.setup()` runs during Server boot, which runs every installed app's `ready()`
- **[library]** `ready()` installs the Evennia patch, layers our AMP client factory on top of it, and
  repoints four class settings
- **[Evennia]** `_init()` builds the Server service from `EVENNIA_SERVER_SERVICE_CLASS`
- **[Evennia]** the AMP client factory dials the Portal, retrying with backoff if it cannot
- **[library]** a Portal that cannot be reached is logged with its host and port, then Twisted retries
  as it would have
- **[library]** `buildProtocol` reads `AMP_CLIENT_PROTOCOL_CLASS` and builds our client protocol —
  Evennia's own ignores that setting; the patch restores it
- **[library]** our `connectionMade` runs
- **[Evennia]** `super().connectionMade()` sends the `PSYNC` handshake
- **[library]** `get_info_dict()` has added this instance's name to what `PSYNC` carries
- **[library]** on the Portal, `register_amp()` has already put our recording protocol on the AMP
  factory
- **[library]** the Portal's responder reads the name and records the connection in the registry
- **[library]** the Server asks the Portal what it is holding, down the same connection
- **[library]** the Portal answers with every instance attached
- **[library]** `check_registration` returns quietly, or logs and raises
- **[library]** on failure: log the reason, register a non-zero exit, stop the reactor
- **[Evennia]** the reactor stops, services come down in order, the log reaches disk
- **[library]** `server_start` waits, checks the pidfile, and reports at the terminal if the Server is
  not there

## How an instance becomes addressable

Both processes run `django.setup()`, so both run `AppConfig.ready()`, which repoints class settings
that Evennia resolves later in `_init()`. That ordering is the whole reason this works without
patching anything at runtime.

The name comes from `MULTIPLEX_INSTANCE_ID`. A consumer that already names its instances aliases that
setting rather than maintaining two.

The Portal's side of the same handshake: `ready()` repoints `EVENNIA_PORTAL_SERVICE_CLASS` and
`PORTAL_SESSION_HANDLER_CLASS`; `_init()` builds our Portal service, which creates the one registry;
`register_amp()` puts our recording protocol on the AMP factory; and the responder writes the name
into the registry against the connection it arrived on.

## How a Server refuses to start

A Server that announced itself and was not recorded looks exactly like one that was, until something
tries to reach it. So it asks, and stops if the answer is wrong.

**The check runs from `connectionMade`, and it has to.** `PSYNC` and the query go down the same
connection in order, AMP delivers in order, and the Portal records synchronously — so a "not
registered" answer cannot mean "not yet", and one check is enough. From a timer or a service hook that
guarantee is gone and retries would be needed to paper over the race.

**One errback, three causes.** This instance missing from the answer, a Portal that answers
`UnhandledCommand` because it is not running this library, or a connection that dropped mid-question.
All three mean the Server cannot confirm anybody can reach it; the log line says which.

**Stopping the reactor, not raising.** A raise out of `connectionMade` is logged by Twisted and the
reactor carries on, leaving a Server running unreachable. Stopping brings the services down in order,
so the log line reaches disk — and the log is the only place the reason exists, because twistd has
daemonised by then and has no terminal. The launcher reports the *fact* separately: `server_start`
waits, checks the pidfile, and says so if the Server is not there.

**The exit is non-zero**, so a process manager retries rather than leaving the Server down. After a
reboot "not registered" is usually the Portal not listening yet, which a retry fixes; a real
misconfiguration still gives up, at the process manager's own retry limit.

`AMP_CLIENT_PROTOCOL_CLASS` is what makes the override reachable, and it only works because
`evennia_patch` restored it — `AMPClientFactory` resolves it and then ignores it.

## A Portal that was never reached

`connectionMade` only runs on a connection that formed, so none of the above applies: Twisted calls
`clientConnectionFailed` on the factory instead. Evennia already logs that and retries with backoff,
but names no address, which with several instances leaves you unable to tell which Portal is wrong.
Our factory layer adds the host and port and lets the retry proceed — a Portal that is not up yet
usually will be shortly.

Both factory layers are installed by rebinding `amp_client.AMPClientFactory`, since no setting names
it. Ours goes on after the patch, so the chain is ours → patched → Evennia's.

# Process two — a player connecting

A new session, from the socket opening to the player typing, and everything the Portal says about it
afterwards. No gaps: this process is complete.

- **[Evennia]** the player's client connects; the protocol calls `sessionhandler.connect()`
- **[library]** the announcement goes down the connection this session's input will use — the default
  instance, unless something has bound it elsewhere
- **[Evennia]** Evennia's `connect()` throttles, assigns a session id, and sends `PCONN` with the
  session's data
- **[Evennia]** the Server creates a session and sends back a login screen
- **[Evennia]** output returns on that Server's own AMP link and reaches the right socket by session
  id — correct under several Servers, unmodified
- **[Evennia]** telnet negotiates terminal type, width, colour and compression, which settle after the
  session already exists
- **[library]** `sync()` sends the updated session data to the same instance
- **[Evennia]** the player types; the protocol hands it to `data_in`
- **[library]** `data_in` routes it to the instance the session is bound to
- **[Evennia]** Evennia's `data_in` applies the character limit, the command-rate limit,
  `clean_senddata` and the local echo
- **[library]** on disconnect, the instance actually holding the session is the one told
- **[library]** when the Portal shuts down, every attached instance is told to drop everything it
  holds, then Evennia closes the Portal's own sockets

## Announce and input have to agree

Four things the Portal says about a session: `connect`, `sync`, `data_in`, `disconnect`. All four
resolve through `connection_for`, so they cannot pick different Servers.

Leave any one of them unrouted and it goes to whichever Server last spoke to the Portal, while the
other three follow the binding. The session is then created on one Server and spoken to on another
that has never heard of it: a login screen, and then nothing the player types does anything. Whether
it bites at all depends on AMP timing at boot, which is the worst kind of bug to meet live.

`connect` routes on the session it was handed, while Evennia's own may announce a *different* one off
its connection queue. Both are unbound at that point and resolve to the same default; a session is
only ever bound later, by a move.

## Where a session starts

**Unbound means the default instance**, not "whatever Evennia's global happens to hold". That global
names whichever Server attached most recently, so a player arriving while a second Server started
would be handed to that one. The default is a decision, taken from `MULTIPLEX_DEFAULT_INSTANCE`.

The binding is held **as a name, not a connection**. The Portal outlives Servers — that is how
`reload` works — so a Server that restarts comes back on a new connection and the registry replaces
its entry. A session holding the old connection object would be writing into a dead one, silently. A
session holding the name follows the replacement without noticing.

## Shutting the Portal down

`disconnect_all` is the one thing on this path that is not a routed send. It is a single message
meaning "drop all your sessions", so it goes to every attached connection rather than to one — sent
once, the other instances carry on believing their players are still connected.

`super()` then sends one more. Evennia welds the send to the teardown: the callback that closes the
Portal's own sockets is attached to that send's Deferred. Skipping it leaves every socket open, and
reimplementing it means carrying a copy of the watchdog that stops `disconnect` deleting sessions
mid-loop. The extra message lands on a Server that has already dropped everything and finds nothing to
do, which is cheaper than a copy that goes stale silently.

`announce_all` needs none of this. It writes to the Portal's own sockets and never involves a Server,
so it already reaches every player on every instance — see *Process four*, which is about asking for
it rather than doing it.

`stop_server` — the Portal telling a Server to shut down — is not on this path. It only runs in
portal-interactive mode, and a plain Portal shutdown leaves the Servers running.

# Process three — moving a session between Servers

Not a reconnection. The player's socket stays exactly where it is; only the Server it is fed to
changes. No gaps: this process is complete.

- **[consumer]** game code decides a session should move, and calls `send_session`
- **[library]** the Server asks its Portal, naming the session by id and the destination by name, with
  an optional payload
- **[library]** the Portal's responder resolves the id to a session
- **[library]** an id it does not hold is reported as `NO_SUCH_SESSION`, and nothing else runs
- **[library]** a payload is stamped onto the session, where the sync data will carry it
- **[library]** a session already on that instance is reported as `ALREADY_THERE`, and nothing is sent
- **[library]** a destination that is not attached is reported as `NOT_ATTACHED`, and nothing is sent
- **[library]** the origin and the session's identity are captured, before anything changes them
- **[library]** the origin is told to release the session — `PDISCONN`
- **[Evennia]** the origin Server tears down its own session
- **[library]** `uid`, `logged_in` and `puid` are cleared, before the sync data is taken
- **[library]** the session is bound to the destination
- **[library]** the destination is told to build one — `PCONN`, with the session's sync data
- **[Evennia]** the destination creates a session and runs its own login flow; the player is
  unauthenticated
- **[library]** a destination that would not take it is `REJECTED`: the identity goes back, the session
  is rebound to the origin, and the same build runs again pointing there
- **[library]** an origin that will not take it back either is `STRANDED`, and logged
- **[library]** everything the Portal says about the session now follows the new binding
- **[library]** the outcome goes back to the Server that asked, as the command's reply
- **[consumer]** the game reads the outcome, and at the destination reads the payload

No socket is opened, closed or renegotiated at any point, on either the player's connection or the AMP
links.

## What a consumer calls

`send_session(session, destination, payload=None)`, and nothing else. It returns a Deferred resolving
to `(moved, outcome)`, where `moved` is true for `MOVED` and nothing else — including `ALREADY_THERE`,
which is a consumer asking to send a session somewhere it already is, and so a bug in their logic
worth surfacing rather than a quiet success.

**One session per call.** An account can hold several, and whether they all follow is a game decision.
A consumer moving an account loops its sessions and decides for itself what to do when the third comes
back refused after the first two moved.

**The payload is context, not a ticket.** A destination often needs to know something about an
arriving session that the session does not carry — which archive to rebuild it from, say. It is a
dict, `json.dumps`ed onto the command, stamped into `server_data[PAYLOAD_KEY]` by the Portal, and
carried across by the sync data. JSON types only.

Nothing of ours reads it back, because **nothing of ours runs on the destination** — the session there
is built by Evennia from the sync data. The consumer's own code calls `json.loads`:

    payload = session.server_data.get(PAYLOAD_KEY)

It authenticates nothing. A moved session never leaves the Portal, so there is no untrusted hop — the
destination trusts the instruction because it came from the Portal it is attached to.

## Why it is sent directly

`sessionhandler.disconnect()` and `.connect()` would also drop the session from the Portal's own
handler and close the transport, which is the one thing a move must not do. The move sends `PDISCONN`
and `PCONN` itself, so the Servers change their minds about the session while the socket stays exactly
where it was.

## Why the identity fields are cleared

`uid`, `logged_in` and `puid` are all on `SESSION_SYNC_ATTRS`, and all three are primary keys
belonging to the Server being left. Carried across, the destination believes the session is already
authenticated as whatever account holds that id over there. They are cleared *before* `get_sync_data()`
is called, or the destination receives the old values and the clearing achieves nothing.

## Refusing rather than falling back

A destination that is not attached is reported, not silently substituted. Falling back would leave the
player where they were while everything above believed they had moved, and the two would only disagree
later, somewhere else. Routing falls back deliberately — traffic has to go somewhere real — but a move
is a decision and can refuse.

Every check runs before the first send, so a refusal is a decision not to start rather than a
half-finished move. Any future reason to refuse has to be checked there too: one found after the
origin has let go cannot leave the session where it was, because it is not there any more.

## Putting it back

The origin has already released the session by the time a build can fail, so a session left alone is a
player connected to a Portal and on no Server at all.

Instead the identity captured before it was cleared is restored, the session is rebound to the origin,
and the same build step runs again pointing there — the one thing it varies is whether the identity is
wiped or supplied. Nothing is sent to the destination, which never built anything to release.

That rebuild is Evennia's own reload, applied to one session: when a Server reconnects, the Portal
hands back every session's sync data and they come back logged in and re-puppeted.

Building before releasing would avoid stranding anyone, but it leaves a window where the session exists
on two Servers at once, and a release that then failed would leave a ghost standing in the origin's
world. Releasing first trades that for a stranded player, which the rollback recovers.

# Process four — announcing to every player

An admin messaging everyone. Short, because the Portal already does the work.

- **[consumer]** an admin command decides to say something to everyone, and calls
  `broadcast_to_all_instances`
- **[library]** the Server asks its Portal, carrying the message
- **[library]** the Portal's responder passes it to `announce_all`
- **[Evennia]** every session on the Portal is written to, whichever instance owns it

## Why it is here at all

An admin command that messages everyone calls `SESSION_HANDLER.announce_all` on its Server, and on a
single-instance game that reaches every player. Under several Servers it reaches one instance's
sessions, because that is all a Server's session handler holds — the rest are on other handlers in
other processes.

So it is a regression this library causes rather than a feature it is being asked to add: the same
game code did the right thing before it was installed. What belongs here is what breaks *because*
there is more than one Server.

The Portal has its own `announce_all`, and that one already reaches every player, because it holds
every socket. What Evennia has no way to do is ask for it from a Server — the Server-to-Portal admin
operations disconnect, sync and shut down, and none of them speaks. So there is nothing to build but
the asking, and the responder is a pass-through.

**Every session, not every player.** That includes anyone at the login screen who has not
authenticated: the Portal writes to sockets, not accounts. Right for "the game is going down in five
minutes"; a consumer wanting only logged-in players wants their own Server-side loop, on each
instance.

# Not designed yet

- **`PSYNC` hands every session to whichever Server just attached.** The Portal answers a Server's
  handshake with `get_all_sync_data()` — all of its sessions, regardless of which instance owns them.
  The attaching Server then builds a `ServerSession` for each, and any that carries a `uid` is
  attached to *that instance's* account of the same number.

  Two consequences, seen live. Every instance believes it owns every session. And each attach
  announces `SERVER_RESTART_MSG` to all of them, so players on unrelated instances are told the server
  restarted whenever any instance starts — which reads as instability that is not happening.

  The identity half is the same hazard MV-03 covers, arriving by a path the move never touches: it
  looks harmless only because two demo databases number their superuser identically.

  Nothing here has been touched yet. The Portal's side of `PSYNC` is `amp.py`'s territory and already
  has the registry to filter by.

- **A move announces a disconnect to the players left behind.** The origin receives `PDISCONN` and
  tells everyone still on that instance that the mover disconnected. The mover sees nothing.

  Not established as a problem. Someone watching a character leave for another shard has been told
  something true, and the alternative is silence. `[TBD — needs investigation: what the whole sequence
  looks like to the people watching, and then a decision on whether anything should change.]`

- **A player who moves sees `SERVER_RESTART_MSG`; a player moved by somebody else does not.** Both
  observed live, on the same destination, through the same mechanism. Unexplained.

- **A new session arriving while the default instance is down.** `connect` announces it to whichever
  Server spoke to the Portal most recently, which is the failure the rest of process two exists to
  remove — silent, and dependent on timing.

  The agreed answer is to refuse at the front door: tell the player the game is not available and
  close the connection. **Not** to fall through to another instance. In a deployment where one
  instance is the entry point, the others would only send the player back to it.

  The Portal can do this alone, since it holds the socket — the "not right now" path does not depend
  on the thing that is broken. A session already bound to an instance that goes down still falls back
  to the default, because it is in the game and its traffic has to go somewhere real. Only the front
  door refuses.

  `MULTIPLEX_DEFAULT_INSTANCE` stays a single name.

- **Checking the required settings at boot.** `MULTIPLEX_INSTANCE_ID` and `MULTIPLEX_DEFAULT_INSTANCE`
  both raise when read, but they are read at first use — which on a Portal is when a player connects.
  So a misconfigured Portal boots clean and fails on the first login. Checking them in `ready()`
  instead would fail at boot, on the same argument as the registration check: an instance nobody can
  reach is not started in any useful sense.

  `EXTRA_LAUNCHER_COMMANDS` is not in that set. This library never reads it — Evennia's launcher
  does — and a deployment that never starts a second Server on a shared Portal legitimately does not
  need it. It belongs in the installation guide, not in a boot check.
