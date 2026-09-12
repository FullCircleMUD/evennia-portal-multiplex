# SPDX-License-Identifier: BSD-3-Clause
"""The two settings this library reads, the boot check, and every constant.

The settings are an instance's name, and where traffic goes when nothing has
said otherwise. Both are required — `check_settings` refuses the boot without
them, so everything below reads them plainly. Both are named here rather than
borrowed from a sibling, so a
consumer that already names its instances aliases them rather than this library
reaching for someone else's vocabulary::

    MULTIPLEX_INSTANCE_ID = MESSAGEBUS_INSTANCE_ID
    MULTIPLEX_DEFAULT_INSTANCE = SCALING_ROUTER_ID

That keeps one name per instance across whatever else a deployment runs, while
leaving this library with no opinion about where the name came from. A consumer
doing that should check the two agree at startup: if they drift, a session is
addressed by one name and routed by another, and the only symptom is traffic
arriving at the default while everything above believes it moved.

See docs/test-plan.md § CF.
"""

SETTING_INSTANCE_ID = "MULTIPLEX_INSTANCE_ID"
SETTING_DEFAULT_INSTANCE = "MULTIPLEX_DEFAULT_INSTANCE"

#: What a move resolves to. The names describe what happened to the session,
#: not what this library did about it — a destination that would not take the
#: session **rejected** it, and that we then put the session back is
#: bookkeeping the consumer has no use for. `move.py` imports them and they
#: are read from there: `from evennia_portal_multiplex.move import MOVED`.
MOVED = "moved"
ALREADY_THERE = "already_there"
NOT_ATTACHED = "not_attached"
REJECTED = "rejected"
STRANDED = "stranded"
NO_SUCH_SESSION = "no_such_session"

#: Where a payload lands on the session. `server_data` is on
#: ``SESSION_SYNC_ATTRS``, so what is put there crosses with the ``PCONN``.
#: Prefixed because the dict is Evennia's and a consumer keeps their own keys
#: in it too.
PAYLOAD_KEY = "multiplex_payload"

#: The fields cleared on the way out and restored on the way back. All three
#: are on ``SESSION_SYNC_ATTRS`` and all three are primary keys belonging to
#: the Server being left: carried across, the destination believes the session
#: is already authenticated as whatever account holds that id over there.
IDENTITY = {"uid": None, "logged_in": False, "puid": None}

#: The attribute a session's instance name is stamped on. Prefixed because a
#: Portal session is an Evennia object and a consumer may stamp their own.
BINDING_KEY = "_multiplex_instance"

#: The key an instance's name travels under inside Evennia's ``info_dict``.
#: Prefixed because the dict is Evennia's and a consumer may add to it too.
INSTANCE_KEY = "multiplex_instance_id"

#: How long to wait for a dropped instance before giving up on it and moving
#: its sessions to the default. Evennia's AMP client redials at one second
#: growing to a ceiling of ten, so anything transient — a reload, a crash under
#: a process manager, a network blip — is back inside this. See § RC.
RECONNECT_WAIT_SECONDS = 10

#: How often to look at the registry entry while waiting. The Portal cannot see
#: the Server's redial attempts, so it watches the entry those attempts change.
RECONNECT_POLL_SECONDS = 1

#: What a player is told, in order: their connection went, we are waiting, and
#: then one of the two outcomes. Nothing about registries or redialling — none
#: of that is theirs to know.
RECONNECT_LOST_MESSAGE = (
    "Your connection to the game server has been lost. Reconnecting..."
)
RECONNECT_RESTORED_MESSAGE = "Reconnected."
RECONNECT_TIMED_OUT_MESSAGE = (
    "Could not reconnect you. Moving you to the default server."
)

#: When the default will not take them either. Their own instance is gone and
#: the default cannot build them a session, so the game is down rather than one
#: shard of it — there is no further fallback worth having at that depth.
RECONNECT_NOWHERE_MESSAGE = (
    "The game is unreachable. Disconnecting you — please reconnect shortly."
)

#: How long to let a Server settle before deciding it did not come up. It has
#: to cover a full boot *and* a refusal, because the refusal happens once the
#: Server is up enough to have dialled its Portal — see docs/test-plan.md § ST.
#: A guess until this has been run against live instances; too short reports a
#: healthy Server as failed, which is worse than saying nothing.
SETTLE_SECONDS = 10


#: Why each setting has no default, in the words a consumer reading the refusal
#: needs. Kept beside the names rather than inside the check, so the reason a
#: setting is required sits with the setting itself.
REQUIRED = {
    SETTING_INSTANCE_ID: (
        "Each Server announces this to the Portal it attaches to, and the "
        "Portal tells its connections apart by it. Instances sharing a Portal "
        "need distinct names."
    ),
    SETTING_DEFAULT_INSTANCE: (
        "A session that has not been moved has to belong somewhere, and "
        "leaving it to whichever Server attached last is not a decision."
    ),
}


def check_settings():
    """Refuse to start when a required setting is missing.

    Called from ``AppConfig.ready()``, before anything else runs — the Portal
    reads `get_default_instance` when a player connects, so left to the read
    the refusal would land on a live deployment one player at a time.

    See docs/test-plan.md § CF.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    problems = []

    # getattr with a default rather than settings.NAME, so an undeclared
    # setting reaches the message that says what to add instead of raising
    # AttributeError from inside the check. `not value` covers unset and empty
    # together: an instance named '' is one nothing can address.
    for name, why in REQUIRED.items():
        if not getattr(settings, name, None):
            problems.append(f"{name} is not set. {why}")

    if not problems:
        return

    # Imported inside the branch, never at this module's scope: a log import at
    # module scope runs when the library is first imported, which can be while
    # the consumer's settings module is still executing.
    from .log import portal_multiplex_log

    # Logged before the raise, same text both ways. The exception surfaces
    # wherever the raise lands — for a daemonised Server, not beside the other
    # lines this library wrote — so the file carries it too, rather than an
    # operator reconciling two accounts of one refusal.
    message = "evennia-portal-multiplex cannot start: " + " ".join(problems)
    portal_multiplex_log(message, level="ERROR")
    raise ImproperlyConfigured(message)


def get_instance_id():
    """This instance's name, as it announces itself to a Portal.

    Every Server attached to one Portal must have a distinct one, or the second
    to attach replaces the first in the registry and takes its sessions.

    A plain read: `check_settings` refused the boot if it was missing, so there
    is no unset case left for this to handle.
    """
    from django.conf import settings

    return settings.MULTIPLEX_INSTANCE_ID


def get_default_instance():
    """Where a session goes when nothing has bound it elsewhere.

    A decision rather than a leftover. Without it the destination would be
    whichever Server attached most recently, so a player arriving while a
    second instance starts would be handed to that one.

    A plain read, for the same reason as `get_instance_id`.
    """
    from django.conf import settings

    return settings.MULTIPLEX_DEFAULT_INSTANCE
