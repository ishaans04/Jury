"""jury.chairs.dependencies / jury.chairs.base. Task 4.2. PRD §6.2.

Same demo pitch family as the other four chairs: BillWise, an invoicing
SaaS for Indian small businesses -- a payments-adjacent product with real
external dependencies (a payment aggregator, RBI/GST regulation, API rate
limits) to investigate.

The load-bearing tests here are the parametrised guard tests below, given
close to verbatim in the task brief: opinion-shaped "claims" (no named
dependency, no citable value) must be rejected; a claim naming a specific
dependency with a real numeric price/rate/licence property must be
accepted. See `jury.chairs.dependencies`'s module docstring for why the
guard is a purely structural variable+value/unit check rather than a
lexical entity-in-excerpt check -- the middle "citable" case below
(`stripe_api_price`) is the brief's own example proving why a lexical check
would be wrong: its excerpt names no vendor at all.
"""
import pytest

from jury.chairs import dependencies
from jury.chairs.base import ChairContext
from jury.retrieval.budgets import CHAIR_BUDGETS, BudgetLedger
from jury.retrieval.embed import Embedder
from jury.schemas.assumption import AssumptionRecord
from jury.schemas.enums import Chair
from jury.schemas.scope import Scope
from jury.tracing.events import MemoryTraceSink
from jury.transport.fixtures import FixtureFetchClient, FixtureLLMClient, FixtureSearchClient
from jury.transport.kv import MemoryKV
from jury.transport.protocols import Transports

ASSUMPTION_ID = "44444444-4444-4444-4444-444444444444"
PITCH_MAIN = "BillWise invoicing software for Indian small businesses"
DOMAIN_MAP: dict[str, int] = {}


async def _seed(pool, *, project_suffix: str = "") -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'deps-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, '{}') returning id",
                (user_id, "billwise-deps" + project_suffix))
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
                "values (%s, %s, %s, 'saas.dependency_risk', "
                "'Founders believe the required payment aggregator integration is "
                "straightforward', 'founder', 'high', 'uncertain', 'testable_now', "
                "null, null, null)",
                (ASSUMPTION_ID, project_id, run_id))

    return {"project_id": str(project_id), "run_id": str(run_id)}


def _transports() -> Transports:
    return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                      fetch=FixtureFetchClient(), kv=MemoryKV(), offline=True)


def _make_ctx(pool, seed: dict, *, pitch: str, budgets: BudgetLedger | None = None,
             trace=None) -> ChairContext:
    assumption = AssumptionRecord(
        id=ASSUMPTION_ID, statement="Founders believe the required payment "
        "aggregator integration is straightforward", class_key="saas.dependency_risk",
        origin="founder", criticality="high", uncertainty="uncertain",
        falsifiability="testable_now")
    return ChairContext(
        run_id=seed["run_id"], project_id=seed["project_id"], pitch=pitch,
        target_scope=Scope(geo="IN", segment="smb"), assumptions=[assumption],
        transports=_transports(),
        budgets=budgets or BudgetLedger(MemoryKV(), seed["run_id"]),
        domain_map=DOMAIN_MAP, trace=trace if trace is not None else MemoryTraceSink(),
        pool=pool, embedder=Embedder(MemoryKV()))


async def _exhausted_budget(run_id: str) -> BudgetLedger:
    ledger = BudgetLedger(MemoryKV(), run_id)
    for _ in range(CHAIR_BUDGETS[Chair.DEPENDENCIES]):
        await ledger.spend(Chair.DEPENDENCIES, "brave")
    return ledger


async def count_evidence(pool, project_id: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from evidence_items where project_id = %s",
                (project_id,))
            return (await cur.fetchone())[0]


# ── PRD §6.2: opinions are rejected -- the old persona wearing a new badge ─

