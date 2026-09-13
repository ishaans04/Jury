"""The only module that opens a database connection pool."""
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
