import asyncio
import os
import sys
from contextlib import asynccontextmanager

import psycopg
import pytest

# Same local Supabase Postgres as tests/conftest.py's `conn` fixture.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture(scope="session")
def event_loop_policy():
    """psycopg3's async connection refuses Windows' default
    ProactorEventLoop outright (it needs a selector-based loop to drive its
    libpq integration) -- without this override every test in this file
    fails at `AsyncConnection.connect` with `psycopg.InterfaceError` on
    Windows, before any repository code even runs. Overriding
    pytest-asyncio's own `event_loop_policy` fixture is the supported hook
    for this; non-Windows platforms keep asyncio's default policy."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


class _RollbackPool:
    """Test double for `psycopg_pool.AsyncConnectionPool`, holding exactly
    one connection for the lifetime of a test.

    This is the async counterpart of tests/conftest.py's `conn` fixture
    (manual transaction, unconditional rollback), adapted for repositories
    that are async and expect a pool-shaped object. It is deliberately NOT
    a real `AsyncConnectionPool`: a real pool's `.connection()` wraps the
    connection in `async with conn:`, which commits on a clean exit -- so
    every repository call would commit its own transaction immediately,
    the same way it correctly does in production, but that would leave
    rows behind in the shared local database after every test. Here,
    `.connection()` just re-yields the one held connection with no
    commit/rollback wrapping of its own, so every repository call in a
    test shares one outer transaction that this fixture rolls back at
    teardown -- nothing a test does is ever actually persisted.

    Repositories only ever call `pool.connection()`, so that is the only
    method this double needs to provide.
    """

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
