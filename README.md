# evennia-portal-multiplex

Run several [Evennia](https://www.evennia.com/) servers behind a single portal, and redirect a player's
session from one server to another on command — without the session being dropped or changed, whatever
protocol it is using.

## Status

**Scaffold.** The repository structure, test infrastructure and logging shim are in place. There is no
library code and no public surface yet, and nothing about the design has been agreed beyond the
description above. See [docs/progress.md](docs/progress.md) for the milestone log.

## Is this for me?

Not yet — there is nothing to install. This section gets written once the surface exists.

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

- **[docs/INDEX.md](docs/INDEX.md)** — index of design documents.
- **[docs/test-plan.md](docs/test-plan.md)** — every behaviour the library commits to, and the test
  covering it.
- **[docs/interoperability.md](docs/interoperability.md)** — how this library sits alongside its
  siblings.
- **[CLAUDE.md](CLAUDE.md)** — load-bearing principles, for working in the repository itself.

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
