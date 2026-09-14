"""jury.chairs.economics / jury.chairs.base. Task 4.2. PRD §6.

Same demo pitch as the other four chairs: BillWise, an invoicing SaaS for
Indian small businesses. Economics only records industry-benchmark figures
(smallest budget, 3) -- it does not solve the founder's unit-economics
model; `jury.engines.economics` (Phase 5) does that.
"""
from jury.chairs import economics
from jury.chairs.base import ChairContext
from jury.retrieval.budgets import CHAIR_BUDGETS, BudgetLedger
from jury.retrieval.embed import Embedder
from jury.retrieval.verify import Rejection
from jury.schemas.assumption import AssumptionRecord
from jury.schemas.enums import Chair
from jury.schemas.scope import Scope
from jury.tracing.events import MemoryTraceSink
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports

ASSUMPTION_ID = "55555555-5555-5555-5555-555555555555"

PITCH_MAIN = "BillWise invoicing software for Indian small businesses"
PITCH_FABRICATED = "FastLedger demo pitch for the economics P1 rejection test"
DOMAIN_MAP: dict[str, int] = {}


async def _seed(pool, *, project_suffix: str = "") -> dict:
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
                "values (%s, %s, '{}') returning id",
                (user_id, "billwise-econ" + project_suffix))
            project_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', 't1') returning id",
                (project_id, user_id))
            run_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into assumptions (id, project_id, run_id, class_key, statement, "
                "origin, criticality, uncertainty, falsifiability, asserted_variable, "
                "asserted_value, asserted_unit) "
                "values (%s, %s, %s, 'saas.channel_cost', "
                "'Founders believe CAC will stay under 500 INR per customer', "
                "'founder', 'high', 'uncertain', 'testable_now', "
                "'cac', 500.0, 'INR')",
                (ASSUMPTION_ID, project_id, run_id))

    return {"project_id": str(project_id), "run_id": str(run_id)}


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


def _make_ctx(pool, seed: dict, *, pitch: str, budgets: BudgetLedger | None = None,
             trace=None) -> ChairContext:
    assumption = AssumptionRecord(
        id=ASSUMPTION_ID, statement="Founders believe CAC will stay under 500 "
        "INR per customer", class_key="saas.channel_cost", origin="founder",
        criticality="high", uncertainty="uncertain", falsifiability="testable_now",
        asserted_variable="cac", asserted_value=500.0, asserted_unit="INR")
    return ChairContext(
        run_id=seed["run_id"], project_id=seed["project_id"], pitch=pitch,
        target_scope=Scope(geo="IN", segment="smb"), assumptions=[assumption],
        transports=_transports(),
        budgets=budgets or BudgetLedger(MemoryKV(), seed["run_id"]),
        domain_map=DOMAIN_MAP, trace=trace if trace is not None else MemoryTraceSink(),
        pool=pool, embedder=Embedder(MemoryKV()))


async def _exhausted_budget(run_id: str) -> BudgetLedger:
    ledger = BudgetLedger(MemoryKV(), run_id)
    for _ in range(CHAIR_BUDGETS[Chair.ECONOMICS]):
        await ledger.spend(Chair.ECONOMICS, "brave")
    return ledger


async def count_evidence(pool, project_id: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from evidence_items where project_id = %s",
                (project_id,))
            return (await cur.fetchone())[0]


async def test_economics_emits_only_verified_claims(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await economics.investigate(ctx)

    assert result.inserted
    assert all(isinstance(x, str) for x in result.inserted)


async def test_a_rejected_claim_never_reaches_the_database(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_FABRICATED)
    result = await economics.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert isinstance(result.rejected[0], Rejection)
    assert await count_evidence(pool, seed["project_id"]) == 0


async def test_exhausted_budget_marks_the_chair_partial_not_failed(pool):
    seed = await _seed(pool)
    budgets = await _exhausted_budget(seed["run_id"])
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN, budgets=budgets)

    result = await economics.investigate(ctx)

    assert result.partial is True
    assert result.inserted == []


async def test_the_chair_writes_fetch_and_llm_rows_to_the_trace(pool):
    seed = await _seed(pool)
    trace = MemoryTraceSink()
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN, trace=trace)
    await economics.investigate(ctx)
    kinds = {r["event"] for r in trace.rows}
    assert {"fetch", "llm_call"} <= kinds
