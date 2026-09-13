"""Fix round 1 (code review), Important finding: caching a non-2xx result for
the full 24h dedup window is only correct for a "permanent-ish" 4xx (403
paywalled, 404 gone). Doing the same for a 429 (rate limit) or 5xx (server
outage) records a purely transient hiccup as a day-long absence of evidence,
which is exactly the failure PRD §18 exists to prevent. 429/5xx are therefore
never cached at all, so the very next verification attempt always re-fetches.
"""
import httpx
import respx

from jury.retrieval.fetch import LiveFetchClient
from jury.settings import Settings
from jury.transport.kv import MemoryKV


def client(kv=None):
    return LiveFetchClient(Settings(_env_file=None), kv or MemoryKV())


@respx.mock
async def test_a_503_is_re_fetched_on_the_next_call_but_a_404_is_not():
    route_503 = respx.get("https://flaky.test/a").mock(return_value=httpx.Response(503))
    route_404 = respx.get("https://gone.test/a").mock(return_value=httpx.Response(404))
    c = client(MemoryKV())

    await c.fetch("https://flaky.test/a")
    await c.fetch("https://flaky.test/a")
    assert route_503.call_count == 2, "a 5xx must never be cached"

    await c.fetch("https://gone.test/a")
    await c.fetch("https://gone.test/a")
    assert route_404.call_count == 1, "a 4xx is cached for the full dedup window"


@respx.mock
async def test_a_429_is_also_never_cached():
    route = respx.get("https://ratelimited.test/a").mock(return_value=httpx.Response(429))
    c = client()
    await c.fetch("https://ratelimited.test/a")
    await c.fetch("https://ratelimited.test/a")
    assert route.call_count == 2


@respx.mock
async def test_a_500_is_never_cached():
    route = respx.get("https://down.test/a").mock(return_value=httpx.Response(500))
    c = client()
    await c.fetch("https://down.test/a")
    await c.fetch("https://down.test/a")
    assert route.call_count == 2
