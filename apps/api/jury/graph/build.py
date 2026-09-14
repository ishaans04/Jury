"""Graph assembly. Task 4.3. PRD §7 / §10.

Topology this batch builds (Phase 5 extends past `reconcile`):

    archetype -> extract -> coverage -> [interrupt: hearing]
      -> Send fan-out x5 (chair) -> reconcile -> END

A Postgres-backed checkpointer (`AsyncPostgresSaver`) is what makes the
hearing's `interrupt()` durable across a crashed instance: the graph's state
at the moment of pausing is a committed row, not process memory, so a fresh
`build_graph` call from a brand-new process against the same `thread_id`
(here, the run's own id) can resume exactly where the last instance left off
(PRD §10.1).

**Deviation from the brief's literal interface, stated plainly (the task
brief said to flag this rather than silently adjust):** the brief lists
`build_graph(transports, pool, classes) -> CompiledStateGraph` as a plain
(non-async) function. `AsyncPostgresSaver` has no synchronous constructor --
opening its connection is an `await`, and there is no way to produce a real,
usable instance of it from inside a `def`, only from an `async def`. Rather
than fake this with a sync wrapper around `asyncio.run` (which would break
the moment this is called from inside an already-running event loop, exactly
the context every caller here — the graph tests, and Task 4.4's FastAPI
routes — actually calls it from), `build_graph` is `async def` here. Every
call site in this batch (`run_initial`, `resume_hearing`, and the tests) awaits
it accordingly.

**Second deviation:** `run_initial`/`resume_hearing`'s brief signatures list
only the run's own data (`project_id, run_id, pitch, target_scope` /
`run_id, edited_assumptions`), with no way to inject the transports, pool or
per-archetype checklist a real call needs. Both are extended with keyword-
only `transports`, `pool`, `classes` parameters -- required, no implicit
global default -- since `classes` in particular has no principled
process-wide default (Task 4.1's own extraction/coverage nodes already treat
it as data threaded in by the caller, never looked up or invented
internally: see `jury/graph/nodes/extract.py`/`coverage.py`). A future batch
wiring this to real API routes supplies the archetype-specific checklist it
already has in hand at that call site.
"""
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from jury.graph.nodes.archetype import detect_archetype
from jury.graph.nodes.coverage import coverage_gaps
from jury.graph.nodes.extract import extract_assumptions
from jury.graph.nodes.hearing import run_hearing
from jury.graph.nodes.investigate import dispatch_chairs, run_chair_node
from jury.graph.nodes.reconcile import run_reconcile
from jury.graph.state import RunState
from jury.settings import Settings, settings as _default_settings
from jury.tracing.events import PostgresTraceSink
from jury.tracing.events import traced
from jury.transport.protocols import Transports


async def _open_checkpointer(database_url: str) -> AsyncPostgresSaver:
    conn = await AsyncConnection.connect(
        database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
    checkpointer = AsyncPostgresSaver(conn=conn)
    await checkpointer.setup()
    return checkpointer


async def build_graph(transports: Transports, pool, classes: list[tuple[str, float, str]],
                      *, settings: Settings | None = None) -> CompiledStateGraph:
    settings = settings or _default_settings
    checkpointer = await _open_checkpointer(settings.database_url)

    def _trace(state: RunState) -> PostgresTraceSink:
        return PostgresTraceSink(pool, state["run_id"])

    async def archetype_node(state: RunState) -> dict:
        fn = traced("archetype")(detect_archetype)
        return await fn(state, transports=transports, trace=_trace(state))

    async def extract_node(state: RunState) -> dict:
        fn = traced("extract")(extract_assumptions)
        return await fn(state, transports=transports, classes=classes, trace=_trace(state))

    async def coverage_node(state: RunState) -> dict:
        async def _fn(state: RunState, *, trace) -> dict:
            del trace  # coverage_gaps is a pure function; nothing to trace internally
            return {"coverage_gaps": coverage_gaps(classes, state.get("assumptions", []))}
        fn = traced("coverage")(_fn)
        return await fn(state, trace=_trace(state))

    async def hearing_node(state: RunState) -> dict:
        return await run_hearing(state, pool=pool, transports=transports, trace=_trace(state))

    async def chair_node(state: RunState) -> dict:
        return await run_chair_node(state, transports=transports, pool=pool, trace=_trace(state))

    async def reconcile_node(state: RunState) -> dict:
        return await run_reconcile(state, pool=pool, transports=transports, classes=classes,
                                   trace=_trace(state))

    builder = StateGraph(RunState)
    builder.add_node("archetype", archetype_node)
    builder.add_node("extract", extract_node)
    builder.add_node("coverage", coverage_node)
    builder.add_node("hearing", hearing_node)
    builder.add_node("chair", chair_node)
    builder.add_node("reconcile", reconcile_node)

    builder.add_edge(START, "archetype")
    builder.add_edge("archetype", "extract")
    builder.add_edge("extract", "coverage")
    builder.add_edge("coverage", "hearing")
    builder.add_conditional_edges("hearing", dispatch_chairs, ["chair"])
    builder.add_edge("chair", "reconcile")
    builder.add_edge("reconcile", END)

    return builder.compile(checkpointer=checkpointer)


async def run_initial(project_id: str, run_id: str, pitch: str, target_scope: dict, *,
                      transports: Transports, pool, classes: list[tuple[str, float, str]],
                      settings: Settings | None = None) -> RunState:
    """Starts a new run. Pauses at the hearing interrupt -- see the module
    docstring's "zero evidence before confirmation" guarantee, which holds
    because nothing after `interrupt()` in `jury.graph.nodes.hearing.run_hearing`
    can execute until this same thread is resumed."""
    graph = await build_graph(transports, pool, classes, settings=settings)
    config = {"configurable": {"thread_id": run_id}}
    return await graph.ainvoke(
        {"run_id": run_id, "project_id": project_id, "pitch": pitch,
         "target_scope": target_scope},
        config)


async def resume_hearing(run_id: str, edited_assumptions: list[dict], *,
                         transports: Transports, pool, classes: list[tuple[str, float, str]],
                         settings: Settings | None = None) -> RunState:
    """Resumes a run paused at the hearing with the founder's confirmed
    assumption list -- edits, deletions and additions all included. A fresh
    `build_graph` call each time (rather than caching a compiled graph across
    calls) is deliberate: it is what lets
    `tests/graph/test_graph.py::test_the_run_resumes_from_the_last_completed_node_after_a_crash`
    prove resumability from a brand-new process, not just from a graph object
    that happened to still be sitting in memory."""
    graph = await build_graph(transports, pool, classes, settings=settings)
    config = {"configurable": {"thread_id": run_id}}
    return await graph.ainvoke(Command(resume=edited_assumptions), config)
