# evennia-portal-multiplex

Run several [Evennia](https://www.evennia.com/) servers behind a single portal, and redirect a player's
session from one server to another on command — without the session being dropped or changed, whatever
protocol it is using.

## Why

Evennia runs one Portal holding every player's socket, and one Server running the game. That is a
sound split — it is why a telnet session survives `evennia reload` — but it assumes exactly one
Server. Everything the Portal sends goes to whichever Server attached most recently.

If you want several Servers, on one machine or several, this makes each one addressable and lets a
session be handed between them. The player's socket never moves: only the Server it is fed to changes.
Nothing is dropped, nothing renegotiates, and it works the same whatever protocol the player is on.

## Status

**Working, proven live.** 118 tests, and run against live instances: three Servers behind one Portal,
with a session moved between them repeatedly on one unbroken connection — telnet and WebSocket
alike, and with no protocol-specific code for either. A Server registers with its Portal on connect
and refuses to start if that did not land; a player connecting lands on the default
instance and everything said about their session follows it; a Server can ask for one of its sessions
to be handed to another instance and is told the outcome; and an admin can reach every player on every
instance at once.

Telnet over SSL, SSH and the AJAX web client are untested.

Early. One machine, demo gamedirs, and it turned up things still to work out — see
[docs/progress.md](docs/progress.md) for what those runs proved and
[docs/architecture.md](docs/architecture.md) for what they left open.

## Is this for me?

Not yet, unless you are working on it. When it is finished, it is for an Evennia game that wants more
than one Server — to spread load, to run parts of a world separately, or to move a player between
processes without dropping them.

It has no opinion about *why* you are moving someone. Rooms, characters, what makes a move legal at
this moment: all yours. This moves a session between Servers and nothing else.

## Install

Not published. From a checkout:

```bash
git clone https://github.com/FullCircleMUD/evennia-portal-multiplex.git
cd evennia-portal-multiplex
python -m venv venv
# Activate the venv (platform-specific)
pip install evennia
pip install -e .
python runtests.py
```

## Learn more

- **[docs/architecture.md](docs/architecture.md)** — how it works and what is unfinished. Start here.
- **[docs/INDEX.md](docs/INDEX.md)** — index of design documents.
- **[docs/test-plan.md](docs/test-plan.md)** — every behaviour the library commits to, and the test
  covering it.
- **[docs/interoperability.md](docs/interoperability.md)** — how this library sits alongside its
  siblings.
- **[CLAUDE.md](CLAUDE.md)** — load-bearing principles, for working in the repository itself.

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
