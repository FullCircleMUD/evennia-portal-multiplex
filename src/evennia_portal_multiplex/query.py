# SPDX-License-Identifier: BSD-3-Clause
"""Asking the Portal which instances are attached.

A Server can see its own side of the AMP link and nothing else. Whether its
announcement was recorded, and what else is attached, are facts only the Portal
holds — so a Server that failed to register looks exactly like one that
succeeded, until something tries to reach it.

This is the round trip that closes that, and it is the first thing this library
adds to the AMP protocol rather than intercepts on it.

**One command, one question, one answer.** AMP is already a command-dispatch
protocol: a key, typed arguments, a declared response, and a table that routes
by command. A generic query command carrying a question field would rebuild
that a layer up and worse — one response shape forced to serve every question,
so a pickled blob rather than declared types, and an unknown-question case of
our own to get wrong. Another question later is another command of this shape,
which is a dozen lines in the obvious place.

See docs/test-plan.md § QY.
"""

from evennia.server.portal import amp as evennia_amp
from twisted.protocols import amp

from .config import get_instance_id


class MultiplexQueryRegistry(amp.Command):
    """A Server asking its Portal which instances are attached.

    No arguments: the command is the question. An unrecognised command is
    Twisted's ``UnhandledCommand`` rather than anything we have to detect.
    """

    key = "MultiplexQueryRegistry"
    arguments = []
    errors = {Exception: b"EXCEPTION"}
    response = [(b"attached", amp.String())]


def query_registry(connection):
    """Ask, and decode the reply. Returns a Deferred.

    The Portal is under a millisecond away over localhost and about that
    across a VPC, so this is cheap enough to run at startup.
    """
    return connection.callRemote(MultiplexQueryRegistry).addCallback(
        lambda reply: evennia_amp.loads(reply["attached"])
    )


def am_i_registered(attached):
    """Whether this instance is in the answer `query_registry` came back with.

    A read of an answer already in hand, not a second round trip. This is the
    question worth asking at startup: no instance knows what order the others
    boot in, so "is everyone here" is unanswerable and would only produce a
    retry loop, while "did my own announcement land" is self-contained and
    something the instance can act on.
    """
    return get_instance_id() in attached
