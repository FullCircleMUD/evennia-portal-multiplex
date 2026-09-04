# SPDX-License-Identifier: BSD-3-Clause
"""The two settings this library reads.

An instance's name, and where traffic goes when nothing has said otherwise.
Both are declared here rather than borrowed, so the library depends on Evennia
and nothing else — a consumer that already names its instances aliases them::

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
