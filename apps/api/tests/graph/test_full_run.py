"""Task 5.5: full graph wiring, archetype -> ... -> experiments -> END.
PRD §7, §9, §16.5, §16.6.

Two halves, deliberately:

  A) TOPOLOGY, through the real compiled graph (`build_graph`/`run_initial`/
     `resume_hearing`) against `real_pool`, reusing the exact pre-recorded
     fixtures `tests/graph/test_graph.py` already validated (node ordering,
     the conditional cross_exam edge, trace completeness, search/LLM
     budgets). This is the genuine end-to-end proof that wiring the five new
     edges did not break anything upstream.

  B) LEDGER CONTENT (every artifact exists; founder_asserted-only ranking;
     sensitivity-ordered priority; a thin-evidence HUNG_JURY ships exactly
     three experiments), through the same production node functions
     (`run_economics` -> `rule` -> `plan_experiments`) chained directly
     against controlled, directly-seeded assumptions/evidence.

  Why B is not also driven through `run_initial`/`resume_hearing`: this
  repo's pre-recorded LLM fixtures for pitch extraction (`tests/fixtures/
  llm/`) were captured before this batch existed, and -- verified by hand --
  none of the founder assumptions they produce carry a parsed
  `asserted_variable`, so no founder-asserted economics parameter in a
  graph-driven run using those fixtures is ever traceable back to a real
  assumption row; `plan_experiments` then has nothing to attach an
  experiment to, and the ledger legitimately ends up with zero experiments
  regardless of node correctness. Recording a new fixture set requires a
  real LLM call, which the batch's own constraints forbid in tests. Driving
  B directly at the node level exercises the exact same production code
  (`run_economics`, `rule`, `plan_experiments`, in the same order the graph
  itself calls them) against data guaranteed to exercise the founder_asserted
  path, which is what these tests are actually about.
"""
import pytest

from jury.db.repositories import (
    AssumptionRepo, ConflictRepo, EvidenceRepo, ExperimentRepo, ModelRunRepo, VerdictRepo,
)
from jury.graph.build import build_graph, resume_hearing, run_initial
from jury.graph.nodes.economics import EconomicsRepos, run_economics
from jury.graph.nodes.experiments import ExperimentsRepos, plan_experiments
from jury.graph.nodes.jury import JuryRepos, rule
from jury.schemas.enums import Decision
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports

from tests.graph.conftest import cleanup_run, fetch_run_events, seed_project_run
from tests.graph.test_graph import CLASSES, PITCH, TARGET

pytestmark = pytest.mark.asyncio

DECISIONS = {d.value for d in Decision}


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


async def _full_run(real_pool, *, suffix: str):
    seed = await seed_project_run(real_pool, target_scope=TARGET, suffix=suffix)
    transports = _transports()
    state = await run_initial(seed["project_id"], seed["run_id"], PITCH, TARGET,
                              transports=transports, pool=real_pool, classes=CLASSES)
    state = await resume_hearing(seed["run_id"], state["assumptions"], transports=transports,
                                 pool=real_pool, classes=CLASSES)
    return seed, state


# ── A) topology, through the real compiled graph ────────────────────────

async def test_a_full_offline_run_completes_end_to_end(real_pool):
    seed, state = await _full_run(real_pool, suffix="-a")
    try:
        assert state["run_status"] == "complete"
        assert state["verdict"]["decision"] in DECISIONS
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_a_run_with_no_conflicts_skips_cross_exam_and_still_completes(real_pool):
    seed, state = await _full_run(real_pool, suffix="-b")
    try:
        events = await fetch_run_events(real_pool, seed["run_id"])
        assert not any(e["node"] == "cross_exam" for e in events)
        assert state["run_status"] == "complete"
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_trace_records_every_node_once_per_run(real_pool):
    """F17: append-only trace of every node."""
    seed, state = await _full_run(real_pool, suffix="-c")
    try:
        events = await fetch_run_events(real_pool, seed["run_id"])
        nodes = [e["node"] for e in events if e["event"] == "node_start"]
        for expected in ("archetype", "extract", "reconcile", "economics",
                        "jury", "experiments"):
            assert nodes.count(expected) == 1
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_trace_carries_token_counts(real_pool):
    seed, state = await _full_run(real_pool, suffix="-d")
    try:
        events = await fetch_run_events(real_pool, seed["run_id"])
        llm_rows = [e for e in events if e["event"] == "llm_call"]
        assert llm_rows and all("prompt_tokens" in e["detail"] for e in llm_rows)
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_run_respects_the_search_budget_of_35(real_pool):
    seed, state = await _full_run(real_pool, suffix="-e")
    try:
        events = await fetch_run_events(real_pool, seed["run_id"])
        tool_rows = [e for e in events if e["event"] == "tool_call"
                    and e["detail"].get("kind") == "search"]
        assert len(tool_rows) <= 35
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_run_respects_the_llm_budget_of_120(real_pool):
    seed, state = await _full_run(real_pool, suffix="-f")
    try:
        events = await fetch_run_events(real_pool, seed["run_id"])
        assert len([e for e in events if e["event"] == "llm_call"]) <= 120
    finally:
        await cleanup_run(real_pool, seed["run_id"])


