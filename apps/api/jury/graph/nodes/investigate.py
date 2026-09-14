"""The five-way chair fan-out. Task 4.3. PRD §6, §7.3, §18.

Two functions:

- `dispatch_chairs` is a conditional-edge function, not a node -- it runs
  once (after the hearing resumes) and returns one `Send` per chair. LangGraph
  dispatches all five `Send`s concurrently as independent tasks against the
  SAME node ("chair"), each with its own partial state carrying which chair
  it is. This is genuine concurrency, not a `for` loop: PRD §7's F7 acceptance
  criterion ("all five run concurrently") is provable from the trace by
  overlapping `node_start`/`node_end` windows -- see
  `tests/graph/test_graph.py::test_the_five_chairs_run_concurrently_not_sequentially`.

- `run_chair_node` is that "chair" node. A failing chair (PRD §18: "degrade
  to less evidence, never crash") is caught here and folded into
  `partial_chairs` rather than propagating -- the try/except boundary is
  drawn around the single call to `module.investigate(ctx)`, deliberately
  narrow, so a bug in this node's OWN setup code (building `ChairContext`,
  say) is not silently swallowed the same way.
"""
from langgraph.types import Send

from jury.chairs import customer, dependencies, economics, market, precedent
from jury.chairs.base import ChairContext
from jury.graph.idempotency import already_ran
from jury.graph.state import RunState
from jury.retrieval.budgets import BudgetLedger
from jury.retrieval.embed import Embedder
from jury.schemas.assumption import AssumptionRecord
from jury.schemas.enums import Chair
from jury.schemas.scope import Scope
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

CHAIRS: tuple[Chair, ...] = (
    Chair.MARKET, Chair.CUSTOMER, Chair.PRECEDENT, Chair.DEPENDENCIES, Chair.ECONOMICS,
)

_MODULES = {
    Chair.MARKET: market, Chair.CUSTOMER: customer, Chair.PRECEDENT: precedent,
    Chair.DEPENDENCIES: dependencies, Chair.ECONOMICS: economics,
}


def dispatch_chairs(state: RunState) -> list[Send]:
    """Fan out to all five chairs. Each `Send` carries the whole current
    state plus which chair this branch is -- `run_chair_node` reads
    `state["chair"]` to know which module to run."""
    return [Send("chair", {**state, "chair": chair.value}) for chair in CHAIRS]


async def run_chair_node(state: RunState, *, transports: Transports, pool,
                         trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `evidence_ids`, `discovered`,
    `partial_chairs` -- each additive-reducer fields (`jury/graph/state.py`)
    so five concurrent branches' updates accumulate instead of clobbering.
    """
    chair = Chair(state["chair"])
    run_id = state["run_id"]
    node_label = f"chair:{chair.value}"

    if trace is not None:
        await trace.emit(node=node_label, event="node_start")

    if await already_ran(transports.kv, run_id, "chair", salt=chair.value):
        if trace is not None:
            await trace.emit(node=node_label, event="node_end")
        return {}

    assumptions = [AssumptionRecord(**a) for a in state.get("assumptions", [])]
    ctx = ChairContext(
        run_id=run_id, project_id=state["project_id"], pitch=state["pitch"],
        target_scope=Scope(**state["target_scope"]), assumptions=assumptions,
        transports=transports, budgets=BudgetLedger(transports.kv, run_id),
        domain_map={}, trace=trace, pool=pool, embedder=Embedder(transports.kv))

    try:
        result = await _MODULES[chair].investigate(ctx)
    except Exception as err:      # noqa: BLE001 - PRD §18: degrade, never crash the run
        if trace is not None:
            await trace.emit(node=node_label, event="error",
                             detail={"error": f"{type(err).__name__}: {err}"})
            await trace.emit(node=node_label, event="node_end")
        return {"partial_chairs": [chair.value]}

    if trace is not None:
        await trace.emit(node=node_label, event="node_end")

    discovered = [{"chair": chair.value, "statement": d.statement, "class_key": d.class_key}
                 for d in result.discovered]
    partial_chairs = [chair.value] if result.partial else []
    return {"evidence_ids": result.inserted, "discovered": discovered,
            "partial_chairs": partial_chairs}
