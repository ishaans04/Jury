"""jury.graph.nodes.jury. Task 5.4. PRD §9, §9.4, §9.5, §15.1.

Uses the rollback `pool` fixture, same reasoning as test_economics_node.py and
test_cross_exam.py: this module needs neither genuine concurrency nor
cross-process checkpoint visibility.
"""
import json

import pytest

from jury.db.repositories import AssumptionRepo, ConflictRepo, EvidenceRepo, VerdictRepo
from jury.graph.nodes.jury import JuryRepos, RationaleResponse, build_friction, rule
from jury.schemas.enums import Decision
from jury.transport.kv import MemoryKV
from jury.transport.protocols import LLMResponse, Transports

pytestmark = pytest.mark.asyncio

DECISIONS = {d.value for d in Decision}
CLASSES: list[tuple[str, float, str]] = [("a.class", 1.0, "a question?")]


class FakeLLM:
    def __init__(self, responder):
        self._responder = responder
        self.last_prompt: str | None = None
        self.calls = 0

    async def complete(self, *, model, messages, json_mode=False, temperature=0.0):
        prompt = messages[0]["content"]
        self.last_prompt = prompt
        self.calls += 1
        text = self._responder(prompt, self.calls)
        return LLMResponse(text=text, model=f"fake/{model}",
                           prompt_tokens=len(prompt) // 4, completion_tokens=8)

    def last_prompt_contains(self, needle: str) -> bool:
        return bool(self.last_prompt) and needle in self.last_prompt


class BrokenLLM:
    async def complete(self, *, model, messages, json_mode=False, temperature=0.0):
        raise RuntimeError("simulated LLM outage")


def _plain_rationale(text="Rationale citing the record."):
    def responder(prompt, call_number):
        return json.dumps({"rationale": text})
    return responder


def _claims_proceed():
    def responder(prompt, call_number):
        return json.dumps({"rationale": "You should proceed immediately, all clear."})
    return responder


def _transports(llm) -> Transports:
    return Transports(llm=llm, search=None, fetch=None, kv=MemoryKV(), offline=True)


# ── seeding ──────────────────────────────────────────────────────────────

async def _seed_project(pool, *, suffix="") -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'jury-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{}') returning id",
                (user_id, "juryco" + suffix))
            project_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', %s) returning id",
                (project_id, user_id, "jt" + suffix))
            run_id = (await cur.fetchone())[0]
    return {"project_id": str(project_id), "run_id": str(run_id)}


async def _seed_assumption(pool, seed, *, class_key="a.class", criticality="blocking",
                           asserted_variable=None) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            if class_key is not None:
                await cur.execute(
                    "insert into assumption_classes (key, archetype, label, question, "
                    "crit_weight) values (%s, 'marketplace', %s, 'q?', 1.0) "
                    "on conflict (key) do nothing", (class_key, class_key))
            await cur.execute(
                "insert into assumptions (project_id, run_id, class_key, statement, "
                "origin, criticality, uncertainty, falsifiability, asserted_variable) "
                "values (%s, %s, %s, 'a statement', 'founder', %s, 'uncertain', "
                "'testable_now', %s) returning id",
                (seed["project_id"], seed["run_id"], class_key, criticality,
                 asserted_variable))
            return str((await cur.fetchone())[0])


async def _seed_source(pool, *, tier=1, suffix="") -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values (%s, 'example.test', %s, 200) returning id",
                (f"https://example.test/jury{suffix}", tier))
            return str((await cur.fetchone())[0])


async def _seed_evidence(pool, seed, assumption_id, source_id, *, variable="x",
                         value_num=1.0, direction="supports", confidence=0.9,
                         dedup_suffix="") -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into evidence_items (project_id, run_id, assumption_id, "
                "source_id, chair, direction, variable, value_num, scope_geo, "
                "scope_segment, confidence, excerpt, dedup_hash) "
                "values (%s,%s,%s,%s,'market',%s,%s,%s,'IN','smb',%s,'excerpt',%s) "
                "returning id",
                (seed["project_id"], seed["run_id"], assumption_id, source_id,
                 direction, variable, value_num, confidence,
                 f"dedup-{source_id}-{assumption_id}{dedup_suffix}"))
            return str((await cur.fetchone())[0])


