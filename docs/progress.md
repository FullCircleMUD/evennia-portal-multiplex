# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-04 — proven on SSH as well

A session moved server1 -> server2 -> server3 -> server1 over SSH, in one connection. SSH negotiates a
pty and holds a real terminal, and neither noticed the far end changing.

Three transports now, and the same amount of protocol-specific code in each: none. `evennia-scaling`
can move a browser and nothing else, and needs five modules to do it.

The demo offers SSH so there is something to prove that against. It needs `bcrypt` and `pyasn1`, which
Evennia does not pull in — see `examples/requirements.txt`. Evennia generates its own host keypair on
first start, so there is nothing to make by hand.

Still untested: telnet over SSL, and the AJAX web client. SSL is telnet with a TLS wrapper. AJAX is
the one to be least confident about — it is long-polling rather than a held socket, so "the socket
never moves" means something different there.

## 2026-09-04 — proven on WebSocket, with no WebSocket code

A browser session moved server1 → server2 → server3 → server1 in one tab. No reconnect, no page
reload, no ticket, no URL parameter, no injected JavaScript. `protocol_key` confirmed `websocket`
rather than the AJAX fallback.

**Nothing in the library was written for it.** The move is `PDISCONN` and `PCONN` on the AMP link and
never touches the socket, and `connect`, `sync`, `disconnect` and `data_in` are on the session handler
every protocol shares. A WebSocket session moves for the same reasons a telnet one does.

That is the difference from `evennia-scaling`, which needs a protocol override, a middleware, a ticket
table, a redemption path and IP pinning to move a browser — and can only do it for browsers.

Untested at the time: telnet over SSL, SSH, and the AJAX web client.

## 2026-09-04 — a Server is handed only its own sessions

118 tests, both linters clean, and verified live.

A Server that attaches sends `PSYNC`, and Evennia answers with every session the Portal holds. With
three Servers each attaching one was handed the others' players, built a `ServerSession` for each, and
attached any carrying a `uid` to its own account of that number. The reply is now filtered to the
sessions bound to the instance that asked.

Carried by `syncing.py`: the responder knows who asked, `get_all_sync_data` builds the payload and
takes no arguments, and Evennia's own handler sits between them. Same shape as `routing.sending_to`.
The responder now registers the connection *before* calling `super()`, because the reply is built
inside it.

**Proven live, and the ordering is what makes the proof.** `test` logged in on server1 at 20:45:01;
server3 was killed and restarted at 20:46:30, so its handshake happened with `test`'s session live on
the Portal. server3 came back holding one session — the superuser's, bound to it — and not `test`'s.
Two earlier attempts at this test proved nothing, both because the instance had attached before the
second session existed and so had nothing to wrongly adopt.

The same run showed a session surviving its instance being killed and returning to it, which is the
binding being a name rather than a connection.

## 2026-09-04 — run live, three instances, one Portal

First run against live instances. Three Servers behind one Portal, and a telnet session moved between
them seven times on one unbroken connection — then an eighth move, of somebody else's session,
requested by a superuser who stayed where they were.

What that proves, in the order it happened:

- **Registration.** Each Server announced itself, asked the Portal what it was holding, found itself
  in the answer, and carried on. `attached: ['server1', 'server2', 'server3']`, read from in-game.
- **Refusing to start.** server2's first attempt failed against a Portal that had no responder. It
  logged the reason, stopped, and `server_start` reported it at the terminal with a pointer to the
  log — which is how the misconfiguration was found at all.
- **Reconnection.** An unrelated AMP drop reconnected and re-registered with nothing written to the
  error log.
- **Moving.** Seven moves across all three instances, on one socket. The destination's login screen
  arrives on the same connection and the session is unauthenticated, as intended.
- **The outcome.** `(True, 'moved')` came back to the superuser who asked. It is not visible when you
  move your own session, because that session has left before the answer arrives.

What the run found, all recorded in [architecture.md](architecture.md) under *Not designed yet*:

- `PSYNC` hands every session to whichever Server just attached, so each instance believes it owns
  every session — and each attach announces `SERVER_RESTART_MSG` to all of them.
