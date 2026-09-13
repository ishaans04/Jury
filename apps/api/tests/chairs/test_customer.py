"""jury.chairs.customer / jury.chairs.base. Task 4.2.

Same demo pitch as Market (Task 3.7): an invoicing SaaS for Indian small
businesses. Customer's job here is to find real users' pain, willingness-
to-pay and feature-gap language rather than competitor pricing pages -- a
different corpus (HN Algolia, keyless) against the same pitch.

PRD §18 / spec §3.1: Customer must work with zero credentials because HN
Algolia needs none. `jury.chairs.customer` drives the shared pipeline with
only `hn` -- Reddit is never called from this module in this batch (see
customer.py's module docstring) -- so "no reddit credentials" is true by
construction rather than by a runtime probe; `offline_no_reddit` below is
therefore the same transports as every other scenario, kept as its own
fixture name to document the requirement the test is protecting.
"""
from jury.chairs import customer
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

ASSUMPTION_ID = "22222222-2222-2222-2222-222222222222"

PITCH_MAIN = "BillWise invoicing software for Indian small businesses"
PITCH_FABRICATED = "QuickBill demo pitch for the customer P1 rejection test"
PITCH_NEW_ASSUMPTION = "LedgerPal demo pitch for the customer discovered-assumption test"

# Mirrors the tier-4 forum rows of db/seed/002_domain_tiers.sql -- this test
# suite constructs its own dict (rather than reading the seed file) the same
# way tests/retrieval/test_tiers.py does.
DOMAIN_MAP: dict[str, int] = {"news.ycombinator.com": 4, "reddit.com": 4}


async def _seed(pool, *, project_suffix: str = "") -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'customer-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{}') returning id",
                (user_id, "billwise-customer" + project_suffix))
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
    for _ in range(CHAIR_BUDGETS[Chair.CUSTOMER]):
        await ledger.spend(Chair.CUSTOMER, "hn")
    return ledger


async def count_evidence(pool, project_id: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from evidence_items where project_id = %s",
                (project_id,))
            return (await cur.fetchone())[0]


async def fetch_evidence(pool, evidence_id: str) -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select chair, source_id from evidence_items where id = %s",
                (evidence_id,))
            chair, source_id = await cur.fetchone()
            await cur.execute(
                "select canonical_url, tier from sources where id = %s", (source_id,))
            source_url, tier = await cur.fetchone()
    return {"chair": chair, "source_url": source_url, "tier": tier}


# ── PRD §18: no credentials at all ──────────────────────────────────────

async def test_customer_works_with_no_reddit_credentials(pool):
    """HN Algolia is keyless, so Customer degrades rather than dies (spec
    §3.1). This chair's only pass in this batch runs on `hn`, so no
    credential of any kind is ever consulted."""
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await customer.investigate(ctx)

    assert result.partial is False
    assert result.inserted


async def test_the_chair_emits_no_prose_only_typed_records(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await customer.investigate(ctx)
    assert all(isinstance(x, str) for x in result.inserted)


# ── PRD §16.2 / spec §26.4: forum evidence at tier 4, discounted for WTP ──

async def test_forum_evidence_lands_at_tier4(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await customer.investigate(ctx)

    rows = [await fetch_evidence(pool, i) for i in result.inserted]
    forum = [r for r in rows if "reddit.com" in r["source_url"]
             or "ycombinator" in r["source_url"]]
    assert forum
    assert all(r["tier"] == 4 for r in forum)


async def test_wtp_claims_from_forums_are_discounted_in_scoring():
    """Spec §26.4 wired end to end: a tier-4 price claim weighs 0.15, not
    0.30. Pure scoring-engine assertion -- the chair only needs to land
    forum evidence at tier 4 (test above); the discount itself already
    lives in jury.engines.scoring and is exercised directly here."""
    from jury.engines.scoring import tier_weight
    assert tier_weight(4, "price_monthly") == 0.15


# ── P1: rejection leaves zero rows ──────────────────────────────────────

async def test_a_rejected_claim_never_reaches_the_database(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_FABRICATED)
    result = await customer.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert isinstance(result.rejected[0], Rejection)
    assert await count_evidence(pool, seed["project_id"]) == 0


# ── PRD §18: exhausted budget degrades, never crashes ───────────────────

async def test_exhausted_budget_marks_the_chair_partial_not_failed(pool):
    seed = await _seed(pool)
    budgets = await _exhausted_budget(seed["run_id"])
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN, budgets=budgets)

    result = await customer.investigate(ctx)

    assert result.partial is True
    assert result.inserted == []


# ── PRD §7.3: a chair may introduce a new assumption mid-run ────────────

async def test_a_new_assumption_from_the_chair_is_returned_not_silently_dropped(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_NEW_ASSUMPTION)
    result = await customer.investigate(ctx)

    assert result.discovered
    assert result.discovered[0].class_key == "saas.retention"
    assert result.inserted
