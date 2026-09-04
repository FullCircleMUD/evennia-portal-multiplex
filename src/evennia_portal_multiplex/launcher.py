# SPDX-License-Identifier: BSD-3-Clause
"""Launcher verbs this library adds to ``evennia``.

A Server attached to another instance's Portal has no stock launcher verb that
starts it. ``start`` brings up a Portal too, which collides on the AMP port.
``istart`` tells the Portal to stop its current Server before starting its own —
so on a shared Portal, starting a second Server shuts down the first.

Registered through Evennia's own extension point, in the consumer's settings::

    EXTRA_LAUNCHER_COMMANDS = {"server_start": "evennia_portal_multiplex.launcher.server_start"}

then::

    evennia server_start --settings settings_second

**The setting is ``EXTRA_LAUNCHER_COMMANDS``.** `run_custom_commands` reads
that name; its own docstring says ``CUSTOM_EVENNIA_LAUNCHER_COMMANDS``, which is
wrong and fails silently — the verb falls through to Django and is reported as
an unknown command.

See docs/test-plan.md § LC.
"""


#: How long to let a Server settle before deciding it did not come up. It has
#: to cover a full boot *and* a refusal, because the refusal happens once the
#: Server is up enough to have dialled its Portal — see docs/test-plan.md § ST.
#: A guess until this has been run against live instances; too short reports a
#: healthy Server as failed, which is worse than saying nothing.
SETTLE_SECONDS = 10


def _server_came_up():
    """Whether this gamedir's Server is running, once it has had time to settle.

    **The pidfile, not the spawned process's exit code.** twistd forks and the
    process we started exits 0 almost immediately, whatever became of the
    Server. Its status says nothing about what we want to know.

    The pid is checked as well as read: twistd removes its pidfile on a clean
    shutdown, so a Server that refused leaves none — but one that was killed
    leaves a stale file, and reporting that as running is the false success
    this whole check exists to avoid.
    """
    import os
    import time

    from evennia.server import evennia_launcher

    time.sleep(SETTLE_SECONDS)

    pid = evennia_launcher.get_pid(evennia_launcher.SERVER_PIDFILE)
    if not pid:
        return False
    try:
        # Signal 0 asks the question without sending anything.
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError):
        return False
    return True


def server_start(*args):
    """Start this gamedir's Server, without touching any Portal.

    Reached after the launcher has resolved the gamedir and settings, so
    Evennia's own command construction is already populated and can be reused
    rather than reinvented — the twistd path, the pidfile and the log observer
    all come from it.

    Nothing is sent to a Portal. The Server dials out on its own once it is up,
    to whatever ``AMP_HOST``/``AMP_PORT`` name, and that Portal keeps whatever
    Servers it already had.
    """
    import subprocess

    from evennia.server import evennia_launcher

    from .log import portal_multiplex_log

    # Imported here rather than at module scope: this module is named in a
    # consumer's settings and resolved by the launcher, so importing the
    # launcher on the way past would pull it into every process that touches
    # the library, including the Server and the Portal.
    #
    # A private helper, used deliberately. Keeping our own copy of the twistd
    # invocation would go stale silently the first time Evennia changed theirs;
    # borrowing this one breaks loudly instead.
    _portal_cmd, server_cmd = evennia_launcher._get_twistd_cmdline(False, False)

    portal_multiplex_log(f"server_start: {' '.join(server_cmd)}")
    print(f"Starting Server only (no Portal): {' '.join(server_cmd)}")
    subprocess.Popen(server_cmd, env=evennia_launcher.getenv())

    # Checked rather than assumed. A Server that refuses to start does it after
    # twistd has daemonised, so it has no terminal to say so on and this
    # process has nothing to report unless it looks.
    if not _server_came_up():
        failed = (
            "The Server did not start. Read server/logs/server.log for why — "
            "an instance that is not registered with its Portal refuses to "
            "start, and says so there."
        )
        portal_multiplex_log(failed, level="ERROR")
        print(failed)
        return

    print("Server started. It attaches to the Portal named by AMP_HOST/AMP_PORT.")
