"""Task 6.5: `GET /projects/{id}/versions`, `GET /projects/{id}/versions/{v}/diff`.

PRD §7.10: "The return visit UI shows the diff, not a new report." These
tests build two ledger versions directly against `LedgerVersionRepo` (the
same repository `jury.graph.nodes.version.write_version` itself calls) with
hand-built snapshots, rather than running the full economics/jury pipeline
the way `test_result_logging.py`'s `exp` fixture does -- the versions API
only reads `ledger_versions`, so it does not need a real economics run to
exercise it, and a hand-built snapshot lets this file pin the exact causal
chain PRD §7.10's worked example describes (`uncertain -> refuted`, verdict
`HUNG_JURY -> PIVOT`) without depending on fixture LLM output.
"""
import asyncio
import dataclasses
import os
import sys

import pytest
from psycopg_pool import AsyncConnectionPool

from jury.db.repositories import LedgerVersionRepo
from jury.engines.diff import DIFF_TYPES, compute_diff

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


@pytest.fixture
async def pool():
    """A raw, un-RLS'd pool -- for direct seeding, same pattern as
    `tests/api/test_result_logging.py`."""
    p = AsyncConnectionPool(DATABASE_URL, min_size=1, max_size=4, open=False)
    await p.open()
    try:
        yield p
    finally:
        await p.close()


async def _seed_run(pool, project_id: str, user_id: str) -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into runs (project_id, user_id, kind, status, thread_id) "
                "values (%s,%s,'initial','complete','versions-test-seed') returning id",
                (project_id, user_id))
            return str((await cur.fetchone())[0])


def _snapshot(status: str, verdict: str) -> dict:
    return {
        "assumptions": {
            "a1": {"statement": "pricing_wtp holds at Rs 499", "status": status,
                   "origin": "founder", "discovered_by": None, "criticality": "blocking"},
        },
        "evidence_counts": {},
        "conflicts": {},
        "parameters": {},
        "breakpoints": {},
        "confidence": {"total": 40.0, "coverage": 0.5, "mean_strength": 0.2,
                       "contradiction": 0.1, "open_critical": 0.3},
        "verdict": verdict,
    }


async def _write_two_versions(pool, project_id: str, run_id: str) -> tuple[int, int]:
    """Version 1: baseline (`uncertain`, `HUNG_JURY`). Version 2: the PRD
    §7.10 worked example's own transition -- `uncertain -> refuted`,
    verdict `HUNG_JURY -> PIVOT` -- so the diff route's causal-sentence
    assertion has real content to render."""
    repo = LedgerVersionRepo(pool)
    snap1 = _snapshot("uncertain", "HUNG_JURY")
    diff1 = [dataclasses.asdict(e) for e in compute_diff(None, snap1)]
    v1 = await repo.create_next_version(project_id, run_id, snap1, diff1)

    snap2 = _snapshot("refuted", "PIVOT")
    diff2 = [dataclasses.asdict(e) for e in compute_diff(snap1, snap2)]
    v2 = await repo.create_next_version(project_id, run_id, snap2, diff2)
    return v1, v2


@pytest.fixture
async def versioned_project(pool, project, user_a):
    run_id = await _seed_run(pool, project, user_a)
    await _write_two_versions(pool, project, run_id)
    return project


async def test_versions_list_is_newest_first(client, auth, versioned_project):
    versions = (await client.get(f"/projects/{versioned_project}/versions",
                                 headers=auth)).json()
    assert [v["version"] for v in versions] == sorted(
        [v["version"] for v in versions], reverse=True)


async def test_a_version_diff_returns_typed_entries(client, auth, versioned_project):
    diff = (await client.get(f"/projects/{versioned_project}/versions/2/diff",
                             headers=auth)).json()
    assert diff["entries"]
    assert all(d["type"] in DIFF_TYPES for d in diff["entries"])


async def test_the_diff_response_carries_the_causal_sentence(client, auth, versioned_project):
    body = (await client.get(f"/projects/{versioned_project}/versions/2/diff",
                             headers=auth)).json()
    assert body["causal_sentence"]
    assert "→" in body["causal_sentence"] or "->" in body["causal_sentence"]


async def test_version_one_diff_is_empty_not_an_error(client, auth, versioned_project):
    r = await client.get(f"/projects/{versioned_project}/versions/1/diff", headers=auth)
    assert r.status_code == 200 and r.json()["entries"] == []


async def test_a_nonexistent_version_returns_404(client, auth, versioned_project):
    r = await client.get(f"/projects/{versioned_project}/versions/99/diff", headers=auth)
    assert r.status_code == 404


async def test_another_users_versions_are_not_readable(client, auth_b, versioned_project):
    r = await client.get(f"/projects/{versioned_project}/versions", headers=auth_b)
    assert r.status_code in (403, 404)


async def test_another_users_diff_is_not_readable(client, auth_b, versioned_project):
    r = await client.get(f"/projects/{versioned_project}/versions/2/diff", headers=auth_b)
    assert r.status_code in (403, 404)


async def test_a_missing_token_is_rejected(client, versioned_project):
    r = await client.get(f"/projects/{versioned_project}/versions")
    assert r.status_code == 401
