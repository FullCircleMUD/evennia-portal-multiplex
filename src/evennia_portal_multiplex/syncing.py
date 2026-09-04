# SPDX-License-Identifier: BSD-3-Clause
"""Which instance a `PSYNC` reply is being built for.

When a Server attaches it sends ``PSYNC``, and the Portal answers with every
session it holds. With one Server that is the right answer; with three, each
attaching Server is handed the other instances' sessions as well.

Filtering that reply needs the name of the instance that asked.
`amp.py`'s responder has it — it arrives in the same message — and
`get_all_sync_data` builds the payload and takes no arguments. This carries
the name from one to the other, for the length of one call.

The same shape as `routing.sending_to`, and safe for the same reason: the
Portal is a single-threaded reactor, so nothing runs between setting the name
and clearing it. That is a property of the environment rather than of this
code — on a threaded portal the approach would be wrong.

See docs/test-plan.md § SY.
"""

from contextlib import contextmanager

#: The instance a reply is being built for, or None. Module state rather than
#: something passed down: the two ends of this are Evennia's — a responder we
#: subclass and a handler method we override — with Evennia's own code in
#: between, so there is no argument to thread through.
_SYNCING_FOR = None


@contextmanager
def syncing_for(instance_id):
    """Note that a `PSYNC` reply is being built for ``instance_id``.

    Restored on the way out rather than cleared, and restored whether or not
    the block raised. Left set, every later call to `get_all_sync_data` would
    answer for one instance — including the callers that should see every
    session.
    """
    global _SYNCING_FOR

    held = _SYNCING_FOR
    _SYNCING_FOR = instance_id
    try:
        yield
    finally:
        _SYNCING_FOR = held


def currently_syncing():
    """The instance a reply is being built for, or ``None``.

    ``None`` is the ordinary state and has to stay distinguishable from an
    instance that simply holds no sessions — one means "answer with
    everything", the other means "answer with nothing".
    """
    return _SYNCING_FOR
