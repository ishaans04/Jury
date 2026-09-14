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
    switched to `authenticated` for a specific user on EVERY checkout (Task
    4.4, PRD §13: "the orchestrator validates it and writes under the
    user's ID so RLS applies to service-side writes too").

    Every repository in `jury.db.repositories` only ever calls
    `pool.connection()` once per method and expects that call's work to be
    durably committed when the `async with` block exits -- the same
    contract a real `AsyncConnectionPool.connection()` gives (it wraps the
    checkout in `async with conn:`, which commits on a clean exit). This
    class's `.connection()` therefore opens and commits its OWN transaction
    on every call, rather than holding one long-lived transaction across
    every repository call a request happens to make.

    That per-call commit is deliberate, not merely a style choice: a route
    that schedules a `BackgroundTasks` job (`jury.api.routers.runs.start_run`
    creating a run row, then handing its id to a background `run_initial`)
    needs that row to be visible to a DIFFERENT connection the moment the
    background task starts -- and FastAPI does not guarantee a request-scoped
    dependency's own `async with`/generator cleanup (where a single
    outer-transaction design would commit) runs before Starlette fires the
    response's background tasks. A commit that happens only at request
    teardown can race a background task that starts before then, causing
    exactly the `ForeignKeyViolation` this design avoids: the run row must
    already be committed by the time each individual repository call
    returns, not merely by the time the whole request finishes.

    `set local role`/`set_config(..., true)` (the `true` = "local", scoped
    to the current transaction) are therefore re-applied at the start of
    every checkout rather than once -- they would otherwise revert the
    moment the previous checkout's transaction committed.
    """

    def __init__(self, conn, user_id: str) -> None:
        self._conn = conn
        self._user_id = user_id

    @asynccontextmanager
    async def connection(self):
        async with self._conn.transaction():
            async with self._conn.cursor() as cur:
                await cur.execute("set local role authenticated")
                await cur.execute(
                    "select set_config('request.jwt.claims', %s, true)",
                    (json.dumps({"sub": str(self._user_id), "role": "authenticated"}),))
            yield self._conn


@asynccontextmanager
async def user_scoped_connection(pool: AsyncConnectionPool, user_id: str):
    """Checks out one real connection for the lifetime of a request and
    wraps it so every repository call against it runs (and commits) as
    `authenticated` for `user_id` -- see `_UserScopedPool` for why each
    call gets its own transaction rather than one shared one."""
    async with pool.connection() as conn:
        yield _UserScopedPool(conn, user_id)
