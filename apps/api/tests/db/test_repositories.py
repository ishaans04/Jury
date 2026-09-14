"""Repositories: the only module permitted to write SQL (spec §6).

Uses the `pool` fixture from tests/db/conftest.py -- one real connection per
test, held inside a single uncommitted transaction that is always rolled
back at teardown, the async counterpart of tests/conftest.py's `conn`
fixture. No row created by any test here is ever actually persisted.
"""
from jury.db.repositories import (
    AssumptionRepo,
    ConflictRepo,
    EvidenceRepo,
    ExperimentRepo,
    LedgerVersionRepo,
    ModelRunRepo,
    SourceRepo,
    VerdictRepo,
)
from jury.engines.dedup import dedup_hash
from jury.retrieval.verify import VerifiedClaim
from jury.schemas.claim import ClaimRecord
from jury.schemas.scope import Scope


def _claim(**kw) -> ClaimRecord:
    base = {
        "assumption_id": "will-be-overwritten", "direction": "supports",
        "variable": "price_monthly", "value_num": 149.0, "unit": "INR_per_month",
        "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.8,
        "source_url": "https://x.test/pricing", "source_tier": 1,
        "excerpt": "Starter plan is priced at 149 INR per month", "chair": "market",
    }
    return ClaimRecord.model_validate(base | kw)


def _verified(**kw) -> VerifiedClaim:
    return VerifiedClaim(
        claim=kw.pop("claim", _claim()),
        tier=kw.pop("tier", 1),
        canonical_url=kw.pop("canonical_url", "https://x.test/pricing"),
        extracted_text=kw.pop("extracted_text", "Starter plan is priced at 149 INR per month"),
        http_status=kw.pop("http_status", 200),
    )


async def _seed_project_chain(pool) -> dict:
    """The FK chain an evidence/assumption row needs: one auth user, one
    project, one run, one assumption. Mirrors
    tests/test_db_constraints.py's `_seed_minimal`, adapted to the async
    pool double -- everything here lives inside the same uncommitted
    transaction the `pool` fixture rolls back."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'repo-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, 'p', '{}') returning id", (user_id,))
            project_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', 't1') returning id",
                (project_id, user_id))
            run_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into assumptions (project_id, run_id, statement, origin, "
                "criticality, uncertainty, falsifiability) "
                "values (%s, %s, 's', 'founder', 'blocking', 'unknown', 'testable_now') "
                "returning id", (project_id, run_id))
            assumption_id = (await cur.fetchone())[0]

    return {"user_id": str(user_id), "project_id": str(project_id),
            "run_id": str(run_id), "assumption_id": str(assumption_id)}


# ── P6: EvidenceRepo has no mutation surface ────────────────────────────

def test_evidence_repo_exposes_no_mutation_methods():
    """P6: corrections supersede, never update. The capability must be ABSENT
    from the API, not merely unused -- so this asserts the exact public
    surface rather than denylisting verbs someone happened to think of. A
    denylist of ("update", "delete", "upsert", "save", "set_confidence")
    misses `set_status`, `mark_superseded`, `revise`, or any other verb not
    already on the list; an allowlist of the whole surface cannot be
    defeated by picking a different name."""
    public = {n for n in dir(EvidenceRepo) if not n.startswith("_")}
    # Task 5.2 added `get` -- a single-row read (needed to load a conflict's
    # evidence-type side by id for cross-examination), not a mutation; P6's
    # allowlist is about the absence of update/delete/upsert-shaped methods,
    # not the absence of reads. Task 6.1 added `list_for_project_with_tier`
    # -- the ledger snapshot's project-wide (not run-scoped) tier-joined read.
    assert public == {"insert_verified", "list_for_project",
                      "list_for_conflict_engine", "get",
                      "list_for_project_with_tier"}, public


# ── EvidenceRepo.insert_verified ────────────────────────────────────────

async def test_duplicate_dedup_hash_returns_none_rather_than_raising(pool):
    """P10 at the application boundary: the second insert is a no-op, not a
    crash. Two chairs finding the same pricing page is normal."""
    fixtures = await _seed_project_chain(pool)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values ('https://x.test/pricing', 'x.test', 1, 200) returning id")
            source_id = str((await cur.fetchone())[0])

    repo = EvidenceRepo(pool)
    args = dict(project_id=fixtures["project_id"], run_id=fixtures["run_id"],
               assumption_id=fixtures["assumption_id"], source_id=source_id,
               verified=_verified())

    first = await repo.insert_verified(**args)
    assert first is not None

    second = await repo.insert_verified(**args)
    assert second is None

    # And the connection must still be usable afterwards -- a UniqueViolation
    # must not leave the transaction aborted for the rest of the test.
    rows = await repo.list_for_project(fixtures["project_id"])
    assert len(rows) == 1
    assert str(rows[0]["id"]) == first


async def test_insert_verified_computes_the_dedup_hash_itself(pool):
    """The caller has no parameter through which to supply a hash; a wrong
    or mismatched hash would defeat P10 (a false collision, or a missed
    one). `insert_verified`'s signature does not even accept one."""
    import inspect
    sig = inspect.signature(EvidenceRepo.insert_verified)
    assert "dedup_hash" not in sig.parameters

    fixtures = await _seed_project_chain(pool)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values ('https://x.test/pricing', 'x.test', 1, 200) returning id")
            source_id = str((await cur.fetchone())[0])

    verified = _verified()
    repo = EvidenceRepo(pool)
    evidence_id = await repo.insert_verified(
        project_id=fixtures["project_id"], run_id=fixtures["run_id"],
        assumption_id=fixtures["assumption_id"], source_id=source_id,
        verified=verified)

    rows = await repo.list_for_project(fixtures["project_id"])
    row = next(r for r in rows if str(r["id"]) == evidence_id)
    expected = dedup_hash(verified.canonical_url, verified.claim.variable, verified.claim.scope)
    assert row["dedup_hash"] == expected


