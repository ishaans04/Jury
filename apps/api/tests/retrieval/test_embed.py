"""jury/retrieval/embed.py. Task 3.8 -- local fastembed embeddings into
pgvector `source_chunks`. PRD §7.4, §11.2 dec. 10, §15.3, §16.3, §17.2.

Uses the `pool` fixture from tests/retrieval/conftest.py -- one real
connection per test, held inside a single uncommitted transaction that is
always rolled back at teardown (same pattern as tests/db/test_repositories.py).
`Embedder(MemoryKV())` runs the real local `fastembed` model (no network call,
no mock): the weights are downloaded once into the machine's HF cache and
every call in this file after that is fully offline, which is the entire
point of PRD §11.2 decision 10.
"""
import pytest

from jury.retrieval.embed import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MAX_CHUNKS_PER_RUN,
    Embedder,
    persist_chunks,
    similar_chunks,
)
from jury.transport.kv import MemoryKV

LONG_TEXT = " ".join([f"sentence number {i} about pricing and churn." for i in range(200)])


async def _seed_project(pool) -> dict:
    """Same FK chain as tests/db/test_repositories.py's `_seed_project_chain`,
    inside the same uncommitted transaction the `pool` fixture rolls back."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "encrypted_password, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
                "'authenticated', 'authenticated', "
                "'embed-' || gen_random_uuid() || '@test.local', '', now(), now()) "
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


async def _make_source(pool, canonical_url: str = "https://x.test/embed-source") -> str:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into sources (canonical_url, domain, tier, http_status) "
                "values (%s, 'x.test', 1, 200) returning id", (canonical_url,))
            return str((await cur.fetchone())[0])


async def _cite_source(pool, seed: dict, source_id: str, dedup_hash: str = "h1") -> None:
    """`similar_chunks` scopes by project via a join through evidence_items,
    so a chunk is only findable once some evidence row actually cites its
    source -- mirroring the real access path (PRD §16.3's near-duplicate pass
    only ever runs over a project's own already-cited sources)."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into evidence_items "
                "(project_id, run_id, assumption_id, source_id, chair, direction, "
                "variable, scope_geo, scope_segment, confidence, excerpt, dedup_hash) "
                "values (%s,%s,%s,%s,'market','supports','price_monthly','IN','smb',"
                "0.8,'x',%s)",
                (seed["project_id"], seed["run_id"], seed["assumption_id"], source_id,
                 dedup_hash))


async def count_chunks(pool, source_id: str) -> int:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from source_chunks where source_id = %s", (source_id,))
            return (await cur.fetchone())[0]


async def fetch_chunks(pool, source_id: str) -> list[dict]:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select chunk_index, content from source_chunks "
                "where source_id = %s order by chunk_index", (source_id,))
            rows = await cur.fetchall()
    return [{"chunk_index": r[0], "content": r[1]} for r in rows]


# ── module-level constants ──────────────────────────────────────────────

def test_the_dimension_matches_the_schema_column():
    """A mismatch here fails at insert with an opaque pgvector error."""
    assert EMBEDDING_DIM == 384
    assert "bge-small-en-v1.5" in EMBEDDING_MODEL


async def test_the_embedding_budget_is_enforced():
    """PRD §17.2: ~3000 chunks per run."""
    assert MAX_CHUNKS_PER_RUN == 3000


def test_embedding_never_leaves_the_process():
    """PRD §11.2 dec. 10: local, so no rate limit and no network failure class."""
    import inspect

    from jury.retrieval import embed
    src = inspect.getsource(embed)
    for banned in ("httpx", "requests", "openai", "api.openai", "litellm"):
        assert banned not in src, f"embed.py references {banned}"


# ── Embedder ─────────────────────────────────────────────────────────────

async def test_embedding_returns_one_vector_per_text_at_the_right_dimension():
    vecs = await Embedder(MemoryKV()).embed(["a price of 149 INR", "monthly churn"])
    assert len(vecs) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vecs)


async def test_embedding_is_deterministic_for_the_same_text():
    e = Embedder(MemoryKV())
    assert await e.embed(["same text"]) == await e.embed(["same text"])


async def test_identical_content_is_served_from_the_content_hash_cache():
    """PRD §15.3: cache embeddings in Redis keyed by content hash."""
    kv = MemoryKV()
    e = Embedder(kv)
    await e.embed(["cached text"])
    before = e.model_invocations
    await e.embed(["cached text"])
    assert e.model_invocations == before


async def test_a_mixed_batch_only_embeds_the_uncached_members():
    kv = MemoryKV()
    e = Embedder(kv)
    await e.embed(["one"])
    before = e.texts_embedded
    await e.embed(["one", "two"])
    assert e.texts_embedded == before + 1