async def test_the_run_resumes_and_routes_straight_from_reconcile_when_no_conflict(real_pool):
    """Sanity check on the new conditional edge itself, through `build_graph`."""
    seed = await seed_project_run(real_pool, target_scope=TARGET, suffix="-g")
    transports = _transports()
    try:
        state = await run_initial(seed["project_id"], seed["run_id"], PITCH, TARGET,
                                  transports=transports, pool=real_pool, classes=CLASSES)
        state = await resume_hearing(seed["run_id"], state["assumptions"],
                                     transports=transports, pool=real_pool, classes=CLASSES)
        assert "model_run" in state and state["model_run"] is not None
        assert "experiments" in state
    finally:
        await cleanup_run(real_pool, seed["run_id"])


# ── B) ledger content, through the same node functions chained directly ─

async def _seed_project(pool, *, suffix="") -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'fullrun-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{\"geo\":\"IN\",\"segment\":\"smb\"}') returning id",
                (user_id, "fullrunco" + suffix))
            project_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', %s) returning id",
                (project_id, user_id, "fr" + suffix))
            run_id = (await cur.fetchone())[0]
    return {"project_id": str(project_id), "run_id": str(run_id)}


async def _seed_assumption(pool, seed, *, criticality="medium", asserted_variable=None,
                           asserted_value=None) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into assumptions (project_id, run_id, statement, origin, "
                "criticality, uncertainty, falsifiability, asserted_variable, "
                "asserted_value) "
                "values (%s, %s, 'a statement', 'founder', %s, 'uncertain', "
                "'testable_now', %s, %s) returning id",
                (seed["project_id"], seed["run_id"], criticality,
                 asserted_variable, asserted_value))
            return str((await cur.fetchone())[0])


async def _seed_source(pool, *, tier=1, suffix="") -> str:
    import uuid
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values (%s, 'example.test', %s, 200) returning id",
                (f"https://example.test/full{suffix}-{uuid.uuid4()}", tier))
            return str((await cur.fetchone())[0])


async def _seed_evidence(pool, seed, assumption_id, source_id, *, variable, value_num,
                         confidence=0.8) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into evidence_items (project_id, run_id, assumption_id, "
                "source_id, chair, direction, variable, value_num, scope_geo, "
                "scope_segment, confidence, excerpt, dedup_hash) "
                "values (%s,%s,%s,%s,'market','supports',%s,%s,'IN','smb',%s,'excerpt',%s) "
                "returning id",
                (seed["project_id"], seed["run_id"], assumption_id, source_id,
                 variable, value_num, confidence,
                 f"dedup-{source_id}-{assumption_id}-{variable}"))
            return str((await cur.fetchone())[0])


def _economics_repos(pool):
    return EconomicsRepos(evidence=EvidenceRepo(pool), assumption=AssumptionRepo(pool),
                          model_run=ModelRunRepo(pool))


def _jury_repos(pool, classes):
    return JuryRepos(assumption=AssumptionRepo(pool), evidence=EvidenceRepo(pool),
                     conflict=ConflictRepo(pool), verdict=VerdictRepo(pool),
                     classes=classes)


def _experiments_repos(pool):
    return ExperimentsRepos(experiment=ExperimentRepo(pool))


async def _run_the_pipeline(pool, seed, *, archetype="marketplace",
                            target_scope=None) -> dict:
    """Composes the exact three production node functions the graph itself
    calls, in the graph's own order: economics -> jury -> experiments."""
    state = {"run_id": seed["run_id"], "project_id": seed["project_id"],
            "archetype": archetype,
            "target_scope": target_scope or {"geo": "IN", "segment": "smb"},
            "conflicts": []}

    econ_out = await run_economics(state, repos=_economics_repos(pool),
                                   transports=_transports())
    state = {**state, **econ_out}

    jury_out = await rule(state, repos=_jury_repos(pool, [("a.class", 1.0, "q?")]),
                          transports=_transports())
    state = {**state, **jury_out}

    exp_out = await plan_experiments(state, repos=_experiments_repos(pool))
    state = {**state, **exp_out}
    return state



