# Interoperability

This library against every sibling library in `libraries/`, including itself. A reader deciding
whether two of our libraries can be co-installed gets a definite statement from either side rather
than inferring from silence.

Each section names the relationship — **hard dependency**, **optional integration**, or **no
coupling** — followed either by the constraints that apply or by an explicit clearance stating *why* it
is clear in terms of what this library does. "No known issues" is not a clearance.

**Three properties make most of the clearances below hold**, and a section resting on them says so
rather than restating them:

- **It owns no tables and issues no ORM writes.** No models, no migrations, no router, no alias. A
  library that constrains the database has nothing here to constrain.
- **Its work is transport, on the reactor thread.** It decides which Server a session's traffic goes to.
  It holds no game object, searches for none, and dispatches nothing off the reactor.
- **Nothing of this library runs on the destination of a move.** The session there is built by Evennia
  from the sync data.

**The one thing it does that a sibling can see is the shape it creates, not a call it makes.** Running
several Servers means every library installed in them runs once per instance — its `at_server_start`,
its persistent scripts, its in-process caches, its clocks. And a session can leave one Server for
another mid-play, arriving **unauthenticated**: `uid`, `logged_in` and `puid` are cleared on the way,
because they are primary keys belonging to the instance being left. Where a section below has a real
consideration, it is almost always one of those two.

Whether two instances share a database is the consumer's settings, not this library's business —
Evennia derives each instance's database from its `GAME_DIR`, and the demo gamedirs in
[examples/](../examples/) leave them separate.

## evennia-ai-memory

**No coupling.** Neither library imports the other. It owns tables on an alias of its own and adds a
database router; this library owns none and adds none, so there is nothing to collide over.

The consideration is the per-instance shape. NPC memory is rows in whatever database the instance
holding the conversation reads, so a player moved to a second Server meets NPCs with that instance's
memory of them. Pointing both instances at one memory database is a consumer settings decision and
ai-memory's rules apply to it unchanged.

## evennia-archive

**No coupling.** Neither library imports the other, and archive's
[interoperability.md](../../evennia-archive/docs/interoperability.md) states it from its side.

Worth knowing rather than a constraint: the move carries an optional payload — a JSON dict stamped into
the arriving session's `server_data` — and an archive id is the example it was designed around. This
library does not read it and has no opinion about what it means. `evennia-scaling` uses it for exactly
that.

## evennia-calendar

**No coupling.** Neither library imports the other, and calendar's
[interoperability.md](../../evennia-calendar/docs/interoperability.md) states it from its side: it
reads a clock inside the Server process and touches no connection.

The per-instance shape applies — each Server runs its own copy of whatever calendar starts at boot.
Whether two instances then agree about the time is calendar's question, not this library's.

## evennia-database-cascade

**No coupling.** Neither library imports the other. Cascade's
[interoperability.md](../../evennia-database-cascade/docs/interoperability.md) states it from its side:
this library owns no models and its work is on the Portal rather than in the ORM.

Cascade resolves its aliases inside each Server process, so each instance resolves its own. That is the
per-instance shape, and the rules for what may take an alias are cascade's.

## evennia-equipment

**No coupling.** Neither library imports the other. Equipment hangs state on game objects as
Attributes; this library moves a *session* and never touches a character. Nothing equipment stores
travels on a move, and it does not need to: the session arrives unauthenticated and the destination
builds its own character through its own login flow.

## evennia-llm-service

**No coupling.** Neither library imports the other. It makes provider calls from the Server process,
and this library has no opinion about what a Server does with the sessions it holds.

One consideration, and it belongs here because the move is what causes it: **a call in flight when a
session moves has nowhere to deliver.** The move tells the origin Server to release the session, and
the origin tears its own session down — so a reply arriving afterwards is for a session that instance
no longer has. A consumer that moves sessions while waiting on a provider handles that itself; this
library refuses nothing on those grounds, because it cannot see the call.

## evennia-logging-extension

**Hard dependency** — the one sibling this library imports. `log.py` binds `portal_multiplex_log`
through its `make_logger`, and every line the library emits goes through that binding to
`portalmultiplex.log`. It is not on PyPI, so it installs as an editable sibling checkout — see
[installing.md](installing.md).

Nothing flows the other way: the extension knows nothing about the multiplex, and owns no tables.

## evennia-message-bus

**No coupling.** Neither library imports the other. The bus owns tables and a router; this library owns
neither.

**Both libraries name instances, and nothing checks the two names agree.** This library reads
`MULTIPLEX_INSTANCE_ID`; the bus reads `MESSAGEBUS_INSTANCE_ID`. Running both, alias one to the other
rather than maintaining two names for one thing — [installing.md](installing.md) carries the line. If
they drift, a session is addressed by one name and routed by another, and the only symptom is traffic
arriving at the default instance while everything above believes it moved.

## evennia-mob-spawner

**No coupling.** Neither library imports the other. It spawns and maintains mobs in a Server process;
this library decides which Server a player's input reaches and owns no game concepts.

The per-instance shape applies, and it is the sharpest case of it: spawner keeps one persistent script
per rule-set file, and several Servers means several copies of that script unless the consumer decides
which instance loads which rule-set. That decision, and what spawner's script does when more than one
runs, are spawner's to document.

## evennia-portal-multiplex

This library.

## evennia-scaling

**Hard dependency in the other direction, and the asymmetry is the point.** Scaling imports this
library; nothing here imports scaling, and nothing here knows it exists.

Scaling's [interoperability.md](../../evennia-scaling/docs/interoperability.md) owns the constraints,
and they follow from the two facts in the preamble above: its `handoff.py` calls `send_session` for the
move, carries its ticket in the payload, and everything it does on arrival follows from the session
arriving unauthenticated.

**Why a session should move remains the consumer's** — see [CLAUDE.md](../CLAUDE.md). Scaling answering
that question for FCM does not make it this library's question.

## evennia-shards

**No coupling.** Neither library imports the other, and nothing in either reads the other's settings.

The overlap is conceptual only, and worth naming so it is not mistaken for a coupling: both move a
player between processes. Shards does it with several Server processes over one shared database; this
one keeps the socket on the Portal and never touches a database at all. A shape lifted from shards is
an invention here unless it has been discussed for this library — [CLAUDE.md](../CLAUDE.md) says so and
means it.

## evennia-survival

**No coupling.** Neither library imports the other, and survival's
[interoperability.md](../../evennia-survival/docs/interoperability.md) states it from its side: its tick
reads the local `SESSION_HANDLER`, so a character is ticked by whichever instance currently holds its
session. That is the per-instance shape, read from survival's end.

## evennia-targeting

**No coupling.** Neither library imports the other. Targeting is predicates over game objects, with no
engine state of its own and nothing per-session — so neither the per-instance shape nor the move is
visible to it.

## evennia-world-builder

**No coupling.** Neither library imports the other. It builds rooms and exits in a database; this
library owns no world and moves a session between processes.

The per-instance shape applies: each instance builds from whatever database its settings name. Whether
two instances share one world, or run different parts of one, is the consumer's decision and the reason
someone runs this library at all.

## evennia-yaml-reader

**No coupling.** Neither library imports the other. It reads YAML from a local path or GitHub and needs
no engine — nothing it does is per-session or per-instance.

## fcm-telemetry-spawn

**No coupling.** Neither library imports the other. It is a scaffold with no library code and no public
surface, so there is nothing yet to constrain in either direction.

## fcm-xrpl

**No coupling.** Neither library imports the other. It is a scaffold with no library code extracted
yet, so there is nothing yet to constrain in either direction.
