"""Per-provider search. PRD §16.1, §18.

Seven providers, one method each: `brave`, `tavily`, `exa` (find-similar),
`hn` (HN Algolia), `reddit`, `wayback` (CDX), `playstore`. Two of them --
`hn` and `wayback` -- need no credential at all (spec §3.1), which is what
lets Customer and Precedent function before any key exists.

Every provider method shares the same two-sided degrade contract as
`fetch.py` and `verify.py`:
  - a provider whose credential is absent returns [] before any request is
    attempted -- a missing key is a documented absence, not an error;
  - a provider call that raises for any other reason (network failure, a
    5xx, a response shape we don't recognise) also degrades to [] rather
    than propagating -- `search()` wraps every dispatch in one blanket
    try/except so a single flaky provider cannot crash the chair calling it.

NOTE on `producthunt` and `playstore`, called out explicitly because neither
is a clean fit for the "respx-mockable httpx call" shape the other five
providers have:

  - `producthunt` is routed to by `CHAIR_PROVIDERS[Chair.PRECEDENT]` in
    budgets.py, and `settings.producthunt_token` exists, but the batch
    brief's interfaces section lists only seven provider methods for
    `LiveSearchClient` and "producthunt" is not one of them. That reads as a
    real gap in the brief rather than an intentional omission, so rather
    than inventing an eighth provider method the brief never specified
    (endpoint, auth scheme, response shape -- all unstated), `search()`
    dispatches `producthunt` the same way it dispatches any other
    unrecognised provider name: to an empty list. This is flagged in the
    batch report rather than silently patched.

  - `playstore` has no HTTP API of its own; the brief specifies reaching it
    through the `google-play-scraper` PyPI library (added as a project
    dependency for this batch), run via `asyncio.to_thread` since it makes
    blocking requests internally. Because it does not go through httpx,
    respx cannot intercept it -- its tests monkeypatch
    `google_play_scraper.search` directly instead. That is a deliberate,
    narrow exception to "use respx to mock HTTP": there is no HTTP call at
    this module's boundary for respx to see, but the substitution still
    guarantees no real network request happens during tests.
"""
import asyncio
import hashlib
import json
from dataclasses import asdict

import httpx

from jury.settings import Settings
from jury.transport.protocols import KV, SearchHit

SEARCH_CACHE_TTL_S = 86_400
_TIMEOUT_S = 10.0
_WAYBACK_LIMIT = 5   # brief's literal endpoint template: "...&limit=5"


def _cache_key(provider: str, query: str) -> str:
    return f"search:{provider}:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"


def _hit(url: str | None, title: str | None, snippet: str | None) -> SearchHit:
    return SearchHit(url=url or "", title=title or "", snippet=snippet or "")


