"""Tiered fetch. PRD §16.1.

Tier 1 (this module, always tried first): a direct GET plus local extraction
via trafilatura (`extract.py`). It is free, has no rate limit of its own, and
handles the overwhelming majority of pricing pages, docs and articles.

Tier 2 (this module, automatic fallback): when the tier-1 extraction comes
back with literally nothing (trafilatura and the tag-stripping fallback both
found no text at all -- typically a JS-rendered shell with no server-rendered
content for either to see through), the same URL is retried through Jina
Reader (`https://r.jina.ai/<url>`), a free hosted renderer that needs no API
key and returns pre-extracted markdown.

NOTE on the "thin" threshold: the batch brief's prose describes this as
"extraction below ~200 characters". That figure does not survive contact with
its own test fixtures -- trafilatura's real extraction of the brief's
pricing-page fixture is 37 characters, and of its dedup-test fixture is 31,
and neither of those tests mocks the Jina route, so a literal len(text) < 200
check would make both raise an unmocked-request error. The signal that
actually discriminates the brief's "retry" fixture (an empty `<div id="root">`
shell, 0 characters recovered by either extractor) from its "don't retry"
fixtures (short but real prose, 31-37 characters) is a small nonzero floor
(`_THIN_TEXT_FLOOR`, chosen at 20 characters -- comfortably below the 31/37
character fixtures, comfortably above "true zero"). A pure emptiness check
would also satisfy every given fixture, but a small floor additionally
catches the class of page that renders a cookie-banner or an "enable
JavaScript to continue" placeholder as its only server-rendered text -- a few
words, technically nonzero, still not a page worth treating as fetched. This
module documents the discrepancy here rather than silently matching the
letter of "~200 characters" against tests that contradict it.

Tier 3 (explicitly cut, spec §4): a headless-browser render (Playwright) for
pages that are thin even after Jina — client-side-only apps behind auth
walls, canvas-rendered pricing tables, and the like. It is deliberately not
built in this phase. The extension point is `LiveFetchClient._fetch_live`:
if the post-Jina text is still thin, that is where a Playwright-backed tier 3
call would be inserted, gated behind its own timeout and its own SSRF check
on whatever URL it actually navigates to (a browser follows redirects and
executes JS-driven navigation on its own, so the guard would need to run
against the browser's final URL, not just the one requested).

Every fetch target passes `assert_fetch_allowed` before any socket opens, and
every *redirect hop* is independently re-validated the same way before it is
followed — a plain per-URL SSRF check that only inspects the request URL is
exactly the check a redirect trivially bypasses (Batch K's guard also does
not resolve DNS, so this is the layer that would otherwise be the gap).
Fetches are deduplicated in Redis (or the in-memory KV fallback) by
canonical URL for 24 hours -- but only outcomes that are *not* transient are
cached that long. A hard 4xx (403 paywalled, 404 gone) is cached for the full
window: a source that rejected us a minute ago is not meaningfully more
fetchable now, and re-hitting it inside the same window only spends budget
for no new evidence. A 429 or 5xx is never cached at all, because it is not a
statement about the source -- it is a statement about *this attempt*, and
recording it for a day would silently turn a momentary rate-limit or outage
into a day-long absence of evidence in the ledger, which is exactly the
failure PRD §18 exists to prevent. The cache itself is also never
load-bearing for correctness: a KV read or write failure degrades to an
uncached live fetch rather than propagating, the same way a fetch failure
degrades to a rejected source rather than a crash.
"""
import json
from urllib.parse import urljoin

import httpx

from jury.engines.dedup import canonicalise_url
from jury.retrieval.extract import extract_text
from jury.retrieval.ssrf import assert_fetch_allowed, is_fetch_allowed
from jury.settings import Settings
from jury.transport.protocols import FetchResult

JINA_PREFIX = "https://r.jina.ai/"

_FETCH_TIMEOUT_S = 15.0
_DEDUP_TTL_S = 86_400
_MAX_REDIRECTS = 5
_TOO_MANY_REDIRECTS_STATUS = 310
_REDIRECT_BLOCKED_STATUS = 400
_THIN_TEXT_FLOOR = 20


def _cache_key(canonical_url: str) -> str:
    return f"fetch:{canonical_url}"


def _is_cacheable(status: int) -> bool:
    """2xx and "permanent-ish" 4xx are cached for the full dedup window. 429
    (rate limit) and 5xx (server-side outage) describe this attempt, not the
    source, and are never cached -- see the module docstring."""
    if status == 429 or 500 <= status < 600:
        return False
    return True


