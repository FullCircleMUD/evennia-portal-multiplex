# Installing

What a game has to do to run several Servers behind one Portal. Everything here is settings and two
install lines; the library has no tables, no migrations and no management commands.

The working example of all of it is [examples/](../examples/) — three instances sharing one source
tree, differing only in settings.

## Before you start

**Decide which instance runs the Portal.** One does. Every other instance runs a Server only and
attaches to it. That instance is the *default*: a player who connects and has not been moved anywhere
lands there.

**Give every instance a name.** They have to be distinct, or the second to attach replaces the first
in the registry and takes its sessions.

## 1. Install the packages

Evennia, and `evennia-logging-extension` for the library's own log file. Neither this library nor the
extension is on PyPI, so both install from a checkout — the extension first:

```bash
pip install -e path/to/evennia-logging-extension
pip install -e path/to/evennia-portal-multiplex
```

The extension needs nothing in `INSTALLED_APPS` and declares no settings of its own.

## 2. Add the app

On every instance, the Portal's and the Servers':

```python
INSTALLED_APPS = list(INSTALLED_APPS) + ["evennia_portal_multiplex"]
```

This is what installs the library at all. Its `AppConfig.ready()` is the only way it gets into either
process, so without this line nothing happens and nothing says why.

## 3. Name this instance, and the default

```python
MULTIPLEX_INSTANCE_ID = "shard1"          # this instance's name. Distinct per instance
MULTIPLEX_DEFAULT_INSTANCE = "router"     # where an unmoved session belongs. The same on all
```

If your game already names its instances — `evennia-message-bus` does — alias rather than maintain two
names for one thing:

```python
MULTIPLEX_INSTANCE_ID = MESSAGEBUS_INSTANCE_ID
```

Nothing checks the two agree. If they drift, a session is addressed by one name and routed by another,
and the only symptom is traffic arriving at the default while everything above believes it moved.

## 4. Give the Portal instance its port

The Portal instance listens on its own AMP port and is started normally:

```python
AMP_PORT = 4006
TELNET_PORTS = [4000]
```

## 5. Point every other instance at that port

That is what makes a Server dial there instead of expecting a Portal of its own:

```python
AMP_PORT = 4006          # the Portal instance's port, not one of ours
TELNET_PORTS = [4020]    # never listened on, but set distinctly — see below
```

Give them distinct telnet and web ports even though they never listen. Starting one fully by accident
then fails on something obvious, rather than several instances silently fighting over port 4000.

Each instance needs its own directory, because Evennia derives its database and logs from `GAME_DIR`,
which is the working directory it was started from.

## 6. Declare the Server-only launcher verb

`evennia start` brings up a Portal too, which collides on the AMP port. `evennia istart` tells the
Portal to stop the Server it already has — so on a shared Portal it shuts down the instance you were
attached to. Neither is what you want.

This library adds a verb that starts a Server and speaks to no Portal at all. Declare it on every
Server-only instance:

```python
EXTRA_LAUNCHER_COMMANDS = {
    "server_start": "evennia_portal_multiplex.launcher.server_start",
}
```

Without the setting the verb does not resolve, and it fails silently — it falls through to Django and
is reported as an unknown command.

## 7. Start the Portal instance, then the Servers

The Portal instance first. `server_start` needs a live Portal at the address it dials.

```bash
evennia start --settings settings_router
```

Then, from each Server-only instance's directory:

```bash
evennia server_start --settings settings_shard1
```

**`AMP_PORT` is the launcher's control channel as well as the Server's dial target.** So `stop`,
`reload` and `istart` run from a Server-only instance's directory all reach the *Portal instance*.
`server_start` is the only launcher verb safe to use from one.

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

## Required settings

| Setting | What it does | Without it |
|---|---|---|
| `MULTIPLEX_INSTANCE_ID` | This instance's name, as it announces itself to a Portal. Distinct per instance | The instance refuses to start |
| `MULTIPLEX_DEFAULT_INSTANCE` | Where a session goes when nothing has bound it elsewhere. The same on every instance | The instance refuses to start |

