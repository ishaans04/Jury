"""Node-level idempotency. Task 4.3. PRD §17.3.

LangGraph's own replay semantics guarantee at-least-once execution of a node
across a crash or an explicit re-invoke of an already-completed thread (see
`jury/graph/build.py`'s docstring for why `resume_hearing` can be called
twice against the same run). Guaranteed-at-least-once is not the same as
exactly-once: a node whose body inserts DB rows would duplicate them on a
replay unless something outside the DB's own constraints stops the second
attempt before any write happens. This module is that guard.

The key is written to Redis/KV *before* any side effect the guarded node
performs -- not after -- because the point of the guard is "did we already
attempt this," not "did we already succeed." A node that crashes mid-write
after setting the key is a rarer and more acceptable failure mode than a
node that writes twice because the key was only set on success.
"""
from jury.transport.protocols import KV

_TTL_S = 3600


def idempotency_key(run_id: str, node: str, salt: str = "") -> str:
    """Pure string builder -- no I/O. `salt` disambiguates multiple
    instances of the same node name in one run (e.g. one chair fan-out
    branch per chair)."""
    return f"idem:{run_id}:{node}:{salt}"


async def already_ran(kv: KV, run_id: str, node: str, salt: str = "") -> bool:
    """Returns True if this (run, node, salt) has already been attempted --
    the caller must short-circuit and perform no side effect. Returns False
    (and marks the key) the first time, which is the caller's signal to
    proceed.

    The `kv.get` check runs before the `kv.set` write (the "guarded by a
    kv.get check" the brief asks for): a caller that proceeds past `False`
    is racing nothing else for this exact key inside a single run, since
    each node/chair salt is only ever dispatched once per run by the graph
    topology itself -- this guard exists for the *replay* case, not for
    concurrent duplicate dispatch within one execution.
    """
    key = idempotency_key(run_id, node, salt)
    if await kv.get(key) is not None:
        return True
    await kv.set(key, "1", _TTL_S)
    return False
