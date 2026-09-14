"""Task 6.6: `POST /projects/{id}/export`. PRD §4, §7.10, §9, §23.

`project` is overridden locally (the standard pytest fixture-override idiom:
a fixture of the same name in this module takes the outer `conftest.py`
fixture as its own argument) to seed a project rich enough to exercise every
export section -- one assumption, one real evidence citation with a live
source URL, a real economics run (so breakpoints/parameters exist), a real
jury verdict, and one experiment with a proper P9 kill criterion. Every test
in this file therefore gets the same fully-populated project; the two
ownership/gating tests don't need that richness but sharing it is harmless
and keeps this file to one fixture, the same shape as
`test_result_logging.py`'s single `exp` fixture.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from psycopg_pool import AsyncConnectionPool

from jury.api.deps import get_transports
from jury.db.repositories import (
    AssumptionRepo,
    ConflictRepo,
    EvidenceRepo,
    ExperimentRepo,
    ModelRunRepo,
    SourceRepo,
    VerdictRepo,
)
from jury.graph.nodes.economics import EconomicsRepos, run_economics
from jury.graph.nodes.jury import JuryRepos, rule
from jury.retrieval.verify import VerifiedClaim
from jury.schemas.claim import ClaimRecord
from jury.schemas.enums import Chair, Direction
from jury.schemas.scope import Scope
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
TARGET = {"geo": "IN", "segment": "smb"}
CLASSES = [("pricing", 1.0, "does the founder's price hold?")]


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


@pytest.fixture
async def pool():
    p = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=4, open=False)
    await p.open()
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
def offline(app):
    transports = Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                            fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)
    app.dependency_overrides[get_transports] = lambda: transports
    yield SimpleNamespace(transports=transports)
    app.dependency_overrides.pop(get_transports, None)


async def _set_archetype(pool, project_id: str, archetype: str) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update projects set archetype = %s where id = %s",
                              (archetype, project_id))


async def _seed_run(pool, project_id: str, user_id: str) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s,%s,'initial','complete','export-test-seed') returning id",
                (project_id, user_id))
            return str((await cur.fetchone())[0])


async def _seed_assumption(pool, project_id: str, run_id: str, *, asserted_variable: str,
                           asserted_value: float) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into assumptions (project_id, run_id, statement, origin, "
                "criticality, uncertainty, falsifiability, asserted_variable, "
                "asserted_value) "
                "values (%s,%s,'Price point holds at scale','founder','blocking',"
                "'uncertain','testable_now',%s,%s) returning id",
                (project_id, run_id, asserted_variable, asserted_value))
            return str((await cur.fetchone())[0])


SOURCE_URL = "https://example.com/pricing-page"


@pytest.fixture
async def project(project, pool, auth, offline, user_a):
    """Overrides the outer `project` fixture (bare project, no data) with a
    fully-populated one: real evidence with a real citation URL, a real
    economics/jury pass, and one P9-valid experiment."""
    project_id = project
    await _set_archetype(pool, project_id, "subscription_saas")
    run_id = await _seed_run(pool, project_id, user_a)
    assumption_id = await _seed_assumption(
        pool, project_id, run_id, asserted_variable="price_monthly", asserted_value=499.0)

    source_id = await SourceRepo(pool).upsert(
        canonical_url=SOURCE_URL, domain="example.com", tier=1,
        title="Pricing page", http_status=200)
    claim = ClaimRecord(
        assumption_id=assumption_id, direction=Direction.SUPPORTS,
        variable="price_monthly", value_num=249.0, unit="INR", scope=Scope(**TARGET),
        confidence=0.8, source_url=SOURCE_URL, source_tier=1,
        excerpt="249/mo confirmed at checkout.", chair=Chair.ECONOMICS)
    verified = VerifiedClaim(claim=claim, tier=1, canonical_url=SOURCE_URL,
                             extracted_text=claim.excerpt, http_status=200)
    await EvidenceRepo(pool).insert_verified(project_id, run_id, assumption_id,
                                             source_id, verified)

    state = {"run_id": run_id, "project_id": project_id, "archetype": "subscription_saas",
             "target_scope": TARGET, "conflicts": []}
    econ_repos = EconomicsRepos(evidence=EvidenceRepo(pool), assumption=AssumptionRepo(pool),
                                model_run=ModelRunRepo(pool))
    econ_out = await run_economics(state, repos=econ_repos, transports=offline.transports)
    state = {**state, **econ_out}

    jury_repos = JuryRepos(assumption=AssumptionRepo(pool), evidence=EvidenceRepo(pool),
                           conflict=ConflictRepo(pool), verdict=VerdictRepo(pool),
                           classes=CLASSES)
    await rule(state, repos=jury_repos, transports=offline.transports)

    await ExperimentRepo(pool).create(
        project_id=project_id, assumption_id=assumption_id, target_variable="price_monthly",
        method="presale", instructions="Run a 20-user presale test for price_monthly at Rs 499.",
        kill_criterion="Pass if >=4 of 20 users pre-pay at Rs 499.",
        criterion_spec={"metric": "preorders", "comparator": ">=", "threshold": 4, "n": 20},
        est_cost=500.0, est_days=14, priority=1)

    return project_id


# ── helpers, mirroring the brief's pseudocode fetch_* names ──────────────

async def fetch_all_source_urls(pool, project_id: str) -> list[str]:
    rows = await EvidenceRepo(pool).list_for_project_with_tier(project_id)
    return [r["source_url"] for r in rows]


async def fetch_experiments(pool, project_id: str) -> list[dict]:
    return await ExperimentRepo(pool).list_for_project(project_id)


async def insert_experiment_without_criterion(pool, project_id: str) -> None:
    """P9's kill_criterion column is `not null` at the schema level (P9
    means the field is required, not merely non-empty-checked at read time)
    -- an empty string is the closest a DB insert can get to 'missing', and
    is exactly what the export route's own `not e.get('kill_criterion')`
    falsy check is written to catch."""
    assumptions = await AssumptionRepo(pool).list_for_project(project_id)
    await ExperimentRepo(pool).create(
        project_id=project_id, assumption_id=str(assumptions[0]["id"]), target_variable=None,
        method="survey", instructions="A second experiment with no pre-registered criterion.",
        kill_criterion="", criterion_spec={"metric": "x", "comparator": ">=", "threshold": 1},
        est_cost=None, est_days=None, priority=2)


# ── tests ──────────────────────────────────────────────────────────────

async def test_the_export_contains_every_evidence_citation(client, auth, project, pool):
    """PRD §23: 'Every claim in the output is clickable and verifiable.'"""
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth)
    assert r.status_code == 200, r.text
    md = r.text
    for url in await fetch_all_source_urls(pool, project):
        assert url in md


async def test_the_export_contains_the_verdict_and_all_four_components(client, auth, project):
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth)
    md = r.text
    for token in ("coverage", "mean_strength", "contradiction", "open_critical"):
        assert token in md


async def test_the_export_contains_every_kill_criterion(client, auth, project, pool):
    """P9: 'Required non-null field before the plan can be exported.'"""
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth)
    md = r.text
    for e in await fetch_experiments(pool, project):
        assert e["kill_criterion"] in md


async def test_export_is_refused_when_an_experiment_has_no_kill_criterion(client, auth,
                                                                          project, pool):
    """P9 enforced at the export boundary, exactly as PRD §4 specifies."""
    await insert_experiment_without_criterion(pool, project)
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth)
    assert r.status_code == 409


async def test_the_export_contains_the_breakpoint_sentences(client, auth, project):
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth)
    assert "becomes unviable" in r.text


async def test_the_export_content_type_is_markdown(client, auth, project):
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth)
    assert "text/markdown" in r.headers["content-type"]


async def test_another_users_project_cannot_be_exported(client, auth_b, project):
    r = await client.post(f"/projects/{project}/export", json={"format": "md"}, headers=auth_b)
    assert r.status_code in (403, 404)