Both are checked in `AppConfig.ready()`, so a missing one stops the boot rather than surfacing later —
which for `MULTIPLEX_DEFAULT_INSTANCE` on a Portal would otherwise be the first player's connect. Both
problems are reported in one refusal, so a settings file with two gaps takes one restart to fix, not two.

`EXTRA_LAUNCHER_COMMANDS` is Evennia's, not this library's, and step 6 covers what it costs to leave
out.

## Optional settings

**This library has none.** Both of its settings are required, because neither has a default that could
be right: an instance name invented for you would collide with the next instance's, and a default
instance guessed for you would be whichever Server attached most recently, which is the thing this
library exists to stop.

## Where it logs

Everything this library writes goes to `portalmultiplex.log`, under Evennia's `LOG_DIR` beside its
other logs and in Evennia's own line format. One file per instance, because each instance derives its
log directory from its own `GAME_DIR`.

| Line | When |
|---|---|
| `evennia-portal-multiplex cannot start: …` | ERROR — a required setting is missing, naming every one of them. The instance does not start |
| `Installed on '<name>'` | Every process that runs `django.setup()`, so one `evennia start` writes three. Written only after the settings check passes, so it means started *and* configured |
| `'<name>' attached` | A Server registers with this Portal |
| `'<name>' attached on a new connection, replacing the one held` | A Server re-registered — it restarted, or a second Server carries the same id |
| `server_start: …` | The launcher verb starting a Server |
| `Not starting: …` | A Server refusing to start, with the reason |
| `Could not reach the Portal at …` | The Server's AMP client could not dial; Twisted retries |
| A move that did not simply succeed | Not attached, rejected, stranded, or an id the Portal does not hold |
| `'<name>' has dropped and N session(s) are waiting for it` | An instance vanished and a player on it sent a command |
| `'<name>' is back; its sessions resume` | It reattached inside the ten-second wait |
| `'<name>' did not come back within 10s. Moving N session(s)` | WARN — the wait expired and its players went to the default |
| `Could not move a session to '<name>' … Disconnecting it` | ERROR — the default would not take them either |

**An instance with no `portalmultiplex.log` never loaded the library.** The file appears at install and
a refusal writes to it too, so its absence means the package was never imported — check `INSTALLED_APPS`
on that instance. A file whose last line is a refusal means the opposite: it loaded, and stopped.

## What is not checked for you

- **That the library is in `INSTALLED_APPS`.** Leave it out and `AppConfig.ready()` never runs, so
  nothing installs and nothing validates anything — including the settings check below.
- **That aliased instance names agree** with whatever sibling library you took them from. Nothing
  compares them — see step 3.
- **That `EXTRA_LAUNCHER_COMMANDS` declares the verb** on a Server-only instance. This library never
  reads it — Evennia's launcher does — and a deployment that never starts a second Server on a shared
  Portal legitimately does not need it, so it is not in the boot check. Step 6 covers what it costs to
  leave out.
- **That a Server actually registered** — that one *is* checked. An instance whose announcement did
  not reach the Portal logs the reason and stops, rather than running unreachable. `server_start`
  reports it at the terminal.

## What happens when an instance drops

You do not configure any of this and there is nothing to switch off.

An instance can vanish mid-play — a crash, a reload, a cut link. Evennia's Server redials on its own,
at one second growing to ten, so most of the time it is back before anyone notices. When a player on
that instance sends a command in the meantime:

- The command is **dropped**, not sent elsewhere. Another Server was never told that session exists and
  would discard it silently, leaving the player typing into a socket that never answers.
- Everyone on that instance is told their connection is lost and is being reconnected.
- The Portal watches for the instance for **ten seconds**. If it returns, they are told so and play
  carries on exactly where it was — nothing about the session changed.
- If it does not return, they are moved to your default instance and meet its login flow, arriving
  unauthenticated for the same reason any moved session does.
- If the default will not take them either, the game is down rather than one part of it: they are told
  and disconnected.

**Your character data is your problem, not this library's.** A player moved this way lands on the
default instance as a fresh, unauthenticated session. If your instances have separate databases, that
means the default's character of that name — carrying whatever they were doing on the instance that
died is yours to arrange.
