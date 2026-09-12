# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-12 — an instance with no settings refuses to start

The library validated its two required settings inside the accessors that read them, and nothing called
those at boot. Every sibling with required settings does it the other way — `check_settings()` in
`AppConfig.ready()`, one `ImproperlyConfigured` naming every problem — and this is now the same shape as
`evennia-archive`, `evennia-scaling`, `evennia-llm-service`, `evennia-database-cascade` and `fcm-xrpl`.

**The gap that mattered was `MULTIPLEX_DEFAULT_INSTANCE` on a Portal.** It is read Portal-side, in
`binding.instance_for_session`. Left to the read, the Portal booted clean and raised on the first
player's connect — a live deployment failing one player at a time, for a line missing from a settings
file.

**The check runs before the install line**, so an instance writes a refusal or `Installed on '<name>'`
and never both. That makes the install line mean started *and* configured, and it retires `IN-23`, which
had asserted the opposite: that an unset instance id was reported in the log rather than refusing the
boot. The defensive read that case protected is gone with it.

**Both accessors are now plain reads.** A required setting cannot survive the boot check to reach one,
so a raise there would be a contract for a condition that can no longer occur — see
[library-standards.md](../../../design/library-standards.md) § *Reading settings*.

**Proven against the demo.** Three instances started and attached; a telnet login landed on the default
instance; a live `send_session` moved that session from server1 to server2 on the same socket. Then, per
broken settings file:

```
ImproperlyConfigured: evennia-portal-multiplex cannot start: MULTIPLEX_INSTANCE_ID is not set. …
ImproperlyConfigured: evennia-portal-multiplex cannot start: MULTIPLEX_DEFAULT_INSTANCE is not set. …
ImproperlyConfigured: evennia-portal-multiplex cannot start: MULTIPLEX_INSTANCE_ID … MULTIPLEX_DEFAULT_INSTANCE …
```

`evennia server_start` with a broken file refused in `init_game_directory` and nothing daemonised. The
Server's own log carried the three refusals at ERROR with no `Installed on` line between them.

**One thing left for a sibling.** `evennia-scaling` reads `get_instance_id()` from this library and
relied on the accessor raising `ImproperlyConfigured` with the setting named; a plain read makes that an
`AttributeError`, and app `ready()` order is `INSTALLED_APPS` order. The clause belongs in scaling's own
`check_settings()`.

155 tests, all three linters clean.

## 2026-09-11 — a session whose instance dies is no longer left typing into nothing

**The bug, proven live before it was fixed.** A session was moved to server2, server2 was killed, and
three commands were typed. The player saw nothing. server1 logged nothing. The Portal logged nothing.
The socket stayed open and healthy and the prompt never answered again.

`binding.connection_for` ended in `or registry.default_connection()`, so a session whose instance had
gone had its traffic sent to the default instead. The default was never told that session existed — the
move sends `PDISCONN`/`PCONN`, and a fallback sends neither — so it discarded every message without a
word. The code read as a recovery path and recovered nothing.

**What the registry was throwing away.** `forget()` deleted the instance's name, which made a dead
shard indistinguishable from a typo. Both surfaced as `None`. The name now stays, mapped to nothing, and
`is_known` answers the other half: an unknown name still falls back to the default, because that is
reasonable for a name nobody ever attached under, while a dropped one does not.

**Why there is a wait rather than an immediate decision.** Evennia's `AMPClientFactory` is a
`ReconnectingClientFactory` with `initialDelay` 1, `factor` 1.5 and `maxDelay` raised to 10 in its
`__init__`, retrying indefinitely. So a reload, a crash under a process manager or a network blip is
back inside ten seconds and only a dead machine stays gone. Acting at once would fire on every routine
shard restart, and telling the player anything final would be wrong almost every time.

The Portal cannot see those redial attempts — they happen at the other end — so it polls its own
registry entry once a second for ten. One wait per instance: a shard with forty players drops once, and
a command arriving mid-wait joins it rather than starting another.

**What the player is told, and nothing about our mechanism:** their connection is lost and is being
reconnected; then either it is back, or they are being moved. On the timeout each session is moved
individually, and one that the default will not take is told the game is unreachable and disconnected —
at that depth the game is down rather than one shard of it, and no further fallback is worth having.

**The move needed two guards, not a second function.** `move_session`'s first act is `PDISCONN` to the
origin, and here the origin is what died — so there is nothing to send it down and nothing to send it
to, that Server's session having gone with the process. It is skipped. The rollback is skipped for the
same reason and resolves to `STRANDED`, which already means *on no instance*. Nothing about a move
between two live instances changed.

