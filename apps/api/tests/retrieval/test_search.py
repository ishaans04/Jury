"""Per-provider search routing. PRD §16.1, §18.

No real network call may reach any provider in this file: every httpx-based
provider is exercised through respx, and the one provider that does not speak
httpx (playstore, via the `google-play-scraper` library) is exercised by
monkeypatching that library's own `search` function instead -- see the
module docstring in jury/retrieval/search.py for why respx cannot reach it.
"""
import hashlib

import httpx
import pytest
import respx

from jury.retrieval.search import LiveSearchClient
from jury.settings import Settings
from jury.transport.kv import MemoryKV
from jury.transport.protocols import SearchHit

pytestmark = pytest.mark.network


def client(kv=None, **overrides):
    return LiveSearchClient(Settings(_env_file=None, **overrides), kv or MemoryKV())


# ── keyed providers: absent credential degrades to [], never an exception ──

async def test_brave_returns_empty_list_without_a_key_and_makes_no_request():
    assert await client().search(provider="brave", query="q") == []


async def test_tavily_returns_empty_list_without_a_key():
    assert await client().search(provider="tavily", query="q") == []


async def test_exa_returns_empty_list_without_a_key():
    assert await client().search(provider="exa", query="q") == []


async def test_reddit_returns_empty_list_without_credentials():
    assert await client().search(provider="reddit", query="q") == []


# ── brave ───────────────────────────────────────────────────────────────

@respx.mock
async def test_brave_returns_hits_when_key_present():
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": [
            {"url": "https://x.test/p", "title": "T", "description": "D"}]}}))
    hits = await client(brave_api_key="k").search(provider="brave", query="q")
    assert hits == [SearchHit(url="https://x.test/p", title="T", snippet="D")]


@respx.mock
async def test_brave_sends_the_subscription_token_header():
    route = respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": []}}))
    await client(brave_api_key="secret-key").search(provider="brave", query="q")
    assert route.calls.last.request.headers["X-Subscription-Token"] == "secret-key"


@respx.mock
async def test_a_provider_error_degrades_to_empty_list_not_an_exception():
    """A 500 from the provider must never propagate -- PRD §18: degrade to
    less evidence, the same contract fetch.py and verify.py already hold."""
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(500))
    assert await client(brave_api_key="k").search(provider="brave", query="q") == []


# ── tavily ──────────────────────────────────────────────────────────────

@respx.mock
async def test_tavily_posts_query_and_parses_results():
    respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(200, json={"results": [
            {"url": "https://y.test/a", "title": "Y", "content": "C"}]}))
    hits = await client(tavily_api_key="k").search(provider="tavily", query="q")
    assert hits == [SearchHit(url="https://y.test/a", title="Y", snippet="C")]


# ── exa (find-similar) ──────────────────────────────────────────────────

@respx.mock
async def test_exa_find_similar_sends_the_seed_url_and_the_api_key_header():
    route = respx.post("https://api.exa.ai/findSimilar").mock(
        return_value=httpx.Response(200, json={"results": [
            {"url": "https://z.test/a", "title": "Z", "text": "snip"}]}))
    hits = await client(exa_api_key="k").search(provider="exa", query="https://seed.test/pricing")
    assert route.calls.last.request.headers["x-api-key"] == "k"
    assert hits == [SearchHit(url="https://z.test/a", title="Z", snippet="snip")]


# ── hn (keyless) ────────────────────────────────────────────────────────

@respx.mock
async def test_hn_needs_no_key():
    """Spec §3.1: HN Algolia is keyless and unlimited."""
    respx.get("https://hn.algolia.com/api/v1/search").mock(
        return_value=httpx.Response(200, json={"hits": [
            {"url": "https://hn.test/x", "title": "H", "objectID": "1"}]}))
    hits = await client().search(provider="hn", query="q")
    assert hits == [SearchHit(url="https://hn.test/x", title="H", snippet="")]


@respx.mock
async def test_hn_falls_back_to_the_item_link_when_url_is_null():
    """Ask HN / Show HN posts carry no external url."""
    respx.get("https://hn.algolia.com/api/v1/search").mock(
        return_value=httpx.Response(200, json={"hits": [
            {"url": None, "title": "Ask HN: X", "objectID": "42", "story_text": "body"}]}))
    hits = await client().search(provider="hn", query="q")
    assert hits[0].url == "https://news.ycombinator.com/item?id=42"
    assert hits[0].snippet == "body"


