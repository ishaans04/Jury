"""jury.graph.nodes.version. Task 6.2. PRD §9, §16.8.

Version numbering (`select ... for update` against the project row, retried
once on `UniqueViolation`) and the immutability migration both need genuine,
independently-committed connections to prove anything -- a single held
connection cannot demonstrate two writers racing each other, and a rolled-
back transaction never leaves a row for a second, real connection to see it
try (and fail) to mutate. So this module uses `real_pool`
(tests/graph/conftest.py) throughout, not the rollback `pool` double most of
this package's other node tests use, and cleans up explicitly with
`cleanup_run` instead of relying on a rollback.
"""
import asyncio
import os

import psycopg
import pytest

from jury.db.repositories import AssumptionRepo, LedgerVersionRepo
from jury.graph.nodes.version import VersionRepos, write_version

from .conftest import cleanup_run, seed_project_run

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


def _repos(pool) -> VersionRepos:
    return VersionRepos(ledger_version=LedgerVersionRepo(pool))


async def _fetch_version(pool, project_id: str, version: int) -> dict | None:
    async with pool.connection() as conn:
        from psycopg.rows import dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "select * from ledger_versions where project_id = %s and version = %s",
                (project_id, version))
            return await cur.fetchone()


def _execute_as(role: str, stmt: str, params: tuple = ()) -> None:
    """A genuinely separate, synchronous connection -- switches role for one
    statement inside its own transaction, always rolled back afterwards
    regardless of outcome (mirrors tests/test_db_constraints.py's pattern of
    connecting as the role under test rather than as a superuser)."""
    conn = psycopg.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(f"set local role {role}")
            cur.execute(stmt, params)
    finally:
        conn.rollback()
        conn.close()


async def _add_assumption(pool, project_id: str, run_id: str) -> None:
    """Mutates the ledger between two `write_version` calls so the second
    call's snapshot actually differs from the first, giving `compute_diff`
    something real to find."""
    await AssumptionRepo(pool).create_many(project_id, run_id, [
        {"class_key": "marketplace.demand_exists", "statement": "a new assumption",
         "criticality": "high", "uncertainty": "uncertain",
         "falsifiability": "testable_now"},
    ])


async def test_the_first_run_writes_version_one_with_an_empty_diff(real_pool):
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        out = await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)
        assert out == {"version": 1, "diff": []}
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_the_second_run_writes_version_two_with_a_computed_diff(real_pool):
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        first = await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)
        assert first["version"] == 1

        await _add_assumption(real_pool, seeded["project_id"], seeded["run_id"])

        second = await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)
        assert second["version"] == 2
        assert second["diff"]
        assert any(e["type"] == "assumption_discovered" for e in second["diff"])
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_versions_are_dense_and_monotonic(real_pool):
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        for expected in (1, 2, 3):
            out = await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)
            assert out["version"] == expected
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_an_existing_version_is_never_overwritten(real_pool):
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)
        first = await _fetch_version(real_pool, seeded["project_id"], 1)

        await _add_assumption(real_pool, seeded["project_id"], seeded["run_id"])
        await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)

        still_first = await _fetch_version(real_pool, seeded["project_id"], 1)
        assert still_first == first
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_the_snapshot_and_the_diff_are_both_persisted(real_pool):
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        out = await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)
        row = await _fetch_version(real_pool, seeded["project_id"], out["version"])
        assert row["snapshot"]
        assert row["diff"] is not None
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_a_concurrent_second_writer_does_not_produce_a_duplicate_version(real_pool):
    """`unique (project_id, version)` alone would let two racing writers both
    compute `max(version)+1` from the same stale read and then have one of
    them fail with UniqueViolation; `create_next_version`'s `for update` lock
    on the project row is what actually prevents the race, not just detects
    it after the fact."""
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        results = await asyncio.gather(
            write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None),
            write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None),
            return_exceptions=True)
        versions = [r["version"] for r in results if isinstance(r, dict)]
        assert not any(isinstance(r, Exception) for r in results), results
        assert len(versions) == 2
        assert len(set(versions)) == len(versions)
        assert set(versions) == {1, 2}
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_ledger_versions_are_immutable_at_the_database_level(real_pool):
    """P6 extended to ledger_versions (supabase/migrations/
    0010_ledger_versions_immutable.sql): a unique constraint on
    (project_id, version) stops a duplicate version NUMBER; it does nothing
    to stop an UPDATE that rewrites an existing version's snapshot or diff,
    or a TRUNCATE that wipes the whole table. This is expected to be RED
    until that migration is applied (`supabase db reset`) -- see the batch
    report."""
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)

        with pytest.raises(psycopg.Error):
            _execute_as("service_role", "update ledger_versions set diff = '[]'::jsonb "
                       "where project_id = %s", (seeded["project_id"],))
        with pytest.raises(psycopg.Error):
            _execute_as("service_role", "delete from ledger_versions where project_id = %s",
                       (seeded["project_id"],))
        with pytest.raises(psycopg.Error):
            _execute_as("service_role", "truncate table ledger_versions")
    finally:
        await cleanup_run(real_pool, seeded["run_id"])


async def test_ledger_versions_project_delete_still_cascades(real_pool):
    """The immutability migration must not block project erasure -- the same
    lesson evidence_items needed 0007/0008/0009 to relearn (batch-N/S
    audits). A project's own delete (never a direct DELETE against
    ledger_versions -- projects.id -> ledger_versions.project_id on delete
    cascade) must still remove that project's ledger_versions rows. Expected
    RED until 0010 is applied, same as the immutability test above."""
    seeded = await seed_project_run(real_pool)
    try:
        state = {"project_id": seeded["project_id"], "run_id": seeded["run_id"]}
        await write_version(state, pool=real_pool, repos=_repos(real_pool), trace=None)

        async with real_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("delete from projects where id = %s",
                                  (seeded["project_id"],))

        remaining = await _fetch_version(real_pool, seeded["project_id"], 1)
        assert remaining is None
    finally:
        # The project (and its run) are already gone; this only mops up the
        # checkpoint tables cleanup_run also clears, which project deletion
        # does not cascade into.
        await cleanup_run(real_pool, seeded["run_id"])
