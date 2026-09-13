"""Local embeddings. PRD §11.2 decision 10 and §15.3.

Groq serves no embeddings API, so local fastembed is load-bearing rather than
optional. It is also the highest-volume call in the system, and running it
locally removes an entire class of rate-limit and network failure.

The model is loaded once per process and warmed on container start; weights are
baked into the image at build time (Phase 7).
"""
import hashlib
import json

from fastembed import TextEmbedding

from jury.retrieval.extract import chunk
from jury.transport.protocols import KV

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384                  # must match source_chunks.embedding vector(384)
MAX_CHUNKS_PER_RUN = 3000            # PRD §17.2

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    """Module-level singleton: loading the weights per call would dominate runtime."""
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _model


def warm() -> None:
    """Called at container start so the first real request does not pay the load."""
    list(_get_model().embed(["warm"]))


def _content_key(text: str) -> str:
    return "emb:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class Embedder:
    """Content-hash cached embedder. Counters exist so tests can assert on cache
    behaviour without reaching into the model."""

    def __init__(self, kv: KV) -> None:
        self._kv = kv
        self.model_invocations = 0
        self.texts_embedded = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        out: list[list[float] | None] = [None] * len(texts)
        misses: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            cached = await self._kv.get(_content_key(text))
            if cached is not None:
                out[i] = json.loads(cached)
            else:
                misses.append((i, text))

        if misses:
            self.model_invocations += 1
            self.texts_embedded += len(misses)
            vectors = list(_get_model().embed([t for _, t in misses]))
            for (i, text), vec in zip(misses, vectors, strict=True):
                as_list = [float(x) for x in vec]
                out[i] = as_list
                await self._kv.set(_content_key(text), json.dumps(as_list), 604_800)

        return [v for v in out if v is not None]


async def persist_chunks(pool, source_id: str, text: str,
                         embedder: Embedder) -> int:
    """Chunk, embed and store. Returns rows written; 0 if already present.

    Idempotent on source_id so a re-run does not duplicate chunks. The
    existence check and the write are deliberately two separate connections
    (not one held transaction): embedding thousands of chunks is slow, and a
    long-held transaction across that work would tie up a pool connection
    for the whole embedding pass for no benefit -- a source is only ever
    chunked once in practice, so the narrow race this opens (two concurrent
    callers for the same brand-new source both passing the empty check) costs
    at most one harmless duplicate embedding pass, never a correctness bug a
    caller would observe.
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from source_chunks where source_id = %s",
                (source_id,))
            existing = await cur.fetchone()
        if existing and existing[0] > 0:
            return 0

    pieces = chunk(text)[:MAX_CHUNKS_PER_RUN]
    if not pieces:
        return 0
    vectors = await embedder.embed(pieces)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into source_chunks (source_id, chunk_index, content, embedding) "
                "values (%s, %s, %s, %s::vector)",
                [(source_id, i, piece, str(vec))
                 for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True))])
    return len(pieces)


async def similar_chunks(pool, project_id: str, query: str, embedder: Embedder,
                         limit: int = 5) -> list[dict]:
    """Cosine nearest neighbours over this project's fetched sources.

    Supports PRD §16.3's optional pass: catching near-duplicate statements of
    the same variable under different names. Scoped to `project_id` via a
    join through `evidence_items` -- a source with chunks but no evidence row
    yet citing it (in this project) is invisible here, the same way `sources`
    being globally shared never leaks one project's fetched pages into
    another project's search results.
    """
    vec = (await embedder.embed([query]))[0]
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # GROUP BY every selected column, not DISTINCT: a source cited by
            # more than one evidence row in the same project would otherwise
            # fan out through the join and return the same chunk once per
            # citing evidence row. GROUP BY (unlike SELECT DISTINCT) allows
            # ORDER BY to reference an expression over a grouped column
            # directly, which is what the nearest-neighbour ordering needs.
            await cur.execute(
                "select sc.id, sc.content, sc.source_id, sc.embedding, "
                "       1 - (sc.embedding <=> %s::vector) as similarity "
                "from source_chunks sc "
                "join evidence_items e on e.source_id = sc.source_id "
                "where e.project_id = %s "
                "group by sc.id, sc.content, sc.source_id, sc.embedding "
                "order by sc.embedding <=> %s::vector "
                "limit %s",
                (str(vec), project_id, str(vec), limit))
            rows = await cur.fetchall()
    return [{"id": str(r[0]), "content": r[1], "source_id": str(r[2]), "similarity": r[4]}
            for r in rows]
