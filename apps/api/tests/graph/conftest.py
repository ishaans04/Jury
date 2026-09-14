"""Fixtures for the Task 4.3 graph integration tests.

Unlike every other DB-touching test package in this repo (tests/db,
tests/chairs), these tests do NOT use the single-held-connection
`_RollbackPool` double. Two things Task 4.3 must prove -- genuine concurrent
fan-out, and resumability from a brand-new process -- both require real,
independently-committed connections: `_RollbackPool` serialises every call
onto one connection inside one never-committed transaction, which would
make five "concurrent" chairs provably sequential (they'd all be fighting
over the same connection) and would make the checkpoint invisible to a
second `build_graph` instance (nothing was ever committed for it to see).
So this package uses a real `AsyncConnectionPool` and cleans up afterwards
with an explicit `DELETE` instead of a rollback.
"""
import asyncio
import os
import sys

import pytest
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture(scope="session")
def event_loop_policy():
    """See tests/db/conftest.py: psycopg3's async connection refuses
    Windows' default ProactorEventLoop outright."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


@pytest.fixture
async def real_pool():
    pool = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=8, open=False)
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()


async def seed_project_run(pool, *, target_scope: dict | None = None,
                           suffix: str = "") -> dict:
    """One auth user + one project + one run, committed for real (see the
    module docstring). Returns ids as strings plus the `thread_id` used for
    the checkpointer -- kept equal to `run_id` so cleanup only needs one id.
    """
    target_scope = target_scope or {"geo": "IN", "segment": "smb"}
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'graph-' || gen_random_uuid() || '@test.local', '', now(), now()) "
                "returning id")
            user_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into projects (user_id, name, target_scope) "
                "values (%s, %s, %s) returning id",
                (user_id, "graphco" + suffix, __import__("json").dumps(target_scope)))
            project_id = (await cur.fetchone())[0]

            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s, %s, 'initial', 'pending', %s) returning id",
                (project_id, user_id, "pending-thread" + suffix))
            run_id = (await cur.fetchone())[0]

            # thread_id == run_id (jury/graph/build.py); the placeholder
            # above only exists because `thread_id` is NOT NULL and run_id
            # is not known until after the insert.
            await cur.execute(
                "update runs set thread_id = %s where id = %s", (str(run_id), run_id))

    return {"user_id": str(user_id), "project_id": str(project_id), "run_id": str(run_id)}


async def cleanup_run(pool, run_id: str) -> None:
    """Deletes the project (cascades to runs/assumptions/evidence/conflicts/
    run_events, per the migrations) and this thread's checkpoint rows.
    `sources`/`source_chunks` are shared reference data, same as every other
    test package here -- left behind deliberately (see
    jury/db/repositories.py's SourceRepo docstring)."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "delete from projects where id = "
                "(select project_id from runs where id = %s)", (run_id,))
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                await cur.execute(f"delete from {table} where thread_id = %s", (run_id,))


async def count_evidence(pool, project_id: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from evidence_items where project_id = %s", (project_id,))
            return (await cur.fetchone())[0]


async def fetch_assumptions(pool, project_id: str) -> list[dict]:
    from jury.db.repositories import AssumptionRepo
    return await AssumptionRepo(pool).list_for_project(project_id)


async def fetch_run_events(pool, run_id: str) -> list[dict]:
    async with pool.connection() as conn:
        from psycopg.rows import dict_row
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "select * from run_events where run_id = %s order by ts, id", (run_id,))
            return await cur.fetchall()


async def fetch_conflicts(pool, project_id: str) -> list[dict]:
    from jury.db.repositories import ConflictRepo
    return await ConflictRepo(pool).list_for_project(project_id)


async def fetch_evidence_rows(pool, project_id: str) -> list[dict]:
    from jury.db.repositories import EvidenceRepo
    return await EvidenceRepo(pool).list_for_project(project_id)
