"""jury.chairs.precedent / jury.chairs.base. Task 4.2. PRD §16.7, §25.

Same demo pitch family as Market/Customer (Task 3.7/4.2): BillWise, an
invoicing SaaS for Indian small businesses. Precedent's job is a different
corpus again -- outcome discovery (brave) plus a Wayback CDX death-
verification pass -- against a market (GST invoicing) that genuinely has
dead competitors (PRD §22's "crowded space where real corpses exist").
"""
from jury.chairs import precedent
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

ASSUMPTION_ID = "33333333-3333-3333-3333-333333333333"

PITCH_MAIN = "BillWise invoicing software for Indian small businesses"
PITCH_UNFETCHABLE = "GhostBiller unfetchable-precedent demo pitch"
PITCH_EMPTY = "Nothing Like This Exists Anywhere demo pitch for precedent"

# Mirrors db/seed/002_domain_tiers.sql's tier-1 archive/store row plus a
# couple of tier-3 journalism domains this suite's fixtures cite.
DOMAIN_MAP: dict[str, int] = {"web.archive.org": 1, "techcrunch.com": 3,
                              "yourstory.com": 3}


async def _seed(pool, *, project_suffix: str = "") -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'precedent-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{}') returning id",
                (user_id, "billwise-precedent" + project_suffix))
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
                "values (%s, %s, %s, 'saas.incumbency', "
                "'Founders believe no incumbent has already won this market', "
                "'founder', 'high', 'uncertain', 'testable_now', "
                "null, null, null)",
                (ASSUMPTION_ID, project_id, run_id))

    return {"project_id": str(project_id), "run_id": str(run_id)}


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


def _make_ctx(pool, seed: dict, *, pitch: str, budgets: BudgetLedger | None = None,
             trace=None) -> ChairContext:
    assumption = AssumptionRecord(
        id=ASSUMPTION_ID, statement="Founders believe no incumbent has already won "
        "this market", class_key="saas.incumbency", origin="founder",
        criticality="high", uncertainty="uncertain", falsifiability="testable_now")
    return ChairContext(
        run_id=seed["run_id"], project_id=seed["project_id"], pitch=pitch,
        target_scope=Scope(geo="IN", segment="smb"), assumptions=[assumption],
        transports=_transports(),
        budgets=budgets or BudgetLedger(MemoryKV(), seed["run_id"]),
        domain_map=DOMAIN_MAP, trace=trace if trace is not None else MemoryTraceSink(),
        pool=pool, embedder=Embedder(MemoryKV()))


async def _exhausted_budget(run_id: str) -> BudgetLedger:
    ledger = BudgetLedger(MemoryKV(), run_id)
    for _ in range(CHAIR_BUDGETS[Chair.PRECEDENT]):
        await ledger.spend(Chair.PRECEDENT, "brave")
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
                "select chair, direction, source_id from evidence_items where id = %s",
                (evidence_id,))
            chair, direction, source_id = await cur.fetchone()
            await cur.execute(
                "select canonical_url, tier from sources where id = %s", (source_id,))
            source_url, tier = await cur.fetchone()
    return {"chair": chair, "direction": direction, "source_url": source_url, "tier": tier}


# ── PRD §16.7: a claim about a company whose source cannot be fetched ────

async def test_a_precedent_claim_without_a_fetchable_source_is_rejected(pool):
    """A claim is rejected at insert unless it carries a resolvable source
    URL that was actually fetched and returned a 2xx -- proven here for a
    fabricated company specifically: the archive.org snapshot URL the LLM
    names has no fetch fixture at all, so FixtureFetchClient's documented-
    absence behaviour (404) is exactly what verify_claim must reject on."""
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_UNFETCHABLE)
    result = await precedent.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert isinstance(result.rejected[0], Rejection)
    assert await count_evidence(pool, seed["project_id"]) == 0


# ── PRD §16.7: Wayback snapshot is a tier-1 citable death date ──────────

async def test_wayback_snapshot_becomes_a_tier1_citable_death_date(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await precedent.investigate(ctx)

    rows = [await fetch_evidence(pool, i) for i in result.inserted]
    archived = [r for r in rows if "web.archive.org" in r["source_url"]]
    assert archived
    assert all(r["tier"] == 1 for r in archived)


# ── PRD §16.7/§25: no precedent found is a finding, not an error ───────

async def test_no_precedent_found_is_recorded_as_a_finding_not_an_error(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_EMPTY)
    result = await precedent.investigate(ctx)

    assert result.inserted == []
    assert result.partial is False
    assert result.no_precedent_found is True


# ── PRD §16.7: widen to outcomes, not only failures ─────────────────────

async def test_precedent_widens_to_successful_outcomes_not_only_failures(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await precedent.investigate(ctx)

    outcomes = {(await fetch_evidence(pool, i))["direction"] for i in result.inserted}
    assert outcomes <= {"supports", "refutes"}
    # The fixtures for PITCH_MAIN deliberately carry one of each so this
    # proves the chair actually emits both, not merely that the type is
    # restricted to the enum.
    assert outcomes == {"supports", "refutes"}


async def test_the_chair_emits_no_prose_only_typed_records(pool):
    seed = await _seed(pool)
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN)
    result = await precedent.investigate(ctx)
    assert all(isinstance(x, str) for x in result.inserted)


# ── PRD §18: exhausted budget degrades, never crashes ───────────────────

async def test_exhausted_budget_marks_the_chair_partial_not_failed(pool):
    seed = await _seed(pool)
    budgets = await _exhausted_budget(seed["run_id"])
    ctx = _make_ctx(pool, seed, pitch=PITCH_MAIN, budgets=budgets)

    result = await precedent.investigate(ctx)

    assert result.partial is True
    assert result.inserted == []
    assert result.no_precedent_found is False