- A move announces a disconnect to the players left behind. Not established as a problem.
- A player who moves sees the restart message; a player moved by somebody else does not. Unexplained.

Two things cost time and neither was the library: a typo in `--settings`, which Evennia answers by
silently falling back to the default settings file, and a `py` one-liner whose lambda could not see
`self` — an unhandled error in an AMP callback drops the whole connection.

## 2026-09-04 — an admin can reach every player again

107 tests. `broadcast_to_all_instances(message)` sends a message to every session on the Portal,
whichever instance owns it.

An admin command that messages everyone calls `SESSION_HANDLER.announce_all` on its Server. On a
single-instance game that reaches every player; under several it reaches one instance's sessions, and
the same game code quietly becomes partial. That is a regression this library causes rather than a
feature it is being asked to add, which is why it belongs here.

The Portal's own `announce_all` already reaches everybody, because it holds every socket. Nothing in
Evennia lets a Server ask for it, so what was built is the asking: a command, and a responder that
passes the message straight through. It reaches every *session*, including anyone at the login screen
who has not authenticated.

## 2026-09-04 — a Server can ask for a move

103 tests, linter clean. The last of the three processes closed, and with it the only piece that had
been built with nothing calling it.

- **`send_session(session, destination, payload=None)`** — the consumer's whole API. Returns a
  Deferred resolving to `(moved, outcome)`. One session per call: an account can hold several, and
  whether they all follow is a game decision.
- **Five outcomes, named** — `MOVED`, `ALREADY_THERE`, `NOT_ATTACHED`, `REJECTED`, `STRANDED`, plus
  `NO_SUCH_SESSION` when the Portal does not hold the id. All come back the same way, so a caller
  never has to remember which failures arrive by which route.
- **The move puts a session back when a destination refuses it.** The origin has already let go by
  then. The identity captured before it was cleared is restored, the session is rebound, and the same
  build step runs again pointing at the origin — which is Evennia's own reload, applied to one session.
- **An optional payload rides with the move** — a dict, JSON on the wire, landing in the session's
  `server_data`, which the sync data already carries. Context, not a ticket: a moved session never
  leaves the Portal, so there is no untrusted hop to authenticate across.

## 2026-09-04 — a session lands where its input goes

88 tests. `connect`, `sync` and `disconnect` now route the same way `data_in` already did, so all four
things the Portal says about a session resolve through `connection_for` and cannot pick different
Servers.

`disconnect_all` is the one that is not routed but broadcast: a Portal shutting down tells every
attached instance to drop everything it holds, then Evennia closes the Portal's own sockets. Sent
once, the other instances carried on believing their players were still connected. `announce_all`
needs nothing — it writes to the Portal's own sockets and never involves a Server.

Unrouted, they went to whichever Server had last spoken to the Portal while everything typed went to
the default: the session was created on one Server and spoken to on another that had never heard of
it — a login screen, and then nothing the player typed doing anything. Whether it bit depended on AMP
timing at boot.

That completes a player connecting, from the socket opening to the Portal shutting down.

## 2026-09-04 — a Server refuses to start when it is not registered

83 tests, both linters clean, no uncovered cases. Booting a Server and registering it is complete end
to end: it announces itself, confirms the Portal recorded it, and stops if it did not — with the reason
in the log, the fact at the terminal, and a non-zero exit for a process manager. Nothing has been
booted; this is the unit-tested state.

- **The Server's AMP client protocol** — `connectionMade` sends the handshake, asks the Portal what it
  recorded, and hands the answer to `check_registration`. One errback covers the three ways this can
  fail; a Portal that does not speak the query is named as not running this library.
- **Stopping, not raising** — a raise out of `connectionMade` is logged by Twisted and the reactor
  carries on. `reactor.stop()` brings the services down in order, so the reason reaches the log.
- **`AMP_CLIENT_PROTOCOL_CLASS` is layered like the other three**, and `evennia_patch.install()` runs
  from `ready()` ahead of it — unpatched, Evennia resolves that setting and ignores it.
- **A Portal that was never reached is named** — host and port, off the connector, from the factory's
  `clientConnectionFailed`. That path never reaches `connectionMade`, so none of the check above is on
  it. Evennia logs the failure already; what it does not say is which Portal, which is the only
  question worth asking once there are several instances.
