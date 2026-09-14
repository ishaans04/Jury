"""SSE for transient cross-exam tokens. Task 5.6. PRD §10.2.

"SSE is retained for exactly one thing -- token-level streaming of
cross-examination prose, which is transient and not persisted as
evidence." Everything else the UI needs comes from Supabase Realtime on
the ledger tables; a chair "speaks" only by writing a persisted row. This
module's whole job is to prove the SSE route does the one thing it's for
(streams, requires auth) and nothing it isn't (no evidence writes, no
route for evidence, dropping the connection can't fail a run).
"""
import psycopg

from tests.api.conftest import DATABASE_URL


async def _count_evidence(project_id: str) -> int:
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from evidence_items where project_id = %s",
                (project_id,))
            return (await cur.fetchone())[0]
    finally:
        await conn.close()


async def test_the_stream_emits_an_event_stream(client, auth, run):
    async with client.stream("GET", f"/runs/{run}/cross-exam/stream",
                             headers=auth) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")


async def test_streamed_tokens_are_never_persisted_as_evidence(client, auth, run, project):
    """The one thing SSE does must not leak into the ledger."""
    before = await _count_evidence(project)

    async with client.stream("GET", f"/runs/{run}/cross-exam/stream",
                             headers=auth) as r:
        assert r.status_code == 200
        async for _chunk in r.aiter_bytes():
            break  # one chunk is enough to prove the route is live

    assert await _count_evidence(project) == before


async def test_the_stream_requires_auth(client, run):
    r = await client.get(f"/runs/{run}/cross-exam/stream")
    assert r.status_code == 401


async def test_a_dropped_stream_does_not_fail_the_run(client, auth, run):
    """PRD §10.2's whole argument against SSE for state: it loses on
    reconnect, so nothing important may depend on it staying open."""
    async with client.stream("GET", f"/runs/{run}/cross-exam/stream",
                             headers=auth) as r:
        assert r.status_code == 200
        # Drop the connection immediately without draining it.

    got = await client.get(f"/runs/{run}", headers=auth)
    assert got.status_code == 200
    assert got.json()["status"] != "failed"


def _all_paths(app) -> set[str]:
    """FastAPI wraps each `include_router` call in an `_IncludedRouter`
    whose own `.routes` is empty -- the real `Route` objects (and their
    `.path`) live on `.original_router.routes`, one level down."""
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        original = getattr(route, "original_router", None)
        if original is not None:
            paths |= {r.path for r in original.routes if getattr(r, "path", None)}
    return paths


async def test_there_is_no_sse_route_for_evidence(app):
    paths = _all_paths(app)
    assert not any("evidence" in p and "stream" in p for p in paths)


async def test_there_is_no_other_stream_route_besides_cross_exam(app):
    stream_paths = {p for p in _all_paths(app) if "stream" in p}
    assert stream_paths == {"/runs/{run_id}/cross-exam/stream"}
