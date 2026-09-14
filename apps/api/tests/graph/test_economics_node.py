"""jury.graph.nodes.economics. Task 5.3. PRD §16.5, §7.7.

Uses the rollback `pool` fixture (tests/graph/conftest.py) -- this module
needs neither genuine concurrency nor cross-process checkpoint visibility,
the same reasoning `tests/graph/test_cross_exam.py` gives for its own choice.
"""
import json

import pytest

from jury.db.repositories import AssumptionRepo, EvidenceRepo, ModelRunRepo
from jury.engines.economics.templates import TEMPLATES
from jury.graph.nodes.economics import (
    ARCHETYPE_TEMPLATES, EconomicsRepos, bind_parameters, run_economics,
)
from jury.schemas.enums import Archetype, Provenance
from jury.transport.kv import MemoryKV
from jury.transport.protocols import LLMResponse, Transports

pytestmark = pytest.mark.asyncio

TARGET_SCOPE = {"geo": "IN", "segment": "smb"}
US_SCOPE = {"geo": "US", "segment": "enterprise"}


class CountingLLM:
    """Records how many times `complete` is called -- P8's own witness."""

    def __init__(self):
        self.calls = 0

    async def complete(self, *, model, messages, json_mode=False, temperature=0.0):
        self.calls += 1
        return LLMResponse(text="{}", model=f"fake/{model}", prompt_tokens=1,
                           completion_tokens=1)


def _transports(llm=None) -> Transports:
    return Transports(llm=llm or CountingLLM(), search=None, fetch=None,
                      kv=MemoryKV(), offline=True)


async def _seed_project(pool, *, suffix="", target_scope=None) -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'econ-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, %s) returning id",
                (user_id, "econco" + suffix, json.dumps(target_scope or TARGET_SCOPE)))
            project_id = (await cur.fetchone())[0]
            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', %s) returning id",
                (project_id, user_id, "et" + suffix))
            run_id = (await cur.fetchone())[0]
    return {"project_id": str(project_id), "run_id": str(run_id)}


async def _seed_assumption(pool, seed, *, asserted_variable=None, asserted_value=None,
                           criticality="medium") -> str:
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


async def _seed_source(pool, *, tier=1, url_suffix="") -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values (%s, 'example.test', %s, 200) returning id",
                (f"https://example.test/{tier}{url_suffix}", tier))
            return str((await cur.fetchone())[0])


async def _seed_evidence(pool, seed, assumption_id, source_id, *, variable, value_num,
                         direction="supports", confidence=0.8,
                         scope=None) -> str:
    scope = scope or TARGET_SCOPE
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into evidence_items (project_id, run_id, assumption_id, "
                "source_id, chair, direction, variable, value_num, scope_geo, "
                "scope_segment, confidence, excerpt, dedup_hash) "
                "values (%s,%s,%s,%s,'market',%s,%s,%s,%s,%s,%s,'excerpt',%s) "
                "returning id",
                (seed["project_id"], seed["run_id"], assumption_id, source_id,
                 direction, variable, value_num, scope["geo"], scope["segment"],
                 confidence, f"dedup-{source_id}-{variable}-{direction}"))
            return str((await cur.fetchone())[0])


async def _fetch_model_run_direct(pool, model_run_id: str) -> dict:
    from psycopg.rows import dict_row
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("select * from model_runs where id = %s", (model_run_id,))
            return await cur.fetchone()


def _repos(pool) -> EconomicsRepos:
    return EconomicsRepos(evidence=EvidenceRepo(pool), assumption=AssumptionRepo(pool),
                          model_run=ModelRunRepo(pool))


def _state(seed, *, archetype="marketplace", target_scope=None) -> dict:
    return {"run_id": seed["run_id"], "project_id": seed["project_id"],
           "archetype": archetype, "target_scope": target_scope or TARGET_SCOPE}


# ── provenance ────────────────────────────────────────────────────────────

async def test_evidence_backed_parameters_carry_their_source_id(pool):
    seed = await _seed_project(pool, suffix="-a")
    assumption_id = await _seed_assumption(pool, seed)
    source_id = await _seed_source(pool, tier=1)
    await _seed_evidence(pool, seed, assumption_id, source_id,
                         variable="take_rate", value_num=0.12)

    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert params["take_rate"].provenance is Provenance.EVIDENCE_BACKED
    assert params["take_rate"].source_id == source_id


async def test_a_founder_assertion_without_evidence_stays_founder_asserted(pool):
    seed = await _seed_project(pool, suffix="-b")
    await _seed_assumption(pool, seed, asserted_variable="take_rate",
                           asserted_value=0.15)

    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert params["take_rate"].provenance is Provenance.FOUNDER_ASSERTED
    assert params["take_rate"].source_id is None


async def test_evidence_outranks_a_founder_assertion(pool):
    """P2: founder claims are expected to lose arguments against evidence."""
    seed = await _seed_project(pool, suffix="-c")
    a1 = await _seed_assumption(pool, seed, asserted_variable="take_rate",
                                asserted_value=0.30)
    source_id = await _seed_source(pool, tier=1)
    await _seed_evidence(pool, seed, a1, source_id, variable="take_rate", value_num=0.09)

    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert params["take_rate"].value == pytest.approx(0.09)
    assert params["take_rate"].value != pytest.approx(0.30)