async def test_insert_verified_persists_scope_and_direction(pool):
    fixtures = await _seed_project_chain(pool)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values ('https://x.test/pricing', 'x.test', 1, 200) returning id")
            source_id = str((await cur.fetchone())[0])

    verified = _verified(claim=_claim(direction="refutes", scope=Scope(geo="US", segment="enterprise")))
    repo = EvidenceRepo(pool)
    evidence_id = await repo.insert_verified(
        project_id=fixtures["project_id"], run_id=fixtures["run_id"],
        assumption_id=fixtures["assumption_id"], source_id=source_id,
        verified=verified)

    rows = await repo.list_for_project(fixtures["project_id"])
    row = next(r for r in rows if str(r["id"]) == evidence_id)
    assert row["direction"] == "refutes"
    assert row["scope_geo"] == "US"
    assert row["scope_segment"] == "enterprise"


# ── SourceRepo ───────────────────────────────────────────────────────────

async def test_source_upsert_is_idempotent_on_canonical_url(pool):
    repo = SourceRepo(pool)
    a = await repo.upsert("https://x.test/p", "x.test", 1, "T", 200)
    b = await repo.upsert("https://x.test/p", "x.test", 1, "T", 200)
    assert a == b


async def test_source_upsert_does_not_overwrite_existing_metadata(pool):
    """`sources` has deliberately no UPDATE policy (0006_sources_insert_policy.sql):
    on a globally-shared table nobody individually owns, an UPDATE grant
    would let any authenticated user rewrite another user's cached source
    metadata. `upsert` is therefore `ON CONFLICT DO NOTHING`, not
    `DO UPDATE` -- the first insert's metadata wins and a second call for
    the same canonical_url is a pure no-op that changes nothing."""
    repo = SourceRepo(pool)
    first = await repo.upsert("https://x.test/q", "x.test", 3, "Old Title", 200)
    second = await repo.upsert("https://x.test/q", "x.test", 1, "New Title", 201)
    assert first == second
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select tier, title, http_status from sources where id = %s",
                              (second,))
            tier, title, status = await cur.fetchone()
    assert (tier, title, status) == (3, "Old Title", 200)


# ── AssumptionRepo ───────────────────────────────────────────────────────

async def test_assumption_create_many_and_list(pool):
    fixtures = await _seed_project_chain(pool)
    repo = AssumptionRepo(pool)
    ids = await repo.create_many(fixtures["project_id"], fixtures["run_id"], [
        {"class_key": "marketplace.demand_exists", "statement": "founders believe x", "criticality": "high",
         "uncertainty": "uncertain", "falsifiability": "testable_now"},
        {"class_key": "marketplace.supply_liquidity", "statement": "founders believe y", "criticality": "medium",
         "uncertainty": "unknown", "falsifiability": "untestable",
         "asserted_variable": "churn", "asserted_value": 0.05},
    ])
    assert len(ids) == 2
    rows = await repo.list_for_project(fixtures["project_id"])
    # the one seeded by _seed_project_chain plus the two just created
    assert len(rows) == 3
    assert {str(r["id"]) for r in rows} >= set(ids)


