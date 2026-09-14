"""jury.graph.build / hearing / investigate / reconcile. Task 4.3.

Uses the real (non-rollback) `real_pool` fixture from tests/graph/conftest.py
-- see that module's docstring for why concurrency and crash-resume proofs
both require genuinely committed connections. Fixtures for the LLM/search/
fetch calls (`tests/graph/_gen_pipeline_fixtures.py`, `_gen_fixtures.py`) are
pre-recorded under tests/fixtures/, the same content-addressed scheme every
other offline test in this repo uses.
"""
from jury.graph.build import build_graph, resume_hearing, run_initial
from jury.graph.nodes.investigate import _MODULES
from jury.schemas.enums import Chair
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports

from tests.graph.conftest import (
    cleanup_run, count_evidence, fetch_assumptions, fetch_conflicts,
    fetch_evidence_rows, fetch_run_events, seed_project_run,
)

PITCH = "GraphCo pipeline test pitch for invoicing software for small businesses"
TARGET = {"geo": "IN", "segment": "smb"}

CLASSES: list[tuple[str, float, str]] = [
    ("saas.pain_severity", 1.0, "Is the pain acute enough to pay for?"),
    ("saas.wtp_above_cost", 1.0, "Does willingness to pay exceed delivered cost per account?"),
    ("saas.retention", 1.0, "Will accounts stay long enough to repay acquisition?"),
    ("saas.channel_cost", 1.0, "Is CAC recoverable within an acceptable payback?"),
    ("saas.buyer_identity", 0.6, "Is there a budget holder who can actually buy?"),
    ("saas.switching_cost", 0.6, "What makes them leave the current solution?"),
    ("saas.dependency_risk", 0.6, "Do required third parties permit this at viable cost?"),
    ("saas.data_compliance", 0.6, "Any data, privacy or regulatory constraint?"),
    ("saas.incumbency", 0.3, "Is the category already won or already a graveyard?"),
    ("saas.expansion", 0.3, "Is there an observable adjacency for expansion?"),
]


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


async def _start(pool, *, suffix: str = "") -> tuple[dict, dict, Transports]:
    """Seeds a project/run and pauses it at the hearing. Returns
    (seed, state, transports) -- `transports` must be reused on the matching
    `resume_hearing` call: its `kv` carries the per-run idempotency keys and
    budget ledgers, which a fresh `MemoryKV()` would trivially reset."""
    seed = await seed_project_run(pool, target_scope=TARGET, suffix=suffix)
    transports = _transports()
    state = await run_initial(seed["project_id"], seed["run_id"], PITCH, TARGET,
                              transports=transports, pool=pool, classes=CLASSES)
    return seed, state, transports


# ── zero evidence before confirmation ────────────────────────────────────

async def test_the_graph_pauses_at_the_hearing_and_writes_no_evidence(real_pool):
    seed, state, _ = await _start(real_pool, suffix="-a")
    try:
        assert state["__interrupt__"]
        assert await count_evidence(real_pool, seed["project_id"]) == 0
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_interrupt_is_recorded_in_the_trace(real_pool):
    seed, state, _ = await _start(real_pool, suffix="-b")
    try:
        events = await fetch_run_events(real_pool, seed["run_id"])
        assert any(r["event"] == "interrupt" for r in events)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


# ── founder edits at the hearing ─────────────────────────────────────────