- **`server_start` checks that the Server came up** and says so at the terminal when it did not,
  pointing at the log. twistd has daemonised by the time a Server refuses, so without this the
  operator gets silence.
- **A non-zero exit**, on an after-shutdown trigger. From a terminal it changes nothing; under a
  process manager it is the difference between being retried and staying down, and after a reboot the
  cause is usually just the Portal not listening yet.

## 2026-09-04 — the mechanism, built and tested

67 tests, linter clean, one uncovered case. Everything below is unit-tested against fakes; **none of
it has ever been run against live instances.**

Built and wired:

- **The registry** — instance id to live AMP connection. Removal matches on connection identity, so a
  reconnecting instance's replacement survives the old connection's late disconnect.
- **Announcement and recording** — a Server names itself in the `info_dict` it already sends on
  `PSYNC`; the Portal reads it off that handshake and records the connection it arrived on.
- **Routing** — one send pointed at one instance, restored in a `finally`.
- **Session binding** — which instance a session belongs to, held as a name so a Server that restarts
  is followed rather than a dead connection kept.
- **The move** — release, clear identity, build. No socket operations anywhere in it.
- **The registry query** — `MultiplexQueryRegistry`, a Server asking its Portal what is attached.
- **The startup check** — refusing to start when this instance is not registered.
- **`evennia server_start`** — a launcher verb that starts a Server without stopping another.
- **Installation** — `AppConfig.ready()` repointing three class settings, one registry shared by all
  three of the pieces that need it.
- **A patch for an Evennia bug** — `AMP_CLIENT_PROTOCOL_CLASS` is resolved and then ignored. Restored
  rather than routed around, so the patch is deletable when the upstream fix lands.

Built and **not wired** — see [architecture.md](architecture.md):

- `move_session` has no trigger
- `check_registration` has no caller, and the seam it needs is open
- `evennia_patch.install()` is not called

Demo harness: three gamedirs under `examples/`, `server2` and `server3` symlinking `server1`'s source
so game-side code written to exercise the library exists once. Settings cascade through
`settings_common.py`. Never started.

## 2026-09-04 — brought over from evennia-scaling

Seven modules and 44 tests were built inside `evennia-scaling` between commits `0d90f34` and `9d38493`,
then moved here once it was clear that running several Servers behind one Portal is a different
concern from moving a character between instances. This library knows nothing about archives,
characters or accounts, and depends on nothing but Evennia.

The decision point is recorded in scaling's commit `fb4e54f`, which removed them there. Scaling's
`src/` is byte-identical to where it was before that work began.

Renamed on the way over: the router became the *default instance*; `MESSAGEBUS_INSTANCE_ID` and
`SCALING_ROUTER_ID` became `MULTIPLEX_INSTANCE_ID` and `MULTIPLEX_DEFAULT_INSTANCE`, declared by this
library rather than borrowed. A consumer aliases them to keep one name per instance.

**What was proven before any of it was written.** A throwaway spike inside `evennia-scaling` ran the
whole mechanism live — a telnet session moved between two Servers five times on one unbroken
connection, and a fresh login landed on the intended instance. That spike is on the
`spike/amp-session-move` branch of `evennia-scaling`. It is the only version of this that has ever
worked end to end, and is worth comparing against if the rebuilt one behaves differently.

Four things it cost an evening to learn, each silent, each now pinned by a case:

- An AMP responder must be re-registered, not overridden (AR-07, QY-07)
- `factory.server_connection` is the routing variable, not `portal.amp_protocol` (RT, MV-05)
- `PortalSessionHandler.data_in` must be wrapped, not replaced
- Wrapping `evennia._init()` stops the Portal starting, before twistd's logger exists, so it fails
  invisibly. The service-class settings seams do the same job properly.

## 2026-09-04 — repository scaffolded

Library-standards structure only: `pyproject.toml`, `runtests.py`, the `src/` layout, `tests/`
infrastructure on Evennia's settings defaults, the `log.py` shim writing to `portalmultiplex.log`,
`CLAUDE.md`, `README.md` and the `docs/` set.