@pytest.mark.parametrize("opinion", [
    "This will be hard to build.",
    "The architecture would need a queue, which adds complexity.",
    "Expect about six months of engineering effort.",
])
async def test_dependency_opinions_are_rejected(pool, opinion):
    seed = await _seed(pool)
    pitch = f"{PITCH_MAIN} [opinion: {opinion}]"
    ctx = _make_ctx(pool, seed, pitch=pitch)
    result = await dependencies.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert await count_evidence(pool, seed["project_id"]) == 0


# ── PRD §6.2: a named dependency with a citable property is accepted ────

@pytest.mark.parametrize("citable", [
    ("razorpay_licence", "Payment aggregators require RBI authorisation."),
    ("stripe_api_price", "Standard pricing is 2.9% plus 30 cents per charge."),
    ("api_rate_limit", "The endpoint is limited to 100 requests per minute."),
])
async def test_dependency_claims_naming_a_dependency_and_property_are_accepted(pool, citable):
    seed = await _seed(pool)
    label, _excerpt = citable
    pitch = f"{PITCH_MAIN} [citable: {label}]"
    ctx = _make_ctx(pool, seed, pitch=pitch)
    result = await dependencies.investigate(ctx)

    assert result.inserted


# ── A property needs a variable AND a value/unit, not just a variable ───

async def test_a_dependency_claim_must_carry_a_variable_or_unit(pool):
    """A 'citable property' means a property with a value, not a sentence:
    even a syntactically fine excerpt is rejected when the extractor
    supplies no variable and no value_num/value_min/unit at all."""
    seed = await _seed(pool)
    pitch = f"{PITCH_MAIN} [propertyless]"
    ctx = _make_ctx(pool, seed, pitch=pitch)
    result = await dependencies.investigate(ctx)

    assert result.inserted == []
    assert result.rejected


# ── grounding: a citable property must be the figure the page states ────

async def test_a_dependency_claim_with_an_ungrounded_value_is_rejected(pool):
    """The structural check alone (variable + value_num/value_min/unit
    populated) is not enough: a claim naming a real-looking dependency and
    property whose numeric value never actually appears on the cited page
    is still opinion dressed in structured fields, and must be rejected."""
    seed = await _seed(pool)
    pitch = f"{PITCH_MAIN} [ungrounded]"
    ctx = _make_ctx(pool, seed, pitch=pitch)
    result = await dependencies.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert await count_evidence(pool, seed["project_id"]) == 0


async def test_an_opinion_with_an_unrelated_number_is_still_rejected(pool):
    """Grounding checks the CLAIM's own value against the excerpt, not
    merely 'is there some digit anywhere in the excerpt' -- an excerpt that
    genuinely contains numbers (a duration, a year) must not ground an
    unrelated value_num the extractor attached to it."""
    seed = await _seed(pool)
    pitch = f"{PITCH_MAIN} [ungrounded-unrelated-number]"
    ctx = _make_ctx(pool, seed, pitch=pitch)
    result = await dependencies.investigate(ctx)

    assert result.inserted == []
    assert result.rejected
    assert await count_evidence(pool, seed["project_id"]) == 0


async def test_the_chair_emits_no_prose_only_typed_records(pool):
    seed = await _seed(pool)
    pitch = f"{PITCH_MAIN} [citable: api_rate_limit]"
    ctx = _make_ctx(pool, seed, pitch=pitch)
    result = await dependencies.investigate(ctx)
    assert all(isinstance(x, str) for x in result.inserted)


# ── PRD §18: exhausted budget degrades, never crashes ───────────────────

async def test_exhausted_budget_marks_the_chair_partial_not_failed(pool):
    seed = await _seed(pool)
    budgets = await _exhausted_budget(seed["run_id"])
    pitch = f"{PITCH_MAIN} [citable: api_rate_limit]"
    ctx = _make_ctx(pool, seed, pitch=pitch, budgets=budgets)

    result = await dependencies.investigate(ctx)

    assert result.partial is True
    assert result.inserted == []