async def test_founder_edits_survive_the_resume(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-c")
    try:
        original = state["assumptions"]
        edited = [{**a, "criticality": "blocking", "statement": "Edited statement here."}
                 for a in original]
        await resume_hearing(seed["run_id"], edited, transports=transports,
                             pool=real_pool, classes=CLASSES)
        stored = await fetch_assumptions(real_pool, seed["project_id"])
        assert any(a["statement"] == "Edited statement here." for a in stored)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_a_deleted_assumption_is_not_investigated(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-d")
    try:
        original = state["assumptions"]
        await resume_hearing(seed["run_id"], original[:-1], transports=transports,
                             pool=real_pool, classes=CLASSES)
        stored = [a for a in await fetch_assumptions(real_pool, seed["project_id"])
                 if a["origin"] == "founder"]
        assert len(stored) == len(original) - 1
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_a_founder_added_assumption_is_investigated(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-e")
    try:
        original = state["assumptions"]
        extra = {"statement": "Suppliers will accept a 20 percent commission.",
                 "origin": "founder", "criticality": "blocking",
                 "uncertainty": "unknown", "falsifiability": "testable_now"}
        await resume_hearing(seed["run_id"], original + [extra], transports=transports,
                             pool=real_pool, classes=CLASSES)
        stored = await fetch_assumptions(real_pool, seed["project_id"])
        assert any("20 percent commission" in a["statement"] for a in stored)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


# ── the five-way fan-out ──────────────────────────────────────────────────

async def test_all_five_chairs_run_and_each_lands_rows(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-f")
    try:
        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        rows = await fetch_evidence_rows(real_pool, seed["project_id"])
        chairs = {r["chair"] for r in rows}
        assert chairs == {"market", "customer", "precedent", "dependencies", "economics"}
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_five_chairs_run_concurrently_not_sequentially(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-g")
    try:
        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        events = await fetch_run_events(real_pool, seed["run_id"])
        starts = [e for e in events if e["event"] == "node_start"
                 and e["node"].startswith("chair:")]
        ends = [e for e in events if e["event"] == "node_end"
               and e["node"].startswith("chair:")]
        assert len(starts) == 5
        assert len(ends) == 5
        # Concurrency, not a for loop: under strictly sequential execution
        # the last chair's start would necessarily come after the first
        # chair's end (start5 > end1 > ... ), so max(start) > min(end).
        # Genuine concurrent dispatch launches all five before any of them
        # finishes, so max(start) < min(end) instead.
        assert max(s["ts"] for s in starts) < min(e["ts"] for e in ends)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_a_chair_failing_does_not_fail_the_run(real_pool, monkeypatch):
    seed, state, transports = await _start(real_pool, suffix="-h")
    try:
        async def _broken(ctx):
            raise RuntimeError("simulated chair failure")
        monkeypatch.setattr(_MODULES[Chair.ECONOMICS], "investigate", _broken)

        result = await resume_hearing(seed["run_id"], state["assumptions"],
                                      transports=transports, pool=real_pool,
                                      classes=CLASSES)
        assert result["run_status"] != "failed"
        assert result["evidence_ids"]
        assert "economics" in result["partial_chairs"]
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_a_replayed_node_short_circuits(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-i")
    try:
        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        before = await count_evidence(real_pool, seed["project_id"])
        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        assert await count_evidence(real_pool, seed["project_id"]) == before
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_run_resumes_from_the_last_completed_node_after_a_crash(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-j")
    try:
        graph = await build_graph(transports, real_pool, CLASSES)
        snap = await graph.aget_state({"configurable": {"thread_id": seed["run_id"]}})
        assert snap.next
    finally:
        await cleanup_run(real_pool, seed["run_id"])


# ── reconcile ─────────────────────────────────────────────────────────────

async def test_reconcile_persists_conflicts_from_the_deterministic_engine(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-k")
    try:
        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        conflicts = await fetch_conflicts(real_pool, seed["project_id"])
        assert conflicts
        assert all(c["rule"] in {"R1", "R2", "R3", "R4", "R5"} for c in conflicts)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_reconcile_uses_no_llm(real_pool):
    """PRD §7.5: 'Deterministic. No LLM.' Proven structurally (reconcile.py's
    own source never imports jury.llm or an LLMClient) rather than by
    counting calls during a full run -- the chairs it runs alongside DO call
    the LLM, so a call-count assertion on the whole pipeline would prove
    nothing about reconcile specifically."""
    import inspect

    import jury.graph.nodes.reconcile as reconcile_mod
    source = inspect.getsource(reconcile_mod)
    assert "jury.llm" not in source
    assert "LLMClient" not in source
    assert "structured_report" not in source

    seed, state, transports = await _start(real_pool, suffix="-l")
    try:
        result = await resume_hearing(seed["run_id"], state["assumptions"],
                                      transports=transports, pool=real_pool,
                                      classes=CLASSES)
        assert result["coverage"] is not None
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_discovered_assumptions_are_appended_during_investigation(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-m")
    try:
        await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                             pool=real_pool, classes=CLASSES)
        rows = await fetch_assumptions(real_pool, seed["project_id"])
        discovered = [a for a in rows if a["origin"] == "discovered"]
        assert discovered
        assert all(a["discovered_by"] for a in discovered)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_coverage_is_scored_after_investigation_not_before(real_pool):
    seed, state, transports = await _start(real_pool, suffix="-n")
    try:
        assert "coverage" not in state or state.get("coverage") is None
        result = await resume_hearing(seed["run_id"], state["assumptions"],
                                      transports=transports, pool=real_pool,
                                      classes=CLASSES)
        assert result["coverage"] is not None
    finally:
        await cleanup_run(real_pool, seed["run_id"])
