"""Fix round 1 (code review): the fetch layer must never let its own
dependencies -- httpx's redirect handling, the KV cache backend -- escape as
an exception. PRD §18 requires degrading to a rejected source, not crashing.
"""
import httpx
import respx

from jury.retrieval.fetch import LiveFetchClient
from jury.settings import Settings
from jury.transport.kv import MemoryKV


def client(kv=None):
    return LiveFetchClient(Settings(_env_file=None), kv or MemoryKV())


# ── CRITICAL 1: httpx.InvalidURL is not an httpx.HTTPError ─────────────────
@respx.mock
async def test_a_malformed_redirect_location_is_a_rejected_source_not_a_crash():
    """httpx eagerly builds the redirect request (for `.next_request`/
    `.history`) even with follow_redirects=False, and raises InvalidURL when
    the Location header doesn't parse as a URL -- before our own per-hop SSRF
    recheck ever gets a chance to run. A hostile or merely misconfigured
    origin controls this header."""
    respx.get("https://evil.test/r").mock(
        return_value=httpx.Response(302, headers={"location": "javascript:alert(1)"}))
    r = await client().fetch("https://evil.test/r")
    assert r.status >= 400
    assert r.text == ""


# ── CRITICAL 2: the cache is an optimisation, never load-bearing ───────────
class RaisingKV:
    """Simulates a transient cache-backend failure, e.g. UpstashKV.get's
    raise_for_status() on a hiccupping REST endpoint."""

    async def get(self, key):
        raise RuntimeError("kv backend unavailable")

    async def set(self, key, value, ttl_s):
        raise RuntimeError("kv backend unavailable")


@respx.mock
async def test_a_kv_get_failure_degrades_to_an_uncached_live_fetch():
    respx.get("https://x.test/p").mock(
        return_value=httpx.Response(200, html="<main><p>Real content, long enough.</p></main>"))
    r = await client(RaisingKV()).fetch("https://x.test/p")
    assert r.status == 200
    assert "Real content" in r.text


@respx.mock
async def test_a_kv_set_failure_does_not_prevent_the_result_being_returned():
    respx.get("https://x.test/q").mock(
        return_value=httpx.Response(200, html="<main><p>Other content, long enough.</p></main>"))
    r = await client(RaisingKV()).fetch("https://x.test/q")
    assert r.status == 200
    assert "Other content" in r.text
