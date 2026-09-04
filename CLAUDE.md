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

That description is the whole of what has been agreed. **Nothing about the mechanism is decided** — not
how a server is registered, not what the command looks like, not how the redirect is carried over AMP,
not what state moves with the session or whether any does. Do not infer any of it from the library's
name, from the sibling libraries, or from how Evennia happens to work today. It is decided in
conversation, recorded in `docs/`, and only then built.

For the big-picture overview, read [README.md](README.md).
For the design wiki, read [docs/INDEX.md](docs/INDEX.md).

## Project status

**Scaffold.** Structure, test infrastructure and the logging shim only — no library code and no public
surface. See [docs/progress.md](docs/progress.md).

## Where to read first

1. [docs/test-plan.md](docs/test-plan.md) — the cases the library commits to. **A behavioural change
   starts here**, not in the code. Currently empty.
2. [README.md](README.md) — what the library is and its status.
3. [docs/INDEX.md](docs/INDEX.md) — map of all design docs.
4. [docs/interoperability.md](docs/interoperability.md) — this library against its siblings. Sections
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

Library-specific principles land here as they are agreed. There are none yet.

## Out of scope

`[TBD — needs discussion: nothing has been ruled out. Scope is decided as concrete questions arise,
by applying the principles above, and the rulings are recorded here.]`

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
├── docs/                            # design wiki (humans + LLMs)
│   ├── INDEX.md
│   ├── progress.md
│   ├── test-plan.md
│   ├── interoperability.md
│   └── archive/                     # historical context (currently empty)
├── src/
│   └── evennia_portal_multiplex/    # library code (src layout)
│       ├── __init__.py
│       ├── log.py                   # shim onto Evennia's logger → portalmultiplex.log
│       └── tests.py                 # unit tests, run via runtests.py
└── tests/                           # standalone test infrastructure
    ├── __init__.py
    ├── test_settings.py
    └── urls.py
```

No `examples/` yet (no demo gamedirs), and no `contrib/` (nothing opt-in exists; the standards forbid
scaffolding one empty). No `config.py` or `db_router.py` — the library reads no settings and owns no
tables yet. When it reads its first setting it gets a `config.py` accessor rather than a direct
`settings.` read, and if it ever owns tables they go on an alias of its own behind its own router; see
[library-standards.md](../../design/library-standards.md).

## Tools and environment

- Python 3.10+ (pinned via `pyproject.toml`).
- Runtime dependencies: `evennia`.
- **Tests use Django's test runner** via `runtests.py`, which bootstraps Django then calls
  `evennia._init()`, as the siblings do. No gamedir required.
- Dedicated venv at `evennia-portal-multiplex/venv/` (gitignored). Development install via
  `pip install -e .`.
