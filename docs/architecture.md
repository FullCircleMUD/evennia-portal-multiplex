# Architecture

How the library is put together, which module does what, and what is not built yet.

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

## What a session move actually is

Not a reconnection. The player's socket stays exactly where it is; only the Server it is fed to
changes.

1. The Portal tells the instance the session is on to release it — `PDISCONN`.
2. It clears the session's identity fields and rebinds it.
3. It tells the destination to build one — `PCONN`, with the session's sync data.

No socket is opened, closed or renegotiated at any point, on either the player's connection or the AMP
links.

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
| `move.py` | The three-step move |
| `query.py` | `MultiplexQueryRegistry` — a Server asking its Portal what is attached |
| `startup.py` | Refusing to start when this instance is not registered |
| `launcher.py` | `evennia server_start` — starts a Server without stopping another |
| `evennia_patch.py` | A local fix for an Evennia bug. Deletable |
| `apps.py` | The installer. The library's only way into either process |

## How an instance becomes addressable

Both processes run `django.setup()`, so both run `AppConfig.ready()`, which repoints class settings
that Evennia resolves later in `_init()`. That ordering is the whole reason this works without
patching anything at runtime.

    Server boots
      -> ready() repoints EVENNIA_SERVER_SERVICE_CLASS
      -> _init() builds our Server service
      -> its AMP client dials the Portal
      -> on connect, get_info_dict() adds multiplex_instance_id
      -> PSYNC carries it across

    Portal boots
      -> ready() repoints EVENNIA_PORTAL_SERVICE_CLASS and PORTAL_SESSION_HANDLER_CLASS
      -> _init() builds our Portal service, which creates the one registry
      -> register_amp() puts our recording protocol on the AMP factory
      -> PSYNC arrives, the responder reads the name, the registry records the connection

The name comes from `MULTIPLEX_INSTANCE_ID`. A consumer that already names its instances aliases that
setting rather than maintaining two.

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

**`PortalSessionHandler.data_in` must be wrapped, not replaced.** It applies a character limit, a
command-rate limit, `clean_senddata` and a local echo before sending. Replacing it and sending
directly puts a malformed message on the wire, which surfaces inside the Server's input handling as
`too many values to unpack` — nowhere near the cause.

## What is built and not wired

Three pieces are complete and tested with nothing calling them. This is deliberate: each was built
before the wiring that invokes it.

- **`move_session`** — no trigger. Nothing can ask for a move.
- **`check_registration`** — no caller, and no place to call it from yet. See below.
- **`evennia_patch.install()`** — not called from `ready()`, and
  `AMP_CLIENT_PROTOCOL_CLASS` is not repointed at anything.

## The open seam

The startup check has to run **on the Server's AMP connection, immediately after the handshake**. That
ordering is not a nicety: it is what makes a single check trustworthy. `PSYNC` and the query go down
the same connection in order, AMP delivers in order, and the Portal records synchronously — so a "not
registered" answer cannot mean "not yet". From a timer or a service hook that guarantee is gone, the
race is real, and retries would be needed to paper over it.

The natural hook is the AMP client protocol's `connectionMade`, which is what sends the handshake. The
setting for it, `AMP_CLIENT_PROTOCOL_CLASS`, is resolved by `AMPClientFactory` and then **ignored** —
`buildProtocol` names the class directly. `evennia_patch` restores it.

So the chain is four links and only the first is built:

1. `evennia_patch.install()` — built, not called
2. `AMP_CLIENT_PROTOCOL_CLASS` repointed at a protocol class of ours — not done
3. That protocol subclass, overriding `connectionMade` — **does not exist**
4. `check_registration` called after the handshake — not wired

## Not designed yet

- **The move trigger.** The intended shape is a `MultiplexCommand` — its own AMP command, with a
  session id and a destination as declared arguments and an outcome as its response, so the Server
  learns whether the move happened. Nothing is built.
- **Where a session starts.** `PortalSessionHandler.connect()` is not routed, so a new session is
  announced to whichever Server spoke most recently rather than to the default instance. Input
  routing is correct; the initial announcement is not. A player can therefore be logged in on one
  instance while typing to another.
- **Broadcasts.** `disconnect_all` and `announce_all` reach one Server. Under several, a shutdown
  announcement would leave the others' sessions hanging.
- **Where an instance lands when none of the defaults is attached.** `MULTIPLEX_DEFAULT_INSTANCE`
  takes a single name today; an ordered list was discussed and not built.