# ── reddit (oauth client-credentials) ───────────────────────────────────

@respx.mock
async def test_reddit_uses_client_credentials_then_searches():
    token_route = respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok"}))
    search_route = respx.get("https://oauth.reddit.com/search").mock(
        return_value=httpx.Response(200, json={"data": {"children": [
            {"data": {"permalink": "/r/x/1", "title": "R", "selftext": "body"}}]}}))
    hits = await client(reddit_client_id="id", reddit_client_secret="s").search(
        provider="reddit", query="q")
    assert token_route.called
    assert search_route.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert hits[0].url == "https://reddit.com/r/x/1"


# ── wayback (keyless, CDX) ──────────────────────────────────────────────

@respx.mock
async def test_wayback_needs_no_key():
    """PRD §16.7: 'the single highest-value retrieval trick in the product'."""
    respx.get("https://web.archive.org/cdx/search/cdx").mock(
        return_value=httpx.Response(200, json=[
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            ["com,x)/pricing", "20200101000000", "https://x.test/pricing",
             "text/html", "200", "abc", "100"],
        ]))
    hits = await client().search(provider="wayback", query="https://x.test/pricing")
    assert hits == [SearchHit(
        url="https://web.archive.org/web/20200101000000/https://x.test/pricing",
        title="https://x.test/pricing", snippet="archived 20200101000000")]


@respx.mock
async def test_wayback_with_no_snapshots_returns_empty_list():
    respx.get("https://web.archive.org/cdx/search/cdx").mock(
        return_value=httpx.Response(200, json=[]))
    assert await client().search(provider="wayback", query="q") == []


# ── playstore (google-play-scraper, no key, not httpx-based) ────────────

async def test_playstore_needs_no_key_and_uses_the_scraper_library(monkeypatch):
    def fake_search(query, n_hits=30, **kw):
        assert query == "q"
        return [{"appId": "com.x.app", "title": "X App", "description": "desc"}]
    monkeypatch.setattr("google_play_scraper.search", fake_search)
    hits = await client().search(provider="playstore", query="q")
    assert hits == [SearchHit(url="https://play.google.com/store/apps/details?id=com.x.app",
                              title="X App", snippet="desc")]


async def test_playstore_scraper_failure_degrades_to_empty_list(monkeypatch):
    def raising_search(*a, **kw):
        raise RuntimeError("play store scrape blew up")
    monkeypatch.setattr("google_play_scraper.search", raising_search)
    assert await client().search(provider="playstore", query="q") == []


# ── unrouted provider (documented brief gap: see search.py docstring) ───

async def test_an_unrouted_provider_returns_empty_list_never_raises():
    """producthunt is in CHAIR_PROVIDERS[PRECEDENT] (budgets.py) but has no
    dedicated LiveSearchClient method in this batch -- flagged in the
    report rather than silently invented. It must still degrade to []."""
    assert await client().search(provider="producthunt", query="q") == []


# ── caching: provider + query hash, 24h ──────────────────────────────────

@respx.mock
async def test_results_are_cached_by_provider_and_query_hash_for_24h():
    route = respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": [
            {"url": "https://x.test/p", "title": "T", "description": "D"}]}}))
    kv = MemoryKV()
    c = client(kv, brave_api_key="k")
    first = await c.search(provider="brave", query="same query")
    second = await c.search(provider="brave", query="same query")
    assert route.call_count == 1
    assert first == second


@respx.mock
async def test_cache_key_is_sha256_of_provider_and_query():
    kv = MemoryKV()
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": []}}))
    await client(kv, brave_api_key="k").search(provider="brave", query="q")
    expected = f"search:brave:{hashlib.sha256(b'q').hexdigest()}"
    assert await kv.get(expected) is not None


@respx.mock
async def test_different_queries_are_cached_separately():
    route = respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": []}}))
    kv = MemoryKV()
    c = client(kv, brave_api_key="k")
    await c.search(provider="brave", query="alpha")
    await c.search(provider="brave", query="beta")
    assert route.call_count == 2
