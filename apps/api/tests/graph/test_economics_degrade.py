"""A run with no archetype has no economics template to solve. It must degrade
to "no model" with a visible trace row, never crash the run."""
from jury.graph.nodes.economics import run_economics
from jury.tracing.events import MemoryTraceSink


async def test_economics_without_an_archetype_skips_the_model_and_says_so():
    trace = MemoryTraceSink()
    state = {"run_id": "run-1", "project_id": "project-1", "archetype": None,
             "target_scope": {"geo": "US", "segment": "smb"}}

    out = await run_economics(state, repos=None, transports=None, trace=trace)

    assert out == {"model_run": None, "model_run_id": None}
    errors = [e for e in trace.rows if e["event"] == "error"]
    assert errors and "no archetype" in errors[0]["detail"]["message"]
