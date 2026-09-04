# CLAUDE.md

> **Project-wide working rules and cross-repo context live in the FCM umbrella repo's `CLAUDE.md`**,
> loaded automatically when you work from the umbrella root. If you opened this repo directly instead
> of via the umbrella, relaunch from the umbrella root for the full context. This file holds only this
> repo's specific instructions.

Instructions for Claude (and other LLM agents) working in this repository.

## What this project is

`evennia-portal-multiplex` runs several Evennia servers behind a single portal, and redirects a
player's session from one server to another on command — without the session being dropped or changed,
whatever protocol it is using. Tagline: **"One portal, many servers, one session."**

The mechanism is built and unit-tested. **It has never been run against live instances.** Read
[docs/architecture.md](docs/architecture.md) before touching anything — particularly its *built and
not wired* and *not designed yet* sections, which is where the loose ends are.

For the big-picture overview, read [README.md](README.md).
For the design wiki, read [docs/INDEX.md](docs/INDEX.md).

## Project status

**Built, unproven.** 83 tests, linters clean, no uncovered cases. Nothing has been booted. Booting a
Server and registering it is complete: it announces itself, confirms the Portal recorded it, and stops
if it did not. `move_session` is written, tested and has no trigger. See
[docs/progress.md](docs/progress.md).

## Where to read first

1. [docs/architecture.md](docs/architecture.md) — how it fits together, and what is unfinished.
   **Start here.**
2. [docs/test-plan.md](docs/test-plan.md) — the cases the library commits to. **A behavioural change
   starts here**, not in the code.
3. [README.md](README.md) — what the library is and its status.
4. [docs/INDEX.md](docs/INDEX.md) — map of all design docs.
5. [docs/interoperability.md](docs/interoperability.md) — this library against its siblings. Sections
   are present and unwritten.

## Load-bearing architectural principles

1. **The library does not own game concepts.** Rooms, exits, zones, characters and what makes a move
   legal at this moment belong to the consumer game. The library provides infrastructure; the consumer
   owns the game.

2. **No FCM-specific assumptions.** Any Evennia game running more than one server is a candidate
   consumer. FCM typeclass names, zone vocabularies and world layout stay in FCM.

3. **Test-first.** A case lands in [docs/test-plan.md](docs/test-plan.md), then the test, then the
   code. See [test-first-process.md](../../design/test-first-process.md) for the process and the
   rationale.

4. **Evennia's seams, not patches over it.** Everything installs by repointing a class setting that
   Evennia resolves later, so nothing wraps a live object at runtime. The one exception is
   `evennia_patch`, which exists solely because Evennia resolves `AMP_CLIENT_PROTOCOL_CLASS` and then
   ignores it — and it *restores* that setting rather than routing around it, so deleting it on a
   fixed Evennia changes no behaviour.

5. **The decision is split from the plumbing.** Registry, routing, binding and the move are plain
   functions taking what they need as arguments. The AMP responders and service overrides that call
   them are three lines each. That is what makes the logic testable without a running Portal, and it
   is worth keeping.

## Out of scope

- **Tickets and re-authentication.** A session moved this way never leaves the Portal, so there is no
  untrusted hop to authenticate across. Building ticket auth here would drag in a message bus and then
  an archive behind it, and would solve a problem this transport does not have. It stays with the
  consumer.
- **Why a session should move.** Rooms, characters, what makes a move legal at this moment: the
  consumer's. This library moves a session and has no opinion about the reason.
- **Anything needing a third dependency.** Evennia and the standard library, nothing else. If this
  library ever grows another dependency, that is the signal the boundary has moved and worth stopping
  to look at.

## Working conventions

- **Editing design docs.** Update or add design documents whenever an architectural decision is made
  or refined. Capture the *why*, not just the *what*. Index new docs in [docs/INDEX.md](docs/INDEX.md).
- **Don't put implementation detail in this file or README.** Link out to `docs/` instead. Keep
  CLAUDE.md and README.md stable; let `docs/` churn.
- **License.** BSD 3-Clause. Source files carry an SPDX header on the first line
  (`# SPDX-License-Identifier: BSD-3-Clause`).

## Documentation discipline (load-bearing)

Design documents in `docs/` must reflect decisions **actually discussed and agreed on with the project
owner**. They are not a place to forward-design the system from first principles or extrapolate
"reasonable defaults" from a starting point.

**Rules:**

1. **Only capture what was discussed and agreed.** If the conversation establishes a principle, do not
   extrapolate it into specifics that were not raised — command names, AMP message shapes, registration
   formats.
2. **Flag open questions explicitly.** Write `[TBD — needs discussion: <what is open>]` so a future
   session picks the topic up deliberately rather than inheriting an unagreed assumption.
3. **Smaller is better.** Three discussed points captured faithfully beat three discussed points plus
   seven invented ones.

The tempting sources of unasked-for answers here are `evennia-shards` and `evennia-scaling`. Both moved
a player's session between processes, so both have a shape ready to be lifted. A shape lifted from
either is an invention unless it has been discussed for this library.

## Repository layout

```
evennia-portal-multiplex/
├── CLAUDE.md                        # this file
├── README.md
├── LICENSE                          # BSD 3-Clause
├── pyproject.toml
├── runtests.py                      # standalone test runner; no gamedir required
├── .gitignore
├── examples/                        # three demo gamedirs. Never started
├── docs/                            # design wiki (humans + LLMs)
│   ├── INDEX.md
│   ├── architecture.md
│   ├── progress.md
│   ├── test-plan.md
│   ├── interoperability.md
│   └── archive/                     # historical context (currently empty)
├── src/
│   └── evennia_portal_multiplex/    # library code (src layout)
│       ├── __init__.py
│       ├── apps.py                 # AppConfig — the only way into either process
│       ├── config.py                # the two settings this library reads
│       ├── registry.py              # instance id -> live AMP connection
│       ├── services.py              # the Server and Portal service overrides
│       ├── amp.py                   # the Portal's AMP protocol
│       ├── amp_client.py            # the Server's AMP protocol and factory; the startup check's call site
│       ├── routing.py               # pointing one send at one instance
│       ├── binding.py               # which instance a session belongs to
│       ├── move.py                  # the three-step move
│       ├── query.py                 # MultiplexQueryRegistry
│       ├── startup.py               # refusing to start when unregistered
│       ├── launcher.py              # `evennia server_start`
│       ├── evennia_patch.py         # a local fix for an Evennia bug. Deletable
│       ├── log.py                   # shim onto Evennia's logger → portalmultiplex.log
│       └── tests.py                 # unit tests, run via runtests.py
└── tests/                           # standalone test infrastructure
    ├── __init__.py
    ├── test_settings.py
    └── urls.py
```

`examples/` holds three demo gamedirs — `server1` runs the Portal, `server2` and `server3` symlink its
source and run Servers only. All four settings files live in `server1/server/conf/` and cascade
through `settings_common.py`. **Never started.**

No `contrib/` and no `db_router.py` — nothing opt-in exists and the library owns no tables.

## Tools and environment

- Python 3.10+ (pinned via `pyproject.toml`).
- Runtime dependencies: `evennia`.
- **Tests use Django's test runner** via `runtests.py`, which bootstraps Django then calls
  `evennia._init()`, as the siblings do. No gamedir required.
- Dedicated venv at `evennia-portal-multiplex/venv/` (gitignored). Development install via
  `pip install -e .`.