async def _seed_conflict(pool, seed, assumption_id, *, status="open",
                         severity="critical", kind="chair_vs_chair", rule="R1") -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into conflicts (project_id, run_id, assumption_id, kind, "
                "left_ref, right_ref, rule, severity, status) "
                "values (%s,%s,%s,%s,'{}','{}',%s,%s,%s) returning id",
                (seed["project_id"], seed["run_id"], assumption_id, kind, rule,
                 severity, status))
            return str((await cur.fetchone())[0])


async def _fetch_verdict(pool, verdict_id: str) -> dict:
    from psycopg.rows import dict_row
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("select * from verdicts where id = %s", (verdict_id,))
            return await cur.fetchone()


async def _fetch_blocking_open_assumption_ids(pool, project_id: str) -> set[str]:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select id from assumptions where project_id = %s "
                "and criticality in ('blocking','high') and status in "
                "('no_evidence','uncertain')", (project_id,))
            return {str(r[0]) for r in await cur.fetchall()}


def _repos(pool, classes=CLASSES) -> JuryRepos:
    return JuryRepos(assumption=AssumptionRepo(pool), evidence=EvidenceRepo(pool),
                     conflict=ConflictRepo(pool), verdict=VerdictRepo(pool),
                     classes=classes)


def _state(seed, *, model_run=None, conflicts=None) -> dict:
    return {"run_id": seed["run_id"], "project_id": seed["project_id"],
           "model_run": model_run or {"viable": True, "parameters": {},
                                      "sensitivity": [], "breakpoints": []},
           "conflicts": conflicts or []}


# ── a clean, PROCEED-eligible record ────────────────────────────────────

async def _seed_clean(pool, suffix) -> dict:
    seed = await _seed_project(pool, suffix=suffix)
    blocking_id = await _seed_assumption(pool, seed, criticality="blocking")
    source_id = await _seed_source(pool, suffix=suffix)
    for i in range(3):
        await _seed_evidence(pool, seed, blocking_id, source_id, confidence=0.9,
                             dedup_suffix=f"-{i}")
    return seed


# ── the single most important test in this batch ────────────────────────

async def test_the_verdict_is_computed_before_the_rationale_is_requested(pool):
    """The model explains a decision already made; it does not make one."""
    seed = await _seed_clean(pool, "-a")
    llm = FakeLLM(_plain_rationale())
    out = await rule(_state(seed), repos=_repos(pool), transports=_transports(llm))
    assert out["verdict"]["decision"] in DECISIONS
    assert llm.calls >= 1
    assert llm.last_prompt_contains(out["verdict"]["decision"])


async def test_an_llm_failure_still_produces_a_verdict(pool):
    """PRD §18: degrade to less prose, never to no decision."""
    seed = await _seed_clean(pool, "-b")
    out = await rule(_state(seed), repos=_repos(pool), transports=_transports(BrokenLLM()))
    assert out["verdict"]["decision"] in DECISIONS
    assert out["verdict"]["rationale"]


async def test_the_model_cannot_change_the_decision(pool):
    """Even if the model writes 'you should proceed', the computed gate wins."""
    seed = await _seed_project(pool, suffix="-c")
    # thin: nothing covers the sole class -> coverage gate fires regardless
    # of what the model's prose claims.
    await _seed_assumption(pool, seed, criticality="blocking")
    llm = FakeLLM(_claims_proceed())
    out = await rule(_state(seed), repos=_repos(pool), transports=_transports(llm))
    assert out["verdict"]["decision"] == "HUNG_JURY"