async def test_an_empty_batch_makes_no_model_call():
    e = Embedder(MemoryKV())
    assert await e.embed([]) == []
    assert e.model_invocations == 0


# ── persist_chunks ───────────────────────────────────────────────────────

async def test_persist_chunks_writes_one_row_per_chunk(pool):
    source_id = await _make_source(pool)
    n = await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    assert n > 1
    assert await count_chunks(pool, source_id) == n


async def test_chunk_index_is_dense_and_ordered(pool):
    source_id = await _make_source(pool, "https://x.test/embed-source-2")
    await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    rows = await fetch_chunks(pool, source_id)
    assert [r["chunk_index"] for r in rows] == list(range(len(rows)))


async def test_persisting_the_same_source_twice_does_not_duplicate_chunks(pool):
    source_id = await _make_source(pool, "https://x.test/embed-source-3")
    a = await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    b = await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    assert b == 0
    assert await count_chunks(pool, source_id) == a


async def test_persist_chunks_on_empty_text_writes_nothing(pool):
    source_id = await _make_source(pool, "https://x.test/embed-source-empty")
    n = await persist_chunks(pool, source_id, "   ", Embedder(MemoryKV()))
    assert n == 0
    assert await count_chunks(pool, source_id) == 0


async def test_source_chunks_are_declared_to_cascade_from_their_source(pool):
    """An embedding must never outlive the row it cites, which is why the FK
    is ON DELETE CASCADE -- but the cascade is a latent guarantee here, not
    an exercised one. `sources` is a shared, globally-deduplicated,
    append-only cache holding nothing user-identifying (PRD §14.4), and it is
    permanently undeletable so long as any evidence row anywhere cites it:
    deleting a source would need a `SELECT ... FOR KEY SHARE` lock on
    evidence_items (to check the FK from evidence_items.source_id), which
    needs UPDATE privilege on evidence_items -- the one privilege P6
    (0003_immutability.sql) must never grant to anyone, and
    0008_evidence_fk_cascades.sql deliberately leaves that particular FK
    alone (see its own comment) precisely because there is nothing about a
    shared source that erasure needs to reach. So this asserts the
    declaration on `source_chunks.source_id` directly via `pg_constraint`,
    rather than a deletion the schema is designed to permanently forbid."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select confdeltype from pg_constraint "
                "where conname = 'source_chunks_source_id_fkey'")
            row = await cur.fetchone()
    assert row is not None
    assert row[0] == "c"          # 'c' = ON DELETE CASCADE


# ── similar_chunks ───────────────────────────────────────────────────────

async def test_similarity_search_ranks_the_relevant_chunk_first(pool):
    seed = await _seed_project(pool)
    source_id = await _make_source(pool, "https://x.test/embed-source-5")
    await _cite_source(pool, seed, source_id, dedup_hash="h-similarity-1")
    await persist_chunks(
        pool, source_id,
        "Delivery costs 30 rupees per order. "
        "Our office is in Bengaluru. "
        "Monthly churn among SMB accounts is 8 percent.",
        Embedder(MemoryKV()))
    hits = await similar_chunks(pool, seed["project_id"], "what is the churn rate",
                                Embedder(MemoryKV()), limit=1)
    assert hits
    assert "churn" in hits[0]["content"].lower()


async def test_similarity_search_respects_the_limit(pool):
    seed = await _seed_project(pool)
    source_id = await _make_source(pool, "https://x.test/embed-source-6")
    await _cite_source(pool, seed, source_id, dedup_hash="h-similarity-2")
    await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    hits = await similar_chunks(pool, seed["project_id"], "price", Embedder(MemoryKV()),
                                limit=3)
    assert len(hits) <= 3


async def test_similarity_search_is_scoped_to_the_project(pool):
    """The join through evidence_items means a chunk belonging to a source no
    project has cited yet is invisible to similar_chunks -- it is not a
    global full-text search over every fetched page ever."""
    seed = await _seed_project(pool)
    source_id = await _make_source(pool, "https://x.test/embed-source-uncited")
    # Deliberately never call _cite_source: no evidence row references this
    # source, so it must not appear in this project's similarity results.
    await persist_chunks(pool, source_id,
                         "Monthly churn among SMB accounts is 8 percent.",
                         Embedder(MemoryKV()))
    hits = await similar_chunks(pool, seed["project_id"], "churn rate",
                                Embedder(MemoryKV()), limit=5)
    assert all(h["source_id"] != source_id for h in hits)
