import asyncio
import os
import sys
from contextlib import asynccontextmanager

import psycopg
import pytest

# Same local Supabase Postgres as tests/db/conftest.py's `pool` fixture. Only
# test_embed.py in this package needs a real connection (persist_chunks and
# similar_chunks write to and read from source_chunks); every other test in
# tests/retrieval is a pure in-memory unit test that never touches this
# fixture, so duplicating it here (rather than promoting it to the root
# tests/conftest.py) keeps the database dependency scoped to the tests that
# actually need it.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture(scope="session")
def event_loop_policy():
    """See tests/db/conftest.py for why this override exists: psycopg3's
    async connection refuses Windows' default ProactorEventLoop outright."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


class _RollbackPool:
    """Same test double as tests/db/conftest.py's -- one held connection,
    no commit/rollback wrapping of its own, so every call in a test shares
    one outer transaction the fixture rolls back at teardown."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self._conn


@pytest.fixture
async def pool():
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        yield _RollbackPool(conn)
    finally:
        await conn.rollback()
        await conn.close()
