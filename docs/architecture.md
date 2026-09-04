# Architecture

How the library is put together, which module does what, and what is not built yet.

Three processes make up everything it does: **a Server booting and registering**, **a player
connecting**, and **moving a session between Servers**. Each has its own section below, and each
starts with the steps in order before the prose explaining them.

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
| `amp.py` | The Portal's AMP protocol: records an instance on its handshake, forgets it on disconnect, answers the registry query |
| `routing.py` | Points one send at one instance for the duration of a call |
| `binding.py` | Which instance a session belongs to, and which connection that resolves to |
| `sessionhandler.py` | Routes everything the Portal says about a session to the instance holding it |
| `move.py` | The three-step move |
| `query.py` | `MultiplexQueryRegistry` — a Server asking its Portal what is attached |
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

A new session, from the socket opening to the player typing. One gap, and it is not on this path for a
single Portal shutting down cleanly.

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
- **[gap]** `disconnect_all` and `announce_all` reach one Server, so a Portal shutdown would leave the
  other instances' sessions hanging

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

# Process three — moving a session between Servers

Not a reconnection. The player's socket stays exactly where it is; only the Server it is fed to
changes. **The mechanism is built; nothing can ask for it yet.**

- **[gap]** game code decides a session should move — the consumer's call, but there is nothing to
  call
- **[gap]** the Server sends the Portal an AMP command naming the session and the destination
- **[gap]** a responder on the Portal resolves the session id and calls `move_session`
- **[library]** a session already on that instance returns, and sends nothing
- **[library]** a destination that is not attached refuses, naming what *is* attached
- **[library]** the origin is resolved before anything is sent, because rebinding changes the answer
- **[library]** the origin is told to release the session — `PDISCONN`
- **[Evennia]** the origin Server tears down its own session
- **[library]** `uid`, `logged_in` and `puid` are cleared, before the sync data is taken
- **[library]** the session is bound to the destination
- **[library]** the destination is told to build one — `PCONN`, with the session's sync data
- **[Evennia]** the destination creates a session and runs its own login flow; the player is
  unauthenticated
- **[library]** everything the Portal says about the session now follows the new binding
- **[gap]** the outcome is reported back to the Server that asked

No socket is opened, closed or renegotiated at any point, on either the player's connection or the AMP
links.

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

A destination that is not attached raises. Falling back would leave the player where they were while
everything above believed they had moved, and the two would only disagree later, somewhere else.
Routing falls back deliberately — traffic has to go somewhere real — but a move is a decision and can
refuse.

# What is built and not wired

One piece is complete and tested with nothing calling it:

- **`move_session`** — no trigger. Nothing can ask for a move.

# Not designed yet

- **The move trigger.** The intended shape is a `MultiplexCommand` — its own AMP command, with a
  session id and a destination as declared arguments and an outcome as its response, so the Server
  learns whether the move happened. Nothing is built.
- **Broadcasts.** `disconnect_all` and `announce_all` reach one Server. Under several, a shutdown
  announcement would leave the others' sessions hanging.
- **Where an instance lands when none of the defaults is attached.** `MULTIPLEX_DEFAULT_INSTANCE`
  takes a single name today; an ordered list was discussed and not built.
