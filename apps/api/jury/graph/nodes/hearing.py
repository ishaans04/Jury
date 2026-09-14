"""The assumption hearing. Task 4.3. F5, PRD §7.3.

"Nothing proceeds without confirmation" is enforced by control flow, not
convention: `interrupt()` is the very first thing this node can possibly do
that has any externally visible effect (the `trace.emit` line just before it
is itself gated behind nothing -- see below for why that is still safe), and
raises `GraphInterrupt` on its first call for a given run. Nothing after
that line in this function -- in particular, the `AssumptionRepo.create_many`
call -- can execute until a caller resumes the thread with
`Command(resume=edited_assumptions)`. There is therefore no code path in
this module that can write a row before the founder has confirmed.

**Node-level replay** (langgraph's own documented behaviour): "The graph
resumes from the start of the node, re-executing all logic." So on resume,
this entire function body runs again from its first line, including the
`trace.emit(event="interrupt")` call and the `interrupt()` call itself --
`interrupt()` recognises it already has a resume value queued for this call
and returns it immediately rather than pausing again. The trace call before
it is harmless to repeat (an extra `run_events` row, not a correctness
issue); the persistence call after it is NOT harmless to repeat, which is
exactly why it is the one line in this function gated by the idempotency
guard (`jury/graph/idempotency.py`) rather than by `interrupt()`'s own
replay-proofing (`interrupt()` only protects itself, not arbitrary code
after it).

This node is NOT wrapped in the generic `jury.tracing.events.traced`
decorator used elsewhere: `traced`'s blanket `except Exception` would catch
the `GraphInterrupt` `interrupt()` raises internally to pause the graph
(`GraphInterrupt` subclasses `Exception`) and misrecord an ordinary pause as
a run_events `error` row before re-raising it. This module emits its own
node_start/node_end pair and re-raises `GraphInterrupt` uninspected.
"""
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from jury.db.repositories import AssumptionRepo
from jury.graph.idempotency import already_ran
from jury.graph.state import RunState
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports


def _row_to_dict(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "statement": row["statement"],
        "class_key": row["class_key"],
        "origin": row["origin"],
        "discovered_by": row["discovered_by"],
        "criticality": row["criticality"],
        "uncertainty": row["uncertainty"],
        "falsifiability": row["falsifiability"],
        "asserted_variable": row["asserted_variable"],
        "asserted_value": (float(row["asserted_value"])
                          if row["asserted_value"] is not None else None),
        "asserted_unit": row["asserted_unit"],
        "status": row["status"],
        "strength": float(row["strength"]) if row["strength"] is not None else 0.0,
    }


async def run_hearing(state: RunState, *, pool, transports: Transports,
                      trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `assumptions`, refreshed from the
    database to reflect exactly what the founder confirmed -- edits,
    deletions and additions all included -- which is what every downstream
    node (fan-out, reconcile) must investigate against.
    """
    run_id, project_id = state["run_id"], state["project_id"]

    if trace is not None:
        await trace.emit(node="hearing", event="node_start")
        await trace.emit(
            node="hearing", event="interrupt",
            detail={"assumptions": state.get("assumptions", []),
                    "coverage_gaps": state.get("coverage_gaps", [])})

    try:
        edited = interrupt({"assumptions": state.get("assumptions", []),
                            "coverage_gaps": state.get("coverage_gaps", [])})

        repo = AssumptionRepo(pool)
        if not await already_ran(transports.kv, run_id, "hearing_persist"):
            await repo.create_many(project_id, run_id, edited)

        rows = await repo.list_for_project(project_id)
        assumptions = [_row_to_dict(r) for r in rows if str(r["run_id"]) == str(run_id)]
    except GraphInterrupt:
        raise
    except Exception as err:
        if trace is not None:
            await trace.emit(node="hearing", event="error",
                             detail={"error": f"{type(err).__name__}: {err}"})
        raise

    if trace is not None:
        await trace.emit(node="hearing", event="node_end")
    return {"assumptions": assumptions}
