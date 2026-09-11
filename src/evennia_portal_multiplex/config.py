# SPDX-License-Identifier: BSD-3-Clause
"""The two settings this library reads, and every constant it declares.

The settings are an instance's name, and where traffic goes when nothing has
said otherwise. Both are named here rather than borrowed from a sibling, so a
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

#: How long to let a Server settle before deciding it did not come up. It has
#: to cover a full boot *and* a refusal, because the refusal happens once the
#: Server is up enough to have dialled its Portal — see docs/test-plan.md § ST.
#: A guess until this has been run against live instances; too short reports a
#: healthy Server as failed, which is worse than saying nothing.
SETTLE_SECONDS = 10


def _required(name, why):
    """Read a setting that has no safe default."""
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    value = getattr(settings, name, None)
    if not value:
        raise ImproperlyConfigured(f"{name} is not set. {why}")
    return value


def get_instance_id():
    """This instance's name, as it announces itself to a Portal.

    Every Server attached to one Portal must have a distinct one, or the second
    to attach replaces the first in the registry and takes its sessions.
    """
    return _required(
        SETTING_INSTANCE_ID,
        "Each Server announces this to the Portal it attaches to, and the "
        "Portal tells its connections apart by it. Instances sharing a Portal "
        "need distinct names.",
    )


def get_default_instance():
    """Where a session goes when nothing has bound it elsewhere.

    A decision rather than a leftover. Without it the destination would be
    whichever Server attached most recently, so a player arriving while a
    second instance starts would be handed to that one.
    """
    return _required(
        SETTING_DEFAULT_INSTANCE,
        "A session that has not been moved has to belong somewhere, and "
        "leaving it to whichever Server attached last is not a decision.",
    )