async def test_all_four_components_are_persisted_with_the_verdict(pool):
    """PRD §9.3 / F12: displayed with its formula."""
    seed = await _seed_clean(pool, "-d")
    out = await rule(_state(seed), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    row = await _fetch_verdict(pool, out["verdict_id"])
    assert set(row["components"]) == {"coverage", "mean_strength",
                                      "contradiction", "open_critical"}


async def test_the_gate_condition_that_fired_is_recorded(pool):
    seed = await _seed_project(pool, suffix="-e")
    await _seed_assumption(pool, seed, criticality="blocking")   # no evidence: coverage 0
    out = await rule(_state(seed), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    row = await _fetch_verdict(pool, out["verdict_id"])
    assert row["decision"] == "HUNG_JURY"
    assert row["gate_triggered"] == "coverage_below_0.70"


async def test_a_clean_verdict_records_no_gate_trigger(pool):
    seed = await _seed_clean(pool, "-f")
    out = await rule(_state(seed), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    row = await _fetch_verdict(pool, out["verdict_id"])
    assert row["decision"] != "HUNG_JURY"
    assert row["gate_triggered"] is None


# ── friction ─────────────────────────────────────────────────────────────

async def test_friction_names_the_conflicts_that_mattered():
    """PRD §7.8: 'Produces a friction summary naming the conflicts that mattered.'"""
    conflicts = [
        {"id": "c1", "kind": "chair_vs_chair", "rule": "R1", "severity": "critical",
         "status": "resolved"},
        {"id": "c2", "kind": "founder_vs_world", "rule": "R3", "severity": "high",
         "status": "open"},
    ]
    deltas = [{"conflict_id": "c1", "reason": "resolved via new tier-1 evidence"}]
    friction = build_friction(conflicts, deltas)
    assert friction
    assert all({"kind", "rule", "status"} <= set(f) for f in friction)
    assert any(f.get("resolution") for f in friction)


async def test_friction_excludes_low_severity_noise():
    conflicts = [{"id": "c1", "kind": "chair_vs_chair", "rule": "R2", "severity": "low",
                 "status": "open"}]
    assert build_friction(conflicts, []) == []


async def test_friction_reaches_the_persisted_verdict(pool):
    import uuid
    seed = await _seed_clean(pool, "-g")
    conflicts = [{"id": str(uuid.uuid4()), "kind": "chair_vs_chair", "rule": "R1",
                 "severity": "critical", "status": "open"}]
    out = await rule(_state(seed, conflicts=conflicts), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    assert out["verdict"]["friction"]
    assert out["verdict"]["friction"][0]["kind"] == "chair_vs_chair"


# ── hung jury experiments ───────────────────────────────────────────────

async def _seed_thin_evidence(pool, suffix) -> dict:
    """Three blocking, uninvestigated assumptions whose asserted variables
    map to sensitivity-ranked, method-mapped economics parameters -- coverage
    stays 0 (nothing has evidence), which is enough on its own to force
    HUNG_JURY regardless of which specific gate condition fires."""
    seed = await _seed_project(pool, suffix=suffix)
    b_take = await _seed_assumption(pool, seed, criticality="blocking",
                                    asserted_variable="take_rate")
    b_delivery = await _seed_assumption(pool, seed, criticality="high",
                                        asserted_variable="delivery_cost")
    b_aov = await _seed_assumption(pool, seed, criticality="blocking",
                                   asserted_variable="aov")
    model_run = {
        "viable": False,
        "parameters": {
            "take_rate": {"assumption_id": b_take, "provenance": "founder_asserted"},
            "delivery_cost": {"assumption_id": b_delivery, "provenance": "founder_asserted"},
            "aov": {"assumption_id": b_aov, "provenance": "founder_asserted"},
        },
        "sensitivity": [
            {"variable": "take_rate", "elasticity": 0.9, "provenance": "founder_asserted"},
            {"variable": "delivery_cost", "elasticity": 0.7, "provenance": "founder_asserted"},
            {"variable": "aov", "elasticity": 0.5, "provenance": "founder_asserted"},
        ],
        "breakpoints": [
            {"variable": "delivery_cost", "threshold": 42.0},
            {"variable": "aov", "threshold": 555.0},
        ],
    }
    return {**seed, "model_run": model_run,
           "ids": {"take_rate": b_take, "delivery_cost": b_delivery, "aov": b_aov}}


async def test_a_hung_jury_ships_exactly_three_experiments(pool):
    """PRD §9.4: 'A HUNG_JURY always ships with the three cheapest experiments
    that would break the deadlock.'"""
    seed = await _seed_thin_evidence(pool, "-h")
    out = await rule(_state(seed, model_run=seed["model_run"]), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    assert out["verdict"]["decision"] == "HUNG_JURY"
    assert len(out["hung_jury_experiments"]) == 3


async def test_hung_jury_experiments_are_the_cheapest_by_cost_then_days(pool):
    seed = await _seed_thin_evidence(pool, "-i")
    out = await rule(_state(seed, model_run=seed["model_run"]), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    plan = out["hung_jury_experiments"]
    keys = [(e["est_cost"], e["est_days"]) for e in plan]
    assert keys == sorted(keys)


async def test_hung_jury_experiments_target_the_blocking_unknowns(pool):
    seed = await _seed_thin_evidence(pool, "-j")
    out = await rule(_state(seed, model_run=seed["model_run"]), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    targets = {e["assumption_id"] for e in out["hung_jury_experiments"]}
    blocking_open = await _fetch_blocking_open_assumption_ids(pool, seed["project_id"])
    assert targets & blocking_open


async def test_a_supplier_quote_experiment_carries_a_nonzero_modelled_threshold(pool):
    """The modelled= plumbing must reach the actual returned draft, not just
    the persisted DB row -- delivery_cost's criterion threshold must be the
    real breakpoint (42.0), not a placeholder 0."""
    seed = await _seed_thin_evidence(pool, "-k")
    out = await rule(_state(seed, model_run=seed["model_run"]), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    supplier = next(e for e in out["hung_jury_experiments"]
                    if e["method"] == "supplier_quote")
    assert supplier["criterion_spec"]["threshold"] == pytest.approx(42.0)
    assert supplier["criterion_spec"]["threshold"] != 0.0


# ── the gate is unreachable-to-PROCEED proof, through the real node ─────

async def test_a_verdict_below_the_gate_can_never_be_proceed_through_the_wired_node(pool):
    """The Phase 1 unreachability proof, now through the real node."""
    # low coverage
    seed1 = await _seed_project(pool, suffix="-l1")
    await _seed_assumption(pool, seed1, criticality="blocking")
    out1 = await rule(_state(seed1), repos=_repos(pool),
                      transports=_transports(FakeLLM(_plain_rationale())))
    assert out1["verdict"]["decision"] == "HUNG_JURY"

    # blocking assumption unresolved (no evidence, but coverage forced via a
    # second, evidence-bearing assumption in the same class)
    seed2 = await _seed_project(pool, suffix="-l2")
    covered_id = await _seed_assumption(pool, seed2, criticality="medium")
    src = await _seed_source(pool, suffix="-l2")
    await _seed_evidence(pool, seed2, covered_id, src)
    await _seed_assumption(pool, seed2, criticality="blocking")   # no evidence -> open
    out2 = await rule(_state(seed2), repos=_repos(pool),
                      transports=_transports(FakeLLM(_plain_rationale())))
    assert out2["verdict"]["decision"] == "HUNG_JURY"

    # low confidence: one strong blocking assumption dragged down by five
    # uninvestigated high-criticality peers plus an unresolved conflict on
    # the blocking assumption itself (zeroes the contradiction credit).
    seed3 = await _seed_project(pool, suffix="-l3")
    blocking_id = await _seed_assumption(pool, seed3, criticality="blocking")
    src3 = await _seed_source(pool, suffix="-l3")
    for i in range(3):
        await _seed_evidence(pool, seed3, blocking_id, src3, confidence=0.9,
                             dedup_suffix=f"-{i}")
    await _seed_conflict(pool, seed3, blocking_id, status="open", severity="high")
    for i in range(5):
        await _seed_assumption(pool, seed3, criticality="high")
    out3 = await rule(_state(seed3), repos=_repos(pool),
                      transports=_transports(FakeLLM(_plain_rationale())))
    assert out3["verdict"]["decision"] == "HUNG_JURY"


async def test_evidence_confidence_is_recomputed_not_carried_forward(pool):
    from jury.engines.scoring import AssumptionLike, EvidenceLike, evidence_confidence
    from jury.schemas.enums import Criticality, Direction

    seed = await _seed_clean(pool, "-m")
    out = await rule(_state(seed), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))

    assumptions = [AssumptionLike(
        id="x", class_key="a.class", criticality=Criticality.BLOCKING,
        evidence=[EvidenceLike(tier=1, confidence=0.9, direction=Direction.SUPPORTS)
                 for _ in range(3)])]
    class_pairs = [(key, weight) for key, weight, _q in CLASSES]
    recomputed, _ = evidence_confidence(class_pairs, assumptions, unresolved_conflicts=0)
    assert out["verdict"]["evidence_confidence"] == pytest.approx(recomputed, abs=0.01)


async def test_the_rationale_cites_the_record_rather_than_offering_advice(pool):
    seed = await _seed_clean(pool, "-n")
    out = await rule(_state(seed), repos=_repos(pool),
                     transports=_transports(FakeLLM(_plain_rationale())))
    assert out["verdict"]["rationale"]
    assert "I think" not in out["verdict"]["rationale"]
