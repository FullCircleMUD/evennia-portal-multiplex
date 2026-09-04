# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

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
