"""Key-value transport: Upstash REST when configured, in-process otherwise.

Used for the search cache, fetch dedup, embedding cache, per-provider token
buckets and node idempotency keys (PRD §10, §17.2, §17.3).
"""
import time

import httpx


class MemoryKV:
    """In-process fallback. Correct for a single container and for tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._buckets: dict[str, list[float]] = {}

    async def get(self, key: str) -> str | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        value, expires = hit
        if expires and expires < time.monotonic():
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl_s if ttl_s else 0.0)

    async def incr_bucket(self, key: str, limit: int, window_s: int) -> bool:
        """Sliding-window token bucket. False means the budget is spent."""
        now = time.monotonic()
        window = self._buckets.setdefault(key, [])
        window[:] = [t for t in window if now - t < window_s]
        if len(window) >= limit:
            return False
        window.append(now)
        return True


class UpstashKV:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _cmd(self, *args: str | int) -> dict:
        path = "/".join(str(a) for a in args)
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{self._url}/{path}", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def get(self, key: str) -> str | None:
        return (await self._cmd("get", key)).get("result")

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._cmd("set", key, value, "ex", ttl_s)

    async def incr_bucket(self, key: str, limit: int, window_s: int) -> bool:
        count = (await self._cmd("incr", key)).get("result", 0)
        if count == 1:
            await self._cmd("expire", key, window_s)
        return int(count) <= limit
