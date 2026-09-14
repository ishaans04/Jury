"""The only module that opens a database connection pool."""
import json
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool

from jury.settings import Settings

_pool: AsyncConnectionPool | None = None


def get_pool(settings: Settings) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(settings.database_url, min_size=1, max_size=8,
                                    open=False)
    return _pool


async def open_pool(settings: Settings) -> AsyncConnectionPool:
    pool = get_pool(settings)
    await pool.open()
    return pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


class _UserScopedPool:
    """Pool-shaped wrapper around one connection whose role/JWT claim is
    already switched to `authenticated` for a specific user (Task 4.4, PRD
    §13: "the orchestrator validates it and writes under the user's ID so
    RLS applies to service-side writes too").

    Every repository in `jury.db.repositories` only ever calls
    `pool.connection()`, so handing one of these to a repository makes every
    write it does go through Postgres' RLS policies as that user, exactly
    the way `tests/test_rls_write_paths.py` probes it by hand with `set
    local role authenticated` + `set_config('request.jwt.claims', ...)`.
    `set local` scopes to the current transaction, so the switch reverts on
    its own when the transaction ends -- nothing here needs to reset it.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self._conn


@asynccontextmanager
async def user_scoped_connection(pool: AsyncConnectionPool, user_id: str):
    """Checks out one real connection and switches it to `authenticated` for
    `user_id`, wrapped so it satisfies every repository's `pool.connection()`
    call. Commits (or rolls back on an exception) and returns the connection
    to the pool on exit -- unlike the test suite's `_RollbackPool`, this is
    the production path and must actually persist."""
    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("set local role authenticated")
                await cur.execute(
                    "select set_config('request.jwt.claims', %s, true)",
                    (json.dumps({"sub": str(user_id), "role": "authenticated"}),))
            yield _UserScopedPool(conn)
