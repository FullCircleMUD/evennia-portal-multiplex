# Installing

What a game has to do to run several Servers behind one Portal. Everything here is settings and one
install line; the library has no tables, no migrations and no management commands.

The working example of all of it is [examples/](../examples/) — three instances sharing one source
tree, differing only in settings.

## Before you start

**Decide which instance runs the Portal.** One does. Every other instance runs a Server only and
attaches to it. That instance is the *default*: a player who connects and has not been moved anywhere
lands there.

**Give every instance a name.** They have to be distinct, or the second to attach replaces the first
in the Portal's registry and takes its sessions.

## Install

Evennia and the standard library are the only dependencies. Not on PyPI, so from a checkout:

```bash
pip install -e path/to/evennia-portal-multiplex
```

## Settings every instance needs

```python
INSTALLED_APPS = list(INSTALLED_APPS) + ["evennia_portal_multiplex"]

MULTIPLEX_INSTANCE_ID = "shard1"          # this instance's name. Distinct per instance
MULTIPLEX_DEFAULT_INSTANCE = "router"     # where an unmoved session belongs. The same on all
```

`INSTALLED_APPS` is what installs the library at all. Its `AppConfig.ready()` is the only way it gets
into either process, so without that line nothing happens and nothing says why.

If your game already names its instances — `evennia-message-bus` does — alias rather than maintain two
names for one thing:

```python
MULTIPLEX_INSTANCE_ID = MESSAGEBUS_INSTANCE_ID
```

Nothing checks the two agree. If they drift, a session is addressed by one name and routed by another,
and the only symptom is traffic arriving at the default while everything above believes it moved.

## Settings that differ per instance

**The Portal instance** listens on its own AMP port and is started normally:

```python
AMP_PORT = 4006
TELNET_PORTS = [4000]
```

```bash
evennia start --settings settings_router
```

**Every other instance** points `AMP_PORT` at the Portal instance's port. That is what makes its
Server dial there instead of expecting a Portal of its own:

```python
AMP_PORT = 4006          # the Portal instance's port, not one of ours
TELNET_PORTS = [4020]    # never listened on, but set distinctly — see below
```

Give them distinct telnet and web ports even though they never listen. Starting one fully by accident
then fails on something obvious, rather than several instances silently fighting over port 4000.

Each instance needs its own directory, because Evennia derives its database and logs from `GAME_DIR`,
which is the working directory it was started from.

## Starting a Server without a Portal

`evennia start` brings up a Portal too, which collides on the AMP port. `evennia istart` tells the
Portal to stop the Server it already has — so on a shared Portal it shuts down the instance you were
attached to. Neither is what you want.

This library adds a verb that starts a Server and speaks to no Portal at all. Declare it:

```python
EXTRA_LAUNCHER_COMMANDS = {
    "server_start": "evennia_portal_multiplex.launcher.server_start",
}
```

then, from that instance's directory:

```bash
evennia server_start --settings settings_shard1
```

Without the setting the verb does not resolve, and it fails silently — it falls through to Django and
is reported as an unknown command.

**`AMP_PORT` is the launcher's control channel as well as the Server's dial target.** So `stop`,
`reload` and `istart` run from a Server-only instance's directory all reach the *Portal instance*.
`server_start` is the only launcher verb safe to use from one.

Start the Portal instance first. `server_start` needs a live Portal at the address it dials.

## What a consumer calls

Two functions, and nothing about AMP:

```python
from evennia_portal_multiplex.move import PAYLOAD_KEY, send_session
from evennia_portal_multiplex.announce import broadcast_to_all_instances
```

**`send_session(session, destination, payload=None)`** hands one session to another instance. Returns
a Deferred resolving to `(moved, outcome)`. `moved` is true only for `MOVED` — `ALREADY_THERE` is
false, because asking to send a session where it already is means a bug worth seeing.

```python
def announce(result):
    moved, outcome = result
    if not moved:
        logger.log_err(f"{session} did not move: {outcome}")

send_session(session, "shard1").addCallback(announce)
```

One session per call. An account can hold several, and whether they all follow is your decision — loop
them if you want the account to move, and decide for yourself what to do when the third comes back
refused after the first two moved.

The arriving session is **not authenticated**: `uid`, `logged_in` and `puid` are cleared on the way,
because they are primary keys belonging to the instance being left. The player meets the destination's
login flow.

**The payload** is a dict carried to the destination — which archive to rebuild the session from, say.
It travels as JSON and lands in the session's `server_data`. Nothing in this library reads it back,
because nothing in this library runs on the destination: the session there is built by Evennia from
the sync data. Your code reads it:

```python
import json

payload = session.server_data.get(PAYLOAD_KEY)
if payload:
    archive_id = json.loads(payload)["archive_id"]
```

JSON types only. It is not a ticket — a moved session never leaves the Portal, so there is no untrusted
hop to authenticate across.

**`broadcast_to_all_instances(message)`** says something to every session on the Portal, whichever
instance owns it. Your Server's own `SESSION_HANDLER.announce_all` reaches only that instance's
players, which is the thing this exists to fix. It reaches every *session*, including anyone at the
login screen who has not authenticated.

## Outcomes

| Outcome | What happened |
|---|---|
| `MOVED` | The session is on the destination |
| `ALREADY_THERE` | It was already there. Nothing was sent |
| `NOT_ATTACHED` | The destination is not attached to this Portal. Nothing was sent |
| `NO_SUCH_SESSION` | The Portal does not hold that session id — usually a player who disconnected mid-move |
| `REJECTED` | The destination would not take it, so it was put back where it was |
| `STRANDED` | It was released, refused, and the origin would not take it back. The player has to reconnect |

## What is not checked for you

- **That the required settings are set**, at boot. They raise when read, which on a Portal is when a
  player connects.
- **That a Server actually registered** — that one *is* checked. An instance whose announcement did
  not reach the Portal logs the reason and stops, rather than running unreachable. `server_start`
  reports it at the terminal.
