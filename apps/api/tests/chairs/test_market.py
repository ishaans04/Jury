"""jury.chairs.market / jury.chairs.base. Task 3.7.

Demo pitch: an invoicing SaaS for Indian small businesses, PRD §22's
"crowded space where real contradictions and real corpses exist" -- GST
invoicing has many real competitors. The founder asserts `price_monthly` =
499 INR/month; the Market chair's own query strategy (`price_monthly` ->
"... pricing") is what finds a real competitor's page charging 149 INR/month,
which is the exact founder-vs-world shape R3 (jury/engines/conflict.py) exists
to catch later.

Three distinct pitches are used across the scenarios below (rather than one
pitch reused with distinct budget/fixture setups) so that each scenario's
`_build_queries` output hashes to fixture keys the other scenarios never
touch -- a fabricated-claim run must not also see the happy-path pricing hit,
and vice versa.

Uses the `pool` fixture from tests/chairs/conftest.py: one real Postgres
connection per test, held in an uncommitted transaction always rolled back at
teardown (same pattern as tests/db/test_repositories.py).
"""
from jury.chairs import market
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

ASSUMPTION_ID = "11111111-1111-1111-1111-111111111111"

PITCH_MAIN = "BillWise invoicing software for Indian small businesses"
PITCH_FABRICATED = "ZapLedger demo pitch for the P1 rejection test"
PITCH_NEW_ASSUMPTION = "NoteVault demo pitch for the discovered-assumption test"

DOMAIN_MAP: dict[str, int] = {}


async def _seed(pool, *, project_suffix: str = "") -> dict:
    """The FK chain a chair needs: one auth user, one project, one run, and
    one FOUNDER assumption inserted with a fixed id (rather than
    AssumptionRepo.create_many's generated uuid) so the recorded LLM fixtures
    -- which must name a concrete assumption_id -- can target it."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'market-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{}') returning id",
                (user_id, "billwise" + project_suffix))
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
                "values (%s, %s, %s, 'saas.wtp_above_cost', "
                "'Founders believe 499 INR/month is acceptable pricing for SMBs', "
                "'founder', 'medium', 'uncertain', 'testable_now', "
                "'price_monthly', 499.0, 'INR_per_month')",
                (ASSUMPTION_ID, project_id, run_id))

    return {"project_id": str(project_id), "run_id": str(run_id)}


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


def _make_ctx(pool, seed: dict, *, pitch: str, budgets: BudgetLedger | None = None,
             trace=None) -> ChairContext:
    assumption = AssumptionRecord(
        id=ASSUMPTION_ID, statement="Founders believe 499 INR/month is acceptable "
        "pricing for SMBs", class_key="saas.wtp_above_cost", origin="founder",
        criticality="medium", uncertainty="uncertain", falsifiability="testable_now",
        asserted_variable="price_monthly", asserted_value=499.0,
        asserted_unit="INR_per_month")
    return ChairContext(
        run_id=seed["run_id"], project_id=seed["project_id"], pitch=pitch,
        target_scope=Scope(geo="IN", segment="smb"), assumptions=[assumption],
        transports=_transports(),
        budgets=budgets or BudgetLedger(MemoryKV(), seed["run_id"]),
        domain_map=DOMAIN_MAP, trace=trace if trace is not None else MemoryTraceSink(),
        pool=pool, embedder=Embedder(MemoryKV()))


async def _exhausted_budget(run_id: str) -> BudgetLedger:
    ledger = BudgetLedger(MemoryKV(), run_id)
    for _ in range(CHAIR_BUDGETS[Chair.MARKET]):
        await ledger.spend(Chair.MARKET, "brave")
    return ledger


async def count_evidence(pool, project_id: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from evidence_items where project_id = %s",
                (project_id,))
            return (await cur.fetchone())[0]


async def count_sources(pool, canonical_url: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from sources where canonical_url = %s",
                (canonical_url,))
            return (await cur.fetchone())[0]


async def fetch_evidence(pool, evidence_id: str) -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select chair, scope_geo, scope_segment from evidence_items "
                "where id = %s", (evidence_id,))
            row = await cur.fetchone()
    return {"chair": row[0], "scope_geo": row[1], "scope_segment": row[2]}


# ── the happy path ───────────────────────────────────────────────────────

async def test_market_emits_only_verified_claims(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await market.investigate(ctx)

    assert result.inserted
    for eid in result.inserted:
        row = await fetch_evidence(pool, eid)
        assert row["chair"] == "market"
        assert row["scope_geo"] and row["scope_segment"]


async def test_the_chair_emits_no_prose_only_typed_records(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await market.investigate(ctx)
    assert all(isinstance(x, str) for x in result.inserted)


async def test_the_chair_writes_fetch_and_llm_rows_to_the_trace(pool):
    seed = await _seed(pool)
    trace = MemoryTraceSink()
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN, trace=trace)
    await market.investigate(ctx)
    kinds = {r["event"] for r in trace.rows}
    assert {"fetch", "llm_call"} <= kinds


async def test_running_twice_inserts_no_duplicates(pool):
    """P10 end to end."""
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)

    first = await market.investigate(ctx)
    second = await market.investigate(ctx)

    assert first.inserted
    assert second.inserted == []


async def test_the_chair_records_a_source_row_before_the_evidence_row(pool):
    """FK ordering: an evidence row's source_id can only ever point at a
    source row that already exists, and (the actual point of this test) a
    verified claim's source is written -- there is no path in base.py that
    inserts evidence without first upserting its source."""
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await market.investigate(ctx)

    assert result.inserted
    assert await count_sources(pool, "https://billwiseapp.test/pricing") == 1


# ── P1: rejection leaves zero rows ──────────────────────────────────────

async def test_a_rejected_claim_never_reaches_the_database(pool):
    """P1 is an ordering guarantee, not just a check: the fabricated excerpt
    is genuinely absent from the fetched page (real rejection path, not a
    synthetic one), and neither an evidence row nor an orphan source row may
    exist afterwards."""
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_FABRICATED)
    result = await market.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert isinstance(result.rejected[0], Rejection)
    assert await count_evidence(pool, seed["project_id"]) == 0
    assert await count_sources(pool, "https://fundwire.test/deals/zapledger") == 0


# ── PRD §18: exhausted budget degrades, never crashes ───────────────────

async def test_exhausted_budget_marks_the_chair_partial_not_failed(pool):
    seed = await _seed(pool)
    budgets = await _exhausted_budget(seed["run_id"])
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN, budgets=budgets)

    result = await market.investigate(ctx)

    assert result.partial is True
    assert result.inserted == []


# ── PRD §7.3: a chair may introduce a new assumption mid-run ────────────

async def test_a_new_assumption_from_the_chair_is_returned_not_silently_dropped(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_NEW_ASSUMPTION)
    result = await market.investigate(ctx)

    assert result.discovered
    assert result.discovered[0].class_key == "saas.pain_severity"
    # And it must actually have been persisted (a real assumption row, not
    # just an in-memory record), since the evidence row's FK requires one.
    assert result.inserted