`CLAUDE.md`'s *Why a session should move* now carries its one exception. The library moving a session
uninvited is error handling rather than policy, and no outcome is returned to anyone because nobody
asked.

**The first live run crashed, and 148 green tests had not noticed.** `_tell` called `session.msg()`,
and a Portal session is a protocol — `TelnetProtocol` has no such method. The suite's sessions were bare
`mock.Mock()`, which answer to any attribute you invent, so the wrong method name passed everywhere and
raised in the Portal. The tests were fixed first, with a `spec_set` session carrying only what a real
one has, confirmed to reproduce the crash, and only then the code changed to
`data_out(text=[[message], {}])` — the shape Evennia's own `announce_all` builds.

**Both paths then proven live.** A session on server2, server2 killed:

```
Your connection to the game server has been lost. Reconnecting...
Reconnected.
INSTANCE=server2          # same socket, never reconnected, play carried on
```

And with server2 left dead:

```
Your connection to the game server has been lost. Reconnecting...
Could not reconnect you. Moving you to the default server.
 Welcome to Server1
INSTANCE=server1
```

The Portal's own log across both:

```
'server2' has dropped and 1 session(s) are waiting for it. Holding them for 10s...
'server2' did not come back within 10s. Moving 1 session(s) to 'server1'.   [WARN]
'server2' is back; its sessions resume.
```

148 tests, all three linters clean.

## 2026-09-11 — the Portal says who attached, and every instance says it installed

The library logged almost nothing on the Portal side. Two places now do, both chosen for what they
give somebody diagnosing a fault rather than for completeness.

**The registry reports an attach, and a replacement.** A first registration records that the instance
reached this Portal. A registration that displaces a *different* connection says so instead — which is
either a Server that restarted before the Portal noticed the old connection drop, or two Servers
configured with the same id, where the second takes the first's sessions and leaves it attached and
unreachable. The registry cannot tell those apart, so both lines are INFO and report rather than rule.
Re-registering the *same* connection is silent: `record_announcement` runs on any admin message
carrying the name, and a replacement that replaced nobody is noise in the line a reader is looking at
during an incident. IR-10, IR-11, IR-12.

**`ready()` records the install, and what the instance calls itself.** Left out of `INSTALLED_APPS` the
library runs nothing and reports nothing, and moves to that instance quietly do nothing. This line is
what makes an absent `portalmultiplex.log` mean *never imported* rather than *nothing to say*. The
instance id is read defensively and only for the line — an unset setting is reported in it rather than
becoming a boot failure, because a log line does not get to decide whether a Server starts. IN-22,
IN-23.

`docs/installing.md` now carries a *Where it logs* section: every line the library writes, and what
each one means.

**Parked: the routing fallback.** `binding.connection_for` falls back to the default instance when a
session's own instance is not attached — per message, resolved fresh each time, with no `PCONN` sent,
so the default Server receives traffic for a session it was never told to build. `get_all_sync_data`
answers the same question the opposite way ("a session bound to an instance that is not attached syncs
to nobody"). Logging it was proposed and deferred: what that fallback *should* do is the question, and
a line describing behaviour that may change is worth nothing.

123 tests, all three linters clean.

## 2026-09-11 — logging through the extension, and clean against the standards

`log.py` is three lines. `portal_multiplex_log` now binds through `evennia-logging-extension`'s
`make_logger`, writing to the same `portalmultiplex.log` as before with the same
`(message, level, trace)` signature — so no call site, import or test changed. The extension is
declared in `pyproject.toml` and installs as an editable sibling checkout; `examples/requirements.txt`
carries it above the library.

What that buys is the pre-reactor window. `startup.py` logs its refusal at ERROR before it raises, and
`AppConfig.ready()` runs before there is a reactor to defer a write to — the extension writes
synchronously when there is none.

The standards pass went with it:

- `docs/interoperability.md` written in full — every sibling in `libraries/`, each naming a
  relationship and carrying a clearance that says why it is clear.
- `docs/installing.md` on a numbered spine, seven steps in the order a consumer does them, with
  required and optional settings stated.
- Every module-level constant declared in `config.py`. The documented import paths are unchanged:
  `from evennia_portal_multiplex.move import PAYLOAD_KEY, send_session` still resolves, which matters
  because `evennia-scaling` uses it.
- Every Evennia import carries a comment saying why that module needs the engine.
- `syncing.py`'s module state is `_syncing_instance_id` — lower case, because it is rebound at runtime
  and never was a constant.

118 tests, all three linters clean. Validated live: three instances up, a session moved
server1 → server2 on one unbroken telnet socket, a broadcast reaching it, and the level and trace paths
landing in `portalmultiplex.log` with no `pre-startup.log` anywhere.

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