class LiveSearchClient:
    """`SearchClient` implementation used whenever the app is not offline."""

    def __init__(self, settings: Settings, kv: KV) -> None:
        self._settings = settings
        self._kv = kv

    async def search(self, *, provider: str, query: str,
                     limit: int = 10) -> list[SearchHit]:
        method = getattr(self, f"_search_{provider}", None)
        if method is None:
            # Either an unrecognised provider name, or a routed-but-not-yet-
            # implemented one (producthunt -- see module docstring). Both
            # are documented absences, not errors.
            return []

        key = _cache_key(provider, query)
        cached = await self._kv_get(key)
        if cached is not None:
            return [SearchHit(**h) for h in json.loads(cached)][:limit]

        try:
            hits = await method(query, limit)
        except Exception:  # noqa: BLE001 - a flaky provider degrades, never crashes
            return []

        await self._kv_set(key, json.dumps([asdict(h) for h in hits]))
        return hits[:limit]

    async def _kv_get(self, key: str) -> str | None:
        """The cache is an optimisation, never load-bearing: a KV hiccup
        degrades to an uncached live search, the same as fetch.py's cache."""
        try:
            return await self._kv.get(key)
        except Exception:
            return None

    async def _kv_set(self, key: str, value: str) -> None:
        try:
            await self._kv.set(key, value, ttl_s=SEARCH_CACHE_TTL_S)
        except Exception:
            pass

    # ── providers ─────────────────────────────────────────────────────

    async def _search_brave(self, query: str, limit: int) -> list[SearchHit]:
        key = self._settings.brave_api_key
        if not key:
            return []
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            r = await c.get("https://api.search.brave.com/res/v1/web/search",
                            params={"q": query, "count": limit},
                            headers={"X-Subscription-Token": key})
            r.raise_for_status()
            data = r.json()
        results = data.get("web", {}).get("results", [])
        return [_hit(x.get("url"), x.get("title"), x.get("description")) for x in results]

    async def _search_tavily(self, query: str, limit: int) -> list[SearchHit]:
        key = self._settings.tavily_api_key
        if not key:
            return []
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            r = await c.post("https://api.tavily.com/search",
                             json={"api_key": key, "query": query, "max_results": limit})
            r.raise_for_status()
            data = r.json()
        results = data.get("results", [])
        return [_hit(x.get("url"), x.get("title"), x.get("content")) for x in results]

    async def _search_exa(self, query: str, limit: int) -> list[SearchHit]:
        """PRD §11.2 dec. 11: Exa is the semantic find-similar provider --
        `query` here is a seed URL to find similar pages to, not free text."""
        key = self._settings.exa_api_key
        if not key:
            return []
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            r = await c.post("https://api.exa.ai/findSimilar",
                             json={"url": query, "numResults": limit},
                             headers={"x-api-key": key})
            r.raise_for_status()
            data = r.json()
        results = data.get("results", [])
        return [_hit(x.get("url"), x.get("title"), x.get("text")) for x in results]

    async def _search_hn(self, query: str, limit: int) -> list[SearchHit]:
        """Keyless (spec §3.1). Ask/Show HN posts often carry no external
        `url`, so those fall back to the HN item's own permalink -- a null
        url would otherwise silently disappear the hit's evidence value."""
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            r = await c.get("https://hn.algolia.com/api/v1/search",
                            params={"query": query, "hitsPerPage": limit})
            r.raise_for_status()
            data = r.json()
        hits = []
        for x in data.get("hits", []):
            url = x.get("url") or f"https://news.ycombinator.com/item?id={x.get('objectID')}"
            snippet = x.get("story_text") or x.get("comment_text") or ""
            hits.append(_hit(url, x.get("title"), snippet))
        return hits

    async def _search_reddit(self, query: str, limit: int) -> list[SearchHit]:
        cid = self._settings.reddit_client_id
        secret = self._settings.reddit_client_secret
        if not cid or not secret:
            return []
        headers = {"User-Agent": "jury/0.1 investigator"}
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            token_resp = await c.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(cid, secret), headers=headers)
            token_resp.raise_for_status()
            token = token_resp.json()["access_token"]

            r = await c.get("https://oauth.reddit.com/search",
                            params={"q": query, "limit": limit},
                            headers={**headers, "Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
        hits = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            permalink = d.get("permalink")
            url = f"https://reddit.com{permalink}" if permalink else d.get("url")
            hits.append(_hit(url, d.get("title"), d.get("selftext")))
        return hits

    async def _search_wayback(self, query: str, limit: int) -> list[SearchHit]:
        """Keyless (spec §3.1). PRD §16.7: 'the single highest-value
        retrieval trick in the product' -- CDX lets Precedent verify a dead
        product actually existed, via its own archived snapshots."""
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            r = await c.get("https://web.archive.org/cdx/search/cdx",
                            params={"url": query, "output": "json", "limit": _WAYBACK_LIMIT})
            r.raise_for_status()
            rows = r.json()
        if not rows or len(rows) < 2:
            return []
        header, *records = rows
        idx = {name: i for i, name in enumerate(header)}
        hits = []
        for row in records:
            timestamp = row[idx["timestamp"]]
            original = row[idx["original"]]
            hits.append(_hit(f"https://web.archive.org/web/{timestamp}/{original}",
                             original, f"archived {timestamp}"))
        return hits

    async def _search_playstore(self, query: str, limit: int) -> list[SearchHit]:
        """No key (it scrapes public Play Store search-result pages). Import
        is lazy so a deployment without the dependency degrades this one
        provider to [] (via `search()`'s blanket except) instead of failing
        to import the whole module."""
        from google_play_scraper import search as gps_search
        results = await asyncio.to_thread(gps_search, query, n_hits=limit)
        return [
            _hit(f"https://play.google.com/store/apps/details?id={r.get('appId')}",
                r.get("title"), r.get("description"))
            for r in results
        ]
