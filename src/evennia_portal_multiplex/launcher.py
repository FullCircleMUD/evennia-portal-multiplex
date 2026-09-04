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
    print("Server started. It attaches to the Portal named by AMP_HOST/AMP_PORT.")