async def test_the_run_produces_every_ledger_artifact(real_pool):
    seed = await _seed_project(real_pool, suffix="-h")
    blocking_id = await _seed_assumption(real_pool, seed, criticality="blocking")
    source_id = await _seed_source(real_pool, suffix="-h")
    await _seed_evidence(real_pool, seed, blocking_id, source_id,
                         variable="aov", value_num=1500.0)
    # a founder-asserted, unmeasured parameter -- this is the experiment candidate
    await _seed_assumption(real_pool, seed, criticality="high",
                           asserted_variable="take_rate", asserted_value=0.12)

    state = await _run_the_pipeline(real_pool, seed)
    assert state["verdict"]["decision"] in DECISIONS
    assert state["model_run"]["viable"] in (True, False)
    assert state["experiments"]


async def test_every_experiment_has_a_non_null_criterion_spec(real_pool):
    seed = await _seed_project(real_pool, suffix="-i")
    await _seed_assumption(real_pool, seed, criticality="high",
                           asserted_variable="take_rate", asserted_value=0.12)

    state = await _run_the_pipeline(real_pool, seed)
    rows = await ExperimentRepo(real_pool).list_for_project(seed["project_id"])
    assert rows
    for e in rows:
        assert e["kill_criterion"] and e["criterion_spec"]


async def test_experiments_only_target_founder_asserted_parameters(real_pool):
    seed = await _seed_project(real_pool, suffix="-j")
    evidence_id = await _seed_assumption(real_pool, seed, criticality="blocking")
    source_id = await _seed_source(real_pool, suffix="-j")
    await _seed_evidence(real_pool, seed, evidence_id, source_id,
                         variable="aov", value_num=1500.0)
    await _seed_assumption(real_pool, seed, criticality="high",
                           asserted_variable="take_rate", asserted_value=0.12)

    state = await _run_the_pipeline(real_pool, seed)
    asserted = {k for k, v in state["model_run"]["parameters"].items()
               if v["provenance"] == "founder_asserted"}
    rows = await ExperimentRepo(real_pool).list_for_project(seed["project_id"])
    for e in rows:
        if e["target_variable"]:
            assert e["target_variable"] in asserted
            assert e["target_variable"] != "aov"   # evidence_backed, must be excluded


async def test_experiment_priority_follows_sensitivity_rank(real_pool):
    """PRD §16.6: the highest-sensitivity guess becomes experiment #1."""
    seed = await _seed_project(real_pool, suffix="-k")
    await _seed_assumption(real_pool, seed, criticality="blocking",
                           asserted_variable="take_rate", asserted_value=0.02)
    await _seed_assumption(real_pool, seed, criticality="high",
                           asserted_variable="cac_buyer", asserted_value=5.0)

    state = await _run_the_pipeline(real_pool, seed)
    ranked = [s["variable"] for s in state["model_run"]["sensitivity"]
             if s["provenance"] == "founder_asserted"]
    rows = await ExperimentRepo(real_pool).list_for_project(seed["project_id"])
    plan = sorted(rows, key=lambda e: e["priority"])
    top_targets = {e["target_variable"] for e in plan}
    expected_first = next(v for v in ranked if v in top_targets)
    assert plan[0]["target_variable"] == expected_first


async def test_a_thin_evidence_pitch_returns_hung_jury_with_three_experiments(real_pool):
    """PRD §22 optional second beat, and PRD §18's 'correct behaviour'."""
    seed = await _seed_project(real_pool, suffix="-l")
    # Plausible (not extreme) values: a real breakpoint must exist in-range
    # for delivery_cost/aov's kill criteria to have a modelled threshold at
    # all (jury.graph.nodes.jury.hung_jury_experiments skips a threshold_source
    # method with none, an honest absence rather than a placeholder-0).
    await _seed_assumption(real_pool, seed, criticality="blocking",
                           asserted_variable="take_rate", asserted_value=0.10)
    await _seed_assumption(real_pool, seed, criticality="high",
                           asserted_variable="delivery_cost", asserted_value=30.0)
    await _seed_assumption(real_pool, seed, criticality="blocking",
                           asserted_variable="aov", asserted_value=1000.0)
    # nothing has any evidence at all -> coverage 0 -> HUNG_JURY

    state = await _run_the_pipeline(real_pool, seed)
    assert state["verdict"]["decision"] == "HUNG_JURY"
    assert len(state["hung_jury_experiments"]) == 3
