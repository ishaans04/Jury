"""Ledger snapshot builder. Task 6.1. PRD §9, §16.8.

`build_snapshot` assembles a complete, self-contained `Snapshot` dict from the
live ledger for one project+run -- the shape `jury.engines.diff.compute_diff`
consumes. It is stored in `ledger_versions.snapshot` (an immutable jsonb
column, see 0010_ledger_versions_immutable.sql), so it must carry text, not
just foreign keys, and must be plain-JSON-serialisable (no Decimal, no UUID
object) at the boundary.

Uses the same `pool` fixture as tests/db/test_repositories.py -- one held
connection, one outer uncommitted transaction, rolled back at teardown.
"""
import json

from jury.db.repositories import (
    AssumptionRepo,
    ConflictRepo,
    EvidenceRepo,
    ModelRunRepo,
    SourceRepo,
    VerdictRepo,
)
from jury.db.snapshot import build_snapshot
from jury.engines.diff import compute_diff


async def _seed_full_ledger(pool) -> dict:
    """A project/run with one of everything build_snapshot reads: an
    assumption, a supporting evidence item (tier 1, chair market), a
    conflict, a model_run (parameters + breakpoints) and a verdict."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'snap-' || gen_random_uuid() || '@test.local', '', now(), now()) "
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

    project_id, run_id = str(project_id), str(run_id)

    assumption_ids = await AssumptionRepo(pool).create_many(project_id, run_id, [
        {"class_key": "marketplace.demand_exists", "statement": "demand exists",
         "criticality": "blocking", "uncertainty": "uncertain",
         "falsifiability": "testable_now"},
    ])
    assumption_id = assumption_ids[0]

    source_id = await SourceRepo(pool).upsert(
        "https://x.test/pricing", "x.test", 1, "Pricing", 200)

    from jury.retrieval.verify import VerifiedClaim
    from jury.schemas.claim import ClaimRecord

    claim = ClaimRecord.model_validate({
        "assumption_id": assumption_id, "direction": "supports",
        "variable": "price_monthly", "value_num": 149.0, "unit": "INR_per_month",
        "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.8,
        "source_url": "https://x.test/pricing", "source_tier": 1,
        "excerpt": "Starter plan is 149 INR/mo", "chair": "market",
    })
    verified = VerifiedClaim(claim=claim, tier=1, canonical_url="https://x.test/pricing",
                             extracted_text="Starter plan is 149 INR/mo", http_status=200)
    await EvidenceRepo(pool).insert_verified(
        project_id=project_id, run_id=run_id, assumption_id=assumption_id,
        source_id=source_id, verified=verified)

    conflict_id = await ConflictRepo(pool).create(
        project_id, run_id, assumption_id, "chair_vs_chair",
        {"chair": "market", "value": 149}, {"chair": "customer", "value": 99},
        "R2", "high")
    await ConflictRepo(pool).add_position_delta(
        conflict_id, "customer", "99 INR", "149 INR", "conceded to fresher evidence")
    await ConflictRepo(pool).resolve(conflict_id, "resolved", "customer conceded")

    await ModelRunRepo(pool).create(
        project_id, run_id, "saas_v1",
        {"price_monthly": {"value": 149.0, "unit": "INR_per_month",
                           "provenance": "evidence_backed", "source_id": source_id,
                           "assumption_id": assumption_id}},
        {"ltv": 1000.0}, [{"variable": "price_monthly", "threshold": 50.0,
                          "direction": "below", "unit": "INR_per_month",
                          "output": "viable", "sentence": "if price drops below 50"}],
        {"price_monthly": 0.8}, True)

    await VerdictRepo(pool).create(
        run_id, project_id, "PROCEED", 62.5,
        {"coverage": 0.5, "mean_strength": 0.7, "contradiction": 0.1, "open_critical": 0.0},
        None, [], "sufficient evidence for a blocking assumption")

    return {"project_id": project_id, "run_id": run_id}


async def test_the_snapshot_shape_matches_what_compute_diff_consumes(pool):
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    assert set(snap) == {"assumptions", "evidence_counts", "conflicts",
                         "parameters", "breakpoints", "confidence", "verdict"}
    assert compute_diff(None, snap) == []          # must not raise


async def test_evidence_counts_are_nested_by_chair_then_tier(pool):
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    assert snap["evidence_counts"]["market"]["1"] >= 1


async def test_assumptions_carry_statement_status_and_origin(pool):
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    a = next(iter(snap["assumptions"].values()))
    assert {"statement", "status", "origin"} <= set(a)


async def test_the_snapshot_is_json_serialisable(pool):
    seeded = await _seed_full_ledger(pool)
    json.dumps(await build_snapshot(pool, seeded["project_id"], seeded["run_id"]))


async def test_the_snapshot_is_self_contained_and_carries_no_foreign_keys_only(pool):
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    a = next(iter(snap["assumptions"].values()))
    assert a["statement"]                          # text, not just an id


async def test_confidence_carries_the_total_and_all_four_components(pool):
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    assert set(snap["confidence"]) == {"total", "coverage", "mean_strength",
                                       "contradiction", "open_critical"}


async def test_two_builds_of_an_unchanged_ledger_are_identical(pool):
    seeded = await _seed_full_ledger(pool)
    a = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    b = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    assert a == b


async def test_breakpoints_are_nested_by_variable_not_a_bare_list(pool):
    """compute_diff's `_breakpoint_entries` iterates `curr.items()` -- a bare
    list of breakpoint dicts (the raw `model_runs.breakpoints` shape) would
    raise AttributeError the first time compute_diff actually ran against a
    changed breakpoint."""
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    assert snap["breakpoints"]["price_monthly"]["threshold"] == 50.0


async def test_verdict_and_parameters_come_from_this_run(pool):
    seeded = await _seed_full_ledger(pool)
    snap = await build_snapshot(pool, seeded["project_id"], seeded["run_id"])
    assert snap["verdict"] == "PROCEED"
    assert snap["parameters"]["price_monthly"]["provenance"] == "evidence_backed"
