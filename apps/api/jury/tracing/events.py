"""In-app tracing. PRD §11.2 decision 9 -- replaces Langfuse/LangSmith.

One row per node entry/exit, tool call, latency, token count and error. Costs
one table, removes a service, and doubles as a demo asset: showing judges the
trace inside the product proves the pipeline is real.
"""
import functools
import time
from typing import Any, Protocol, runtime_checkable

# Must match the `run_events.event` CHECK constraint in the database exactly
# (verified against the running local schema). An unknown kind is rejected
# here, in Python, before it ever reaches an insert statement.
EVENT_KINDS = ("node_start", "node_end", "llm_call", "tool_call",
               "fetch", "error", "interrupt")


@runtime_checkable
class TraceSink(Protocol):
    async def emit(self, *, node: str, event: str, detail: dict | None = None,
                   latency_ms: int | None = None) -> None: ...


class MemoryTraceSink:
    """Collects rows in process. Used by tests and by offline runs."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, *, node: str, event: str, detail: dict | None = None,
                   latency_ms: int | None = None) -> None:
        if event not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {event!r}; "
                             f"the db CHECK constraint would reject it")
        self.rows.append({"node": node, "event": event,
                          "detail": detail or {}, "latency_ms": latency_ms})


class PostgresTraceSink:
    """Writes to run_events. Insert-only and never in the request's critical path."""

    def __init__(self, pool, run_id: str) -> None:
        self._pool = pool
        self._run_id = run_id

    async def emit(self, *, node: str, event: str, detail: dict | None = None,
                   latency_ms: int | None = None) -> None:
        import json
        if event not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {event!r}; "
                             f"the db CHECK constraint would reject it")
        async with self._pool.connection() as conn:
            await conn.execute(
                "insert into run_events (run_id, node, event, detail, latency_ms) "
                "values (%s, %s, %s, %s, %s)",
                (self._run_id, node, event, json.dumps(detail or {}), latency_ms))


def traced(node: str):
    """Wrap a graph node so entry, exit, latency and failure are all recorded.

    The wrapped function must accept a keyword-only `trace` argument -- it is
    passed through (not consumed) so the node can emit its own `llm_call` and
    `fetch` rows in addition to the node_start/node_end/error rows this
    decorator emits itself.
    """
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, trace=None, **kwargs):
            if trace is None:
                return await fn(*args, **kwargs)
            await trace.emit(node=node, event="node_start")
            started = time.perf_counter()
            try:
                result = await fn(*args, trace=trace, **kwargs)
            except Exception as err:
                await trace.emit(
                    node=node, event="error",
                    detail={"error": f"{type(err).__name__}: {err}"},
                    latency_ms=int((time.perf_counter() - started) * 1000))
                raise
            await trace.emit(
                node=node, event="node_end",
                latency_ms=int((time.perf_counter() - started) * 1000))
            return result
        return wrapper
    return decorate