async def test_assumption_create_discovered_requires_a_chair(pool):
    fixtures = await _seed_project_chain(pool)
    repo = AssumptionRepo(pool)
    new_id = await repo.create_discovered(
        fixtures["project_id"], fixtures["run_id"], "customer", "marketplace.take_rate_tolerance",
        "customers churn after month 2", "high", "uncertain", "testable_costly")
    rows = await repo.list_for_project(fixtures["project_id"])
    row = next(r for r in rows if str(r["id"]) == new_id)
    assert row["origin"] == "discovered"
    assert row["discovered_by"] == "customer"


async def test_assumption_update_status_and_strength(pool):
    fixtures = await _seed_project_chain(pool)
    repo = AssumptionRepo(pool)
    await repo.update_status_and_strength(fixtures["assumption_id"], "supported", 0.7)
    rows = await repo.list_for_project(fixtures["project_id"])
    row = next(r for r in rows if str(r["id"]) == fixtures["assumption_id"])
    assert row["status"] == "supported"
    assert float(row["strength"]) == 0.7


# ── ConflictRepo ─────────────────────────────────────────────────────────

async def test_conflict_create_resolve_and_position_delta(pool):
    fixtures = await _seed_project_chain(pool)
    repo = ConflictRepo(pool)
    conflict_id = await repo.create(
        fixtures["project_id"], fixtures["run_id"], fixtures["assumption_id"],
        "chair_vs_chair", {"chair": "market", "value": 149}, {"chair": "customer", "value": 99},
        "R2", "high")
    delta_id = await repo.add_position_delta(conflict_id, "market", "149 INR", "99 INR",
                                             "new pricing page found")
    assert delta_id

    rows = await repo.list_for_project(fixtures["project_id"])
    assert rows[0]["status"] == "open"

    await repo.resolve(conflict_id, "resolved", "market conceded to fresher evidence")
    rows = await repo.list_for_project(fixtures["project_id"])
    assert rows[0]["status"] == "resolved"
    assert rows[0]["resolution"] == "market conceded to fresher evidence"


# ── ModelRunRepo ─────────────────────────────────────────────────────────

async def test_model_run_create_and_list(pool):
    fixtures = await _seed_project_chain(pool)
    repo = ModelRunRepo(pool)
    run_row_id = await repo.create(
        fixtures["project_id"], fixtures["run_id"], "subscription_saas",
        {"price": 149}, {"ltv": 1000}, {"price": [100, 200]}, {"price": 0.8}, True)
    rows = await repo.list_for_project(fixtures["project_id"])
    assert str(rows[0]["id"]) == run_row_id
    assert rows[0]["viable"] is True
    assert rows[0]["parameters"] == {"price": 149}


# ── ExperimentRepo ───────────────────────────────────────────────────────

async def test_experiment_create_list_and_log_result(pool):
    fixtures = await _seed_project_chain(pool)
    repo = ExperimentRepo(pool)
    exp_id = await repo.create(
        fixtures["project_id"], fixtures["assumption_id"], "price_monthly",
        "fake_door", "run a landing page test for two weeks",
        "kill if CTR < 2%", {"metric": "ctr", "comparator": "<", "threshold": 0.02},
        500.0, 14, 1)
    rows = await repo.list_for_project(fixtures["project_id"])
    assert str(rows[0]["id"]) == exp_id
    assert rows[0]["status"] == "proposed"

    await repo.log_result(exp_id, "failed", 0.01, "CTR came in under threshold")
    rows = await repo.list_for_project(fixtures["project_id"])
    assert rows[0]["status"] == "failed"
    assert float(rows[0]["result_value"]) == 0.01
    assert rows[0]["logged_at"] is not None


# ── VerdictRepo ──────────────────────────────────────────────────────────

async def test_verdict_create_and_list(pool):
    fixtures = await _seed_project_chain(pool)
    repo = VerdictRepo(pool)
    verdict_id = await repo.create(
        fixtures["run_id"], fixtures["project_id"], "PIVOT", 42.0,
        {"coverage": 0.5}, "low_coverage", {"friction": "high"}, "insufficient evidence")
    rows = await repo.list_for_project(fixtures["project_id"])
    assert str(rows[0]["id"]) == verdict_id
    assert rows[0]["decision"] == "PIVOT"


# ── LedgerVersionRepo ────────────────────────────────────────────────────

async def test_ledger_version_create_and_latest(pool):
    fixtures = await _seed_project_chain(pool)
    repo = LedgerVersionRepo(pool)
    await repo.create(fixtures["project_id"], fixtures["run_id"], 1, {"v": 1}, {"d": 1})
    await repo.create(fixtures["project_id"], fixtures["run_id"], 2, {"v": 2}, {"d": 2})
    latest = await repo.latest_for_project(fixtures["project_id"])
    assert latest["version"] == 2
    assert latest["snapshot"] == {"v": 2}