def _serialize(result: FetchResult) -> str:
    return json.dumps({
        "url": result.url, "status": result.status, "text": result.text,
        "content_type": result.content_type, "tier_hint": result.tier_hint,
    })


def _deserialize(raw: str) -> FetchResult:
    data = json.loads(raw)
    return FetchResult(**data)


class LiveFetchClient:
    """`FetchClient` implementation used whenever the app is not offline."""

    def __init__(self, settings: Settings, kv) -> None:
        self._settings = settings
        self._kv = kv

    async def fetch(self, url: str) -> FetchResult:
        # First, always -- before any socket opens, and before even the
        # cache lookup below (a cache hit still shouldn't mask a URL that
        # would otherwise be blocked, and this keeps the guard's contract
        # of "runs before anything else touches the network" simple).
        assert_fetch_allowed(url)

        canonical = canonicalise_url(url)
        cached = await self._kv_get(_cache_key(canonical))
        if cached is not None:
            return _deserialize(cached)

        result = await self._fetch_live(url)
        if _is_cacheable(result.status):
            await self._kv_set(_cache_key(canonical), _serialize(result), _DEDUP_TTL_S)
        return result

    async def _kv_get(self, key: str) -> str | None:
        """The cache is an optimisation, never load-bearing for correctness: a
        backend hiccup (network blip, Upstash returning a non-2xx) degrades to
        an uncached live fetch rather than crashing verification."""
        try:
            return await self._kv.get(key)
        except Exception:
            return None

    async def _kv_set(self, key: str, value: str, ttl_s: int) -> None:
        try:
            await self._kv.set(key, value, ttl_s=ttl_s)
        except Exception:
            pass

    async def _fetch_live(self, url: str) -> FetchResult:
        current = url
        async with httpx.AsyncClient(follow_redirects=False,
                                     timeout=_FETCH_TIMEOUT_S) as http:
            for _ in range(_MAX_REDIRECTS):
                try:
                    response = await http.get(current)
                except httpx.InvalidURL:
                    # httpx builds the redirect request eagerly to populate
                    # `response.next_request`/`history`, even with
                    # follow_redirects=False, so a `Location` header that
                    # doesn't parse as a URL (e.g. `javascript:alert(1)`, or
                    # anything else a hostile or merely misconfigured origin
                    # sends) raises here -- before our own per-hop SSRF
                    # recheck ever runs. Treat it exactly like a redirect our
                    # guard refused to follow: a malformed redirect target is
                    # never something we can hand to that recheck at all, and
                    # httpx.InvalidURL is NOT an httpx.HTTPError subclass, so
                    # it needs its own branch.
                    return FetchResult(url=current, status=_REDIRECT_BLOCKED_STATUS, text="")
                except httpx.HTTPError:
                    return FetchResult(url=current, status=502, text="")

                if response.is_redirect or 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        return FetchResult(url=current, status=response.status_code, text="")
                    next_url = urljoin(current, location)
                    # Never follow a redirect blindly: re-run the exact same
                    # guard against the hop's destination, not just the
                    # originally requested URL.
                    allowed, _reason = is_fetch_allowed(next_url)
                    if not allowed:
                        return FetchResult(url=current, status=_REDIRECT_BLOCKED_STATUS, text="")
                    current = next_url
                    continue

                if not (200 <= response.status_code < 300):
                    return FetchResult(url=current, status=response.status_code, text="")

                text = extract_text(response.text, current)
                if len(text.strip()) < _THIN_TEXT_FLOOR:
                    reader_text = await self._fetch_via_reader(current, http)
                    if reader_text:
                        text = reader_text
                return FetchResult(url=current, status=response.status_code, text=text)

            return FetchResult(url=current, status=_TOO_MANY_REDIRECTS_STATUS, text="")

    async def _fetch_via_reader(self, url: str, http: httpx.AsyncClient) -> str | None:
        """Tier 2: Jina Reader. `url` has already passed the SSRF guard as the
        page we are fetching on the model's behalf; the reader-service URL
        itself is a fixed, trusted host, so it is not re-checked."""
        try:
            response = await http.get(f"{JINA_PREFIX}{url}")
        except (httpx.HTTPError, httpx.InvalidURL):
            # Same blind spot as the tier-1 loop above: httpx can raise
            # InvalidURL while eagerly building a redirect request, and that
            # is not an HTTPError subclass. Here it just means "tier 2 didn't
            # pan out either" -- the caller falls back to whatever tier-1
            # text it already has.
            return None
        if not (200 <= response.status_code < 300):
            return None
        text = response.text.strip()
        return text or None