async def test_higher_tier_evidence_outranks_lower_tier(pool):
    seed = await _seed_project(pool, suffix="-d")
    a1 = await _seed_assumption(pool, seed)
    tier1_source = await _seed_source(pool, tier=1, url_suffix="-t1")
    tier4_source = await _seed_source(pool, tier=4, url_suffix="-t4")
    await _seed_evidence(pool, seed, a1, tier4_source, variable="take_rate",
                         value_num=0.50, confidence=0.9)
    await _seed_evidence(pool, seed, a1, tier1_source, variable="take_rate",
                         value_num=0.11, confidence=0.5)

    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert params["take_rate"].value == pytest.approx(0.11)


async def test_evidence_outside_the_target_scope_is_not_bound(pool):
    """Otherwise US-enterprise pricing would silently drive an India-SMB model."""
    seed = await _seed_project(pool, suffix="-e")
    a1 = await _seed_assumption(pool, seed, asserted_variable="take_rate",
                                asserted_value=0.13)
    source_id = await _seed_source(pool, tier=1)
    await _seed_evidence(pool, seed, a1, source_id, variable="take_rate",
                         value_num=0.40, scope=US_SCOPE)

    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert params["take_rate"].provenance is Provenance.FOUNDER_ASSERTED
    assert params["take_rate"].value == pytest.approx(0.13)


async def test_a_refuting_evidence_item_is_not_used_as_a_parameter_value(pool):
    """'X is not 500' is not a measurement of X."""
    seed = await _seed_project(pool, suffix="-f")
    a1 = await _seed_assumption(pool, seed, asserted_variable="take_rate",
                                asserted_value=0.13)
    source_id = await _seed_source(pool, tier=1)
    await _seed_evidence(pool, seed, a1, source_id, variable="take_rate",
                         value_num=0.60, direction="refutes")

    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert params["take_rate"].provenance is Provenance.FOUNDER_ASSERTED
    assert params["take_rate"].value == pytest.approx(0.13)


async def test_a_missing_parameter_falls_back_to_the_template_default(pool):
    seed = await _seed_project(pool, suffix="-g")
    params = await bind_parameters(_state(seed), repos=_repos(pool))
    assert set(params) == set(TEMPLATES["marketplace_v1"].params)
    assert all(p.provenance is Provenance.FOUNDER_ASSERTED and p.source_id is None
              for p in params.values())


async def test_each_archetype_maps_to_a_template(pool):
    assert set(ARCHETYPE_TEMPLATES) == set(Archetype)
    assert ARCHETYPE_TEMPLATES[Archetype.AD_CONSUMER] == "saas_v1"
    assert ARCHETYPE_TEMPLATES[Archetype.HARDWARE] == "d2c_v1"


# ── run_economics / persistence ─────────────────────────────────────────

async def test_ad_consumer_substitution_is_recorded_not_hidden(pool):
    seed = await _seed_project(pool, suffix="-h")
    out = await run_economics(_state(seed, archetype="ad_consumer"),
                              repos=_repos(pool), transports=_transports())
    row = await _fetch_model_run_direct(pool, out["model_run_id"])
    assert row["template_key"] == "saas_v1"


async def test_the_model_run_persists_parameters_breakpoints_and_sensitivity(pool):
    seed = await _seed_project(pool, suffix="-i")
    out = await run_economics(_state(seed), repos=_repos(pool), transports=_transports())
    row = await _fetch_model_run_direct(pool, out["model_run_id"])
    assert row["parameters"] and row["breakpoints"] and row["sensitivity"]
    assert isinstance(row["viable"], bool)


async def test_every_persisted_parameter_records_its_provenance(pool):
    seed = await _seed_project(pool, suffix="-j")
    out = await run_economics(_state(seed), repos=_repos(pool), transports=_transports())
    row = await _fetch_model_run_direct(pool, out["model_run_id"])
    assert all("provenance" in v for v in row["parameters"].values())


async def test_the_node_makes_no_llm_call(pool):
    """P8: economics is computed, not described. The node binds and solves;
    it does not ask a model for a number."""
    seed = await _seed_project(pool, suffix="-k")
    llm = CountingLLM()
    before = llm.calls
    await run_economics(_state(seed), repos=_repos(pool), transports=_transports(llm))
    assert llm.calls == before


async def test_economics_reruns_after_cross_examination(pool):
    """PRD §7.7: 'The model is (re-)executed with the best available parameters
    AFTER cross-examination.'"""
    seed = await _seed_project(pool, suffix="-l")
    first = await run_economics(_state(seed), repos=_repos(pool), transports=_transports())

    a1 = await _seed_assumption(pool, seed)
    source_id = await _seed_source(pool, tier=1, url_suffix="-rerun")
    await _seed_evidence(pool, seed, a1, source_id, variable="aov", value_num=5000.0)

    second = await run_economics(_state(seed), repos=_repos(pool), transports=_transports())

    first_row = await _fetch_model_run_direct(pool, first["model_run_id"])
    second_row = await _fetch_model_run_direct(pool, second["model_run_id"])
    assert second_row["parameters"] != first_row["parameters"]


async def test_the_solve_completes_within_three_seconds(pool):
    """PRD §17.1 target."""
    import time
    seed = await _seed_project(pool, suffix="-m")
    started = time.perf_counter()
    await run_economics(_state(seed), repos=_repos(pool), transports=_transports())
    assert time.perf_counter() - started < 3.0
