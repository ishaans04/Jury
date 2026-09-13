# Phase 3 — Retrieval, Verification, and the Market Chair

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **PRD:** §16.1 (retrieval/extraction), §16.2 (tier rules), §6.1 (claim contract), §17.4 (SSRF), §18 (failure modes)

**Phase goal:** One chair working end to end, so the claim contract, the tier rules, the verification gate and the repair loop are all shaken out against a single corpus before being multiplied by five.

**Sequencing rule (PRD §20, verbatim):** *"Do not build all five chairs before one works end to end — M2 exists to shake out the claim contract and the validation loop with a single corpus."*

**Gate:** `uv run pytest tests/retrieval tests/chairs -q` green, including the hallucination guard: **50 fabricated company names injected into model output, 100% rejected at insert.**

---

## File structure

| Path | Responsibility |
|---|---|
| `jury/retrieval/ssrf.py` | Outbound URL allow/deny (PRD §17.4) |
| `jury/retrieval/search.py` | `LiveSearchClient` — Brave, Tavily, Exa, HN Algolia, Reddit, Wayback |
| `jury/retrieval/fetch.py` | `LiveFetchClient` — trafilatura → Jina Reader |
| `jury/retrieval/extract.py` | HTML → text, chunking |
| `jury/retrieval/embed.py` | fastembed → `source_chunks.embedding` (PRD §7.4) |
| `jury/retrieval/tiers.py` | Rule-based tier assignment (PRD §16.2) |
| `jury/retrieval/verify.py` | **P1 pre-persist verification** |
| `jury/retrieval/budgets.py` | Per-chair, per-provider query budgets (PRD §17.2) |
| `jury/chairs/base.py` | `Chair` protocol + shared claim pipeline |
| `jury/chairs/market.py` | Market chair |
| `jury/db/repositories.py` | `SourceRepo`, `EvidenceRepo`, `AssumptionRepo` |

---

### Task 3.1: SSRF guard

**Files:** Create `jury/retrieval/ssrf.py`; Test `tests/retrieval/test_ssrf.py`

**Interfaces:**
- `is_fetch_allowed(url: str) -> tuple[bool, str]` — `(allowed, reason)`
- `class BlockedURL(Exception)`
- `assert_fetch_allowed(url: str) -> None`

**Why (PRD §17.4, verbatim):** *"Outbound fetches run through an allowlist-blocklist check; no fetching of `localhost`, private IP ranges, or cloud metadata endpoints (SSRF guard). This matters because target URLs are partly model-selected."*

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/retrieval/test_ssrf.py
import pytest

from jury.retrieval.ssrf import BlockedURL, assert_fetch_allowed, is_fetch_allowed


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1:8000/", "http://0.0.0.0/",
    "http://[::1]/", "http://10.1.2.3/", "http://172.16.0.5/",
    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://100.64.0.1/",
    # Trailing dot: resolvers treat these as identical to the undotted form.
    "http://localhost./admin", "http://metadata./x",
    "http://metadata.google.internal./x", "http://instance-data./x",
    "http://169.254.169.254./latest/meta-data/", "http://127.0.0.1./",
    # inet_aton-style encodings that curl and glibc resolve to loopback.
    "http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/",
    "http://127.1/", "http://0x7f.0.0.1/", "http://[::ffff:127.0.0.1]/",
])
def test_private_and_metadata_targets_are_blocked(url):
    """Model-selected URLs must never reach infrastructure."""
    allowed, _ = is_fetch_allowed(url)
    assert allowed is False


def test_every_blocked_hostname_is_still_blocked_with_a_trailing_dot():
    """Canonicalisation, not enumeration. A future addition to BLOCKED_HOSTNAMES
    inherits this protection automatically instead of needing its own test."""
    from jury.retrieval.ssrf import BLOCKED_HOSTNAMES
    for host in BLOCKED_HOSTNAMES:
        assert is_fetch_allowed(f"http://{host}./")[0] is False, host


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://x.test/f", "gopher://x.test/",
    "data:text/html,<script>", "javascript:alert(1)",
])
def test_non_http_schemes_are_blocked(url):
    assert is_fetch_allowed(url)[0] is False


@pytest.mark.parametrize("url", [
    "https://example.test/pricing", "http://news.ycombinator.com/item?id=1",
    "https://web.archive.org/web/2020/https://x.test/",
])
def test_ordinary_public_urls_are_allowed(url):
    assert is_fetch_allowed(url)[0] is True


def test_decimal_encoded_loopback_is_blocked():
    """2130706433 == 127.0.0.1. A naive string check would miss this."""
    assert is_fetch_allowed("http://2130706433/")[0] is False


def test_octal_and_hex_encoded_loopback_is_blocked():
    assert is_fetch_allowed("http://0x7f000001/")[0] is False


def test_credentials_in_the_url_are_blocked():
    assert is_fetch_allowed("https://user:pass@example.test/")[0] is False


def test_the_reason_is_reported_so_it_can_be_traced():
    allowed, reason = is_fetch_allowed("http://169.254.169.254/")
    assert allowed is False and reason


def test_assert_helper_raises_blockedurl():
    with pytest.raises(BlockedURL):
        assert_fetch_allowed("http://127.0.0.1/")
    assert assert_fetch_allowed("https://example.test/") is None
```

- [ ] **Step 2: Verify it fails** — `uv run pytest tests/retrieval/test_ssrf.py -v`

- [ ] **Step 3: Implement**

```python
# apps/api/jury/retrieval/ssrf.py
"""SSRF guard. PRD §17.4.

Target URLs are partly model-selected, so this is a real attack surface rather
than a theoretical one. Blocking happens before any socket is opened.
"""
import ipaddress
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset({
    "localhost", "metadata.google.internal", "metadata",
    "instance-data", "169.254.169.254",
})


class BlockedURL(Exception):
    """Raised when an outbound fetch target fails the guard."""


def _host_as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Resolve literal forms only: dotted quad, decimal, hex, octal, IPv6.

    DNS is deliberately not resolved here — a hostname that resolves to a
    private address is caught by the transport's own no-redirect-to-private
    policy in fetch.py. What this catches is the literal-encoding bypass.
    """
    candidate = host.strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    for base in (10, 16, 8):
        try:
            as_int = int(candidate, base)
        except ValueError:
            continue
        if 0 <= as_int <= 0xFFFFFFFF:
            return ipaddress.ip_address(as_int)
    return None


def is_fetch_allowed(url: str) -> tuple[bool, str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "unparseable url"

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"scheme {parts.scheme!r} not permitted"
    if parts.username or parts.password:
        return False, "credentials in url"

    # Canonicalise BEFORE any check. A trailing dot marks a DNS name as already
    # fully-qualified, and resolvers treat "localhost." as "localhost" — so an
    # exact-string blocklist without this strip is bypassed by one character,
    # including on 169.254.169.254. (the cloud metadata endpoint). Enumerating
    # bad inputs is not a substitute for canonicalising them.
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return False, "missing host"
    if host in BLOCKED_HOSTNAMES:
        return False, f"host {host!r} is blocked"

    ip = _host_as_ip(host)
    if ip is not None:
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False, f"address {ip} is not a public destination"
        # Carrier-grade NAT, not flagged by is_private on all versions.
        if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
            return False, "shared address space"

    return True, "ok"


def assert_fetch_allowed(url: str) -> None:
    allowed, reason = is_fetch_allowed(url)
    if not allowed:
        raise BlockedURL(f"{url}: {reason}")
```

- [ ] **Step 4: Verify it passes** — expect 20 passed
- [ ] **Step 5: Commit** — `git commit -m "feat(retrieval): SSRF guard for model-selected fetch targets"`

---

### Task 3.2: Rule-based source tier assignment

**Files:** Create `jury/retrieval/tiers.py`; Test `tests/retrieval/test_tiers.py`

**Interfaces:**
- `assign_tier(url: str, domain_map: dict[str, int], *, has_review_count: bool = False) -> int | None`
- `PATTERN_RULES: tuple[TierRule, ...]`
- `DEFAULT_TIER = 3`

**Rules (PRD §16.2) — tier is assigned by rule, never by model.** Pattern rules are checked before the domain map, because *"URL is a pricing/plans page on the vendor's own domain, fetched live"* is a property of the **path**, not the host. Unknown domains default to tier 3. Unresolvable → `None` → rejected.

**Pass bar (PRD §19.2):** ≥95% on 100 labelled URLs. Since it is rule-based, aim for 100% on the fixture set.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/retrieval/test_tiers.py
import pytest

from jury.retrieval.tiers import DEFAULT_TIER, assign_tier

MAP = {"sec.gov": 1, "web.archive.org": 1, "play.google.com": 1,
       "crunchbase.com": 2, "g2.com": 2, "techcrunch.com": 3,
       "reddit.com": 4, "news.ycombinator.com": 4}


@pytest.mark.parametrize("url", [
    "https://sec.gov/cgi-bin/browse-edgar?action=x",
    "https://web.archive.org/web/20200101/https://dead.test/",
    "https://play.google.com/store/apps/details?id=com.x",
])
def test_registers_archives_and_stores_are_tier1(url):
    assert assign_tier(url, MAP) == 1


@pytest.mark.parametrize("path", ["/pricing", "/plans", "/pricing/", "/en/pricing",
                                  "/docs/api/pricing"])
def test_vendor_pricing_pages_are_tier1_whatever_the_domain(path):
    """PRD §16.2: 'URL is a pricing/plans page on the vendor's own domain,
    fetched live' -> tier 1. An unknown vendor's live pricing page is primary."""
    assert assign_tier(f"https://unknown-vendor.test{path}", MAP) == 1


@pytest.mark.parametrize("path", ["/docs/api", "/api-reference", "/developers/docs"])
def test_vendor_api_docs_are_tier1(path):
    assert assign_tier(f"https://unknown-vendor.test{path}", MAP) == 1


def test_a_pricing_path_on_a_news_domain_is_not_promoted():
    """TechCrunch writing about pricing is journalism, not a pricing page."""
    assert assign_tier("https://techcrunch.com/2026/01/pricing-wars", MAP) == 3


def test_funding_databases_are_tier2():
    assert assign_tier("https://crunchbase.com/organization/x", MAP) == 2


def test_review_aggregate_with_a_visible_count_is_tier2():
    assert assign_tier("https://g2.com/products/x/reviews", MAP,
                       has_review_count=True) == 2


def test_news_domains_are_tier3():
    assert assign_tier("https://techcrunch.com/2026/01/x", MAP) == 3


def test_forums_are_tier4():
    assert assign_tier("https://reddit.com/r/startups/comments/x", MAP) == 4
    assert assign_tier("https://news.ycombinator.com/item?id=1", MAP) == 4


def test_unknown_domain_defaults_to_tier3():
    assert assign_tier("https://some-random-blog.test/post", MAP) == DEFAULT_TIER


def test_unresolvable_url_returns_none_so_the_claim_is_rejected():
    """PRD §16.2: 'Anything unresolvable -> rejected.'"""
    assert assign_tier("not-a-url", MAP) is None
    assert assign_tier("", MAP) is None


def test_tier_five_is_never_returned():
    """P1: tier 5 is a model prior and cannot be persisted."""
    for url in ("https://sec.gov/x", "https://reddit.com/x", "https://weird.test/x"):
        assert assign_tier(url, MAP) != 5


def test_subdomains_inherit_the_domain_tier():
    assert assign_tier("https://data.crunchbase.com/x", MAP) == 2


def test_www_is_ignored_when_matching_the_domain_map():
    assert assign_tier("https://www.reddit.com/r/x", MAP) == 4


def test_assignment_is_deterministic():
    for _ in range(20):
        assert assign_tier("https://g2.com/products/x", MAP) == 2
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement**

```python
# apps/api/jury/retrieval/tiers.py
"""Source tier assignment. PRD §16.2 — by rule, not by model.

A domain allowlist/tier map is seeded by hand (db/seed/002_domain_tiers.sql)
and extended as needed. Unknown domains default to tier 3.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_TIER = 3

_PRICING_PATH = re.compile(r"(^|/)(pricing|plans|price)(/|$)", re.I)
_API_DOCS_PATH = re.compile(r"(^|/)(api[-_]?reference|api|developers?/docs|docs/api)(/|$)", re.I)


@dataclass(frozen=True, slots=True)
class TierRule:
    name: str
    tier: int
    matches: object       # Callable[[str, str], bool]


def _is_pricing_page(host: str, path: str) -> bool:
    return bool(_PRICING_PATH.search(path))


def _is_api_docs(host: str, path: str) -> bool:
    return bool(_API_DOCS_PATH.search(path))


# Path-shaped rules run BEFORE the domain map, because a live pricing page is a
# primary artifact regardless of whether we have heard of the vendor.
PATTERN_RULES: tuple[TierRule, ...] = (
    TierRule("vendor_pricing_page", 1, _is_pricing_page),
    TierRule("vendor_api_docs", 1, _is_api_docs),
)


def _normalise_host(host: str) -> str:
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _map_lookup(host: str, domain_map: dict[str, int]) -> int | None:
    """Exact match, then walk up the subdomain chain."""
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in domain_map:
            return domain_map[candidate]
    return None


def assign_tier(url: str, domain_map: dict[str, int], *,
                has_review_count: bool = False) -> int | None:
    """Return tier 1-4, or None when the URL is unresolvable (claim rejected)."""
    if not url or "://" not in url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = _normalise_host(parts.hostname or "")
    if not host:
        return None

    known = _map_lookup(host, domain_map)

    # Path rules promote to tier 1, but never override a known low-trust domain:
    # a journalism site writing about pricing is still journalism.
    if known is None or known == 1:
        for rule in PATTERN_RULES:
            if rule.matches(host, parts.path):
                return rule.tier

    if known is not None:
        # A review aggregate only earns tier 2 when the count is actually visible.
        if known == 2 and "review" in parts.path.lower() and not has_review_count:
            return DEFAULT_TIER
        return known

    return DEFAULT_TIER
```

- [ ] **Step 4: Verify it passes** — expect 24 passed
- [ ] **Step 5: Build the 100-URL labelled fixture** at `evals/fixtures/tier_urls.json` (`[{url, expected_tier}]`) and add `tests/retrieval/test_tiers_eval.py` asserting **≥95%**, reporting actual accuracy.
- [ ] **Step 6: Commit** — `git commit -m "feat(retrieval): rule-based source tier assignment"`

---

### Task 3.3: Fetch tiers and extraction

**Files:** Create `jury/retrieval/fetch.py`, `jury/retrieval/extract.py`; Test `tests/retrieval/test_fetch.py`

**Interfaces:**
- `class LiveFetchClient(settings, kv)` implementing `FetchClient`
- `async def fetch(url) -> FetchResult` — trafilatura first, Jina Reader fallback
- `extract_text(html: str, url: str) -> str`
- `chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]`

**Tiered by cost (PRD §16.1):** trafilatura (local, free) → Jina Reader (`r.jina.ai/<url>`, free, no key). **Playwright is cut** (spec §4) with fetch tier 3 left as a documented extension point.

**Every fetch is deduplicated in Redis by canonical URL with a 24-hour TTL** (PRD §16.1).

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/retrieval/test_fetch.py
import httpx
import pytest
import respx

from jury.retrieval.extract import chunk, extract_text
from jury.retrieval.fetch import JINA_PREFIX, LiveFetchClient
from jury.retrieval.ssrf import BlockedURL
from jury.settings import Settings
from jury.transport.kv import MemoryKV

pytestmark = pytest.mark.network


def client(kv=None):
    return LiveFetchClient(Settings(_env_file=None), kv or MemoryKV())


@respx.mock
async def test_a_normal_page_is_fetched_and_extracted():
    respx.get("https://x.test/pricing").mock(
        return_value=httpx.Response(200, html="<html><body><main>"
                                    "<h1>Pricing</h1><p>Starter is 149 INR per month.</p>"
                                    "</main></body></html>"))
    r = await client().fetch("https://x.test/pricing")
    assert r.status == 200
    assert "149" in r.text


@respx.mock
async def test_thin_extraction_falls_back_to_jina_reader():
    """PRD §16.1 tier 2. Jina Reader is free and needs no key."""
    respx.get("https://js.test/pricing").mock(
        return_value=httpx.Response(200, html="<html><body><div id='root'></div></body></html>"))
    respx.get(f"{JINA_PREFIX}https://js.test/pricing").mock(
        return_value=httpx.Response(200, text="# Pricing\n\nPro plan costs 499 INR."))
    r = await client().fetch("https://js.test/pricing")
    assert "499" in r.text


@respx.mock
async def test_a_403_is_returned_as_a_rejected_source_not_an_exception():
    """PRD §18: 'Page fetch 403 / paywall -> claim rejected at insert; logged as
    a rejected source.' Degrade to less evidence, never crash."""
    respx.get("https://paywall.test/a").mock(return_value=httpx.Response(403))
    r = await client().fetch("https://paywall.test/a")
    assert r.status == 403 and r.text == ""


@respx.mock
async def test_a_404_is_returned_as_a_rejected_source():
    respx.get("https://gone.test/a").mock(return_value=httpx.Response(404))
    assert (await client().fetch("https://gone.test/a")).status == 404


async def test_a_blocked_target_raises_before_any_socket_opens():
    with pytest.raises(BlockedURL):
        await client().fetch("http://169.254.169.254/latest/meta-data/")


@respx.mock
async def test_the_same_canonical_url_is_fetched_once_within_the_ttl():
    """PRD §16.1: every fetch is deduplicated in Redis by canonical URL, 24h TTL."""
    route = respx.get("https://x.test/p").mock(
        return_value=httpx.Response(200, html="<p>Body text that is long enough.</p>"))
    kv = MemoryKV()
    c = client(kv)
    await c.fetch("https://x.test/p")
    await c.fetch("https://x.test/p?utm_source=tw")   # same canonical url
    assert route.call_count == 1


@respx.mock
async def test_a_redirect_to_a_private_address_is_refused():
    respx.get("https://evil.test/r").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:22/"}))
    r = await client().fetch("https://evil.test/r")
    assert r.status >= 400


# ── extraction and chunking, no network ────────────────────────────────────
@pytest.mark.parametrize("html,needle", [
    ("<html><body><article><p>Pro plan is 999 INR.</p></article></body></html>", "999"),
    ("<html><body><main><p>Free tier includes 3 seats.</p></main></body></html>", "3 seats"),
])
def test_extract_text_pulls_the_body(html, needle):
    assert needle in extract_text(html, "https://x.test/")


def test_extract_text_drops_script_and_nav_noise():
    html = ("<html><body><nav>Home About</nav><script>var x=1</script>"
            "<main><p>The real content is a price of 250 INR.</p></main></body></html>")
    out = extract_text(html, "https://x.test/")
    assert "250" in out and "var x=1" not in out


def test_chunking_respects_size_and_overlaps():
    text = " ".join(f"word{i}" for i in range(600))
    chunks = chunk(text, size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert chunks[0][-10:] in chunks[1]        # overlap preserved


def test_chunking_a_short_text_yields_one_chunk():
    assert chunk("short", size=200) == ["short"]
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement `extract.py` then `fetch.py`**

`extract.py` uses `trafilatura.extract(html, url=url, include_tables=True, favor_precision=True)` and falls back to a tag-stripping regex path when trafilatura returns `None`. `chunk` slides a window of `size` with `overlap`, breaking on whitespace so chunks stay word-aligned.

`fetch.py`:
- `assert_fetch_allowed(url)` first, always.
- Canonicalise, check `kv.get(f"fetch:{canonical}")`; on hit return the cached `FetchResult`.
- `httpx.AsyncClient(follow_redirects=False, timeout=15.0)`; on a 3xx, re-run `assert_fetch_allowed` on the `Location` and return `FetchResult(status=400)` if it fails — this is the redirect-based SSRF bypass.
- Non-2xx returns `FetchResult(status=..., text="")`. **No exception** — PRD §18 wants a rejected source, not a crash.
- If extracted text is under 200 characters, retry via `JINA_PREFIX = "https://r.jina.ai/"`.
- Cache the result under the canonical URL with `ttl_s=86_400`.
- Add a module docstring noting Playwright is cut (spec §4) and where tier 3 would slot in.

- [ ] **Step 4: Verify it passes** — expect 12 passed
- [ ] **Step 5: Commit** — `git commit -m "feat(retrieval): tiered fetch with jina fallback, dedup cache and redirect guard"`

---

### Task 3.4: Pre-persist verification — the integrity guarantee

**Files:** Create `jury/retrieval/verify.py`; Test `tests/retrieval/test_verify.py`

**Interfaces:**
- `async def verify_claim(claim: ClaimRecord, fetch: FetchClient, *, domain_map: dict[str,int]) -> VerifiedClaim | Rejection`
- `VerifiedClaim` dataclass: `claim`, `tier: int`, `canonical_url: str`, `extracted_text: str`, `http_status: int`
- `Rejection` dataclass: `claim`, `reason: str`
- `excerpt_is_present(excerpt: str, text: str) -> bool`

**PRD §18, verbatim:** *"LLM invents a company or a statistic → Pre-persist fetch verification returns non-2xx or the excerpt is absent from the extracted text → Claim rejected before insert. **This check is the product's integrity guarantee and is non-optional.**"*

Two conditions, both required: HTTP **2xx**, and the excerpt **present in the extracted text**. PRD §16.7 restates it for precedent: *"a precedent claim is rejected at insert unless it carries a resolvable source URL that was actually fetched and returned a 2xx. Verify before persist."*

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/retrieval/test_verify.py
import pytest

from jury.retrieval.verify import Rejection, VerifiedClaim, excerpt_is_present, verify_claim
from jury.schemas.claim import ClaimRecord
from jury.transport.protocols import FetchResult

MAP = {"x.test": 3, "sec.gov": 1}
PAGE = ("Our Starter plan is priced at 149 INR per month and includes three seats. "
        "The Pro plan is 499 INR per month.")


def claim(url="https://x.test/pricing", excerpt="Starter plan is priced at 149 INR per month",
          **kw) -> ClaimRecord:
    base = {"assumption_id": "a1", "direction": "supports", "variable": "price_monthly",
            "value_num": 149.0, "unit": "INR_per_month",
            "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.8,
            "source_url": url, "source_tier": 1, "excerpt": excerpt, "chair": "market"}
    return ClaimRecord.model_validate(base | kw)


class StubFetch:
    def __init__(self, status=200, text=PAGE):
        self._status, self._text = status, text
        self.calls: list[str] = []

    async def fetch(self, url):
        self.calls.append(url)
        return FetchResult(url=url, status=self._status, text=self._text)


async def test_a_real_claim_with_a_present_excerpt_is_accepted():
    out = await verify_claim(claim(), StubFetch(), domain_map=MAP)
    assert isinstance(out, VerifiedClaim)
    assert out.http_status == 200


async def test_a_non_2xx_source_is_rejected():
    """P1: no fetched 2xx, no row."""
    out = await verify_claim(claim(), StubFetch(status=404), domain_map=MAP)
    assert isinstance(out, Rejection) and "404" in out.reason


async def test_an_excerpt_absent_from_the_page_is_rejected():
    out = await verify_claim(claim(excerpt="Starter plan is 49 USD per month"),
                             StubFetch(), domain_map=MAP)
    assert isinstance(out, Rejection) and "excerpt" in out.reason.lower()


async def test_the_fetch_actually_happens_before_the_decision():
    stub = StubFetch()
    await verify_claim(claim(), stub, domain_map=MAP)
    assert stub.calls, "verification must fetch, not trust the model"


async def test_tier_is_reassigned_by_rule_and_overrides_the_model():
    """PRD §16.2: tier is assigned by rule, not by model. A model claiming
    tier 1 for a forum post does not get it."""
    out = await verify_claim(claim(url="https://x.test/blog/post", source_tier=1),
                             StubFetch(), domain_map=MAP)
    assert isinstance(out, VerifiedClaim) and out.tier == 3


async def test_an_unresolvable_url_is_rejected():
    out = await verify_claim(claim(url="https://x.test/p", source_tier=1),
                             StubFetch(), domain_map={})
    assert isinstance(out, VerifiedClaim)      # unknown domain defaults to tier 3
    assert out.tier == 3


async def test_a_blocked_url_is_rejected_without_fetching():
    stub = StubFetch()
    out = await verify_claim(claim(url="http://127.0.0.1/p"), stub, domain_map=MAP)
    assert isinstance(out, Rejection)
    assert stub.calls == []


# ── THE HALLUCINATION GUARD (PRD §19.2: 100% rejected) ─────────────────────
FABRICATED = [f"Zephyrix{i} Technologies" for i in range(50)]


@pytest.mark.parametrize("company", FABRICATED)
async def test_fabricated_companies_are_rejected_at_insert(company):
    """PRD §19.2 hallucination guard: 50 fabricated company names injected into
    model output, pass bar 100% rejected.

    The page text never mentions the company, so the excerpt cannot be present.
    """
    out = await verify_claim(
        claim(excerpt=f"{company} shut down in 2024 after failing to raise."),
        StubFetch(), domain_map=MAP)
    assert isinstance(out, Rejection), f"{company} was NOT rejected"


async def test_all_fifty_fabrications_are_rejected_together():
    stub = StubFetch()
    results = [await verify_claim(
        claim(excerpt=f"{c} raised 10M in 2023."), stub, domain_map=MAP)
        for c in FABRICATED]
    rejected = sum(1 for r in results if isinstance(r, Rejection))
    assert rejected == 50, f"only {rejected}/50 rejected"


# ── excerpt matching must be robust without becoming permissive ────────────
def test_whitespace_and_case_differences_are_tolerated():
    assert excerpt_is_present("STARTER  plan is\npriced at 149 INR", PAGE)


def test_smart_quotes_and_dashes_are_normalised():
    page = "The Pro plan costs “499” INR — billed monthly."
    assert excerpt_is_present('The Pro plan costs "499" INR - billed monthly.', page)


def test_a_paraphrase_is_not_accepted():
    """'verbatim supporting text' means verbatim (PRD §6.1)."""
    assert not excerpt_is_present("The entry tier costs about 150 rupees", PAGE)


def test_an_empty_excerpt_is_never_present():
    assert not excerpt_is_present("", PAGE)
    assert not excerpt_is_present("   ", PAGE)


def test_an_excerpt_is_not_present_in_empty_text():
    assert not excerpt_is_present("anything", "")
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement**

```python
# apps/api/jury/retrieval/verify.py
"""Pre-persist verification. P1 and PRD §18.

"This check is the product's integrity guarantee and is non-optional."

Two conditions, both required before a claim may become a ledger row:
  1. the source URL was actually fetched and returned 2xx
  2. the excerpt is present in the extracted text

Tier is then reassigned by rule (PRD §16.2), overriding whatever the model said.
"""
import re
import unicodedata
from dataclasses import dataclass

from jury.engines.dedup import canonicalise_url
from jury.retrieval.ssrf import is_fetch_allowed
from jury.retrieval.tiers import assign_tier
from jury.schemas.claim import ClaimRecord
from jury.transport.protocols import FetchClient

_WS = re.compile(r"\s+")
_PUNCT_FOLD = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}


@dataclass(frozen=True, slots=True)
class VerifiedClaim:
    claim: ClaimRecord
    tier: int
    canonical_url: str
    extracted_text: str
    http_status: int


@dataclass(frozen=True, slots=True)
class Rejection:
    claim: ClaimRecord
    reason: str


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for bad, good in _PUNCT_FOLD.items():
        text = text.replace(bad, good)
    return _WS.sub(" ", text).strip().lower()


def excerpt_is_present(excerpt: str, text: str) -> bool:
    """Verbatim substring match after whitespace, case and punctuation folding.

    Deliberately NOT fuzzy: PRD §6.1 specifies "verbatim supporting text", and a
    similarity threshold is exactly the loophole a hallucinated statistic slips
    through.
    """
    needle = _normalise(excerpt)
    if not needle:
        return False
    return needle in _normalise(text)


async def verify_claim(claim: ClaimRecord, fetch: FetchClient, *,
                       domain_map: dict[str, int]) -> VerifiedClaim | Rejection:
    allowed, reason = is_fetch_allowed(claim.source_url)
    if not allowed:
        return Rejection(claim, f"blocked url: {reason}")

    result = await fetch.fetch(claim.source_url)
    if not (200 <= result.status < 300):
        return Rejection(claim, f"source returned http {result.status}")
    if not result.text.strip():
        return Rejection(claim, "source returned no extractable text")
    if not excerpt_is_present(claim.excerpt, result.text):
        return Rejection(claim, "excerpt absent from the extracted text")

    tier = assign_tier(claim.source_url, domain_map)
    if tier is None:
        return Rejection(claim, "source url unresolvable for tier assignment")

    return VerifiedClaim(claim=claim, tier=tier,
                         canonical_url=canonicalise_url(claim.source_url),
                         extracted_text=result.text, http_status=result.status)
```

- [ ] **Step 4: Verify it passes** — expect 64 passed (including 50 parametrised fabrications)
- [ ] **Step 5: Commit** — `git commit -m "feat(retrieval): pre-persist verification and hallucination guard"`

---

### Task 3.5: Search routing and per-chair budgets

**Files:** Create `jury/retrieval/search.py`, `jury/retrieval/budgets.py`; Test `tests/retrieval/test_budgets.py`, `tests/retrieval/test_search.py`

**Interfaces:**
- `CHAIR_BUDGETS: dict[Chair, int]` = `{market: 8, customer: 8, precedent: 10, dependencies: 6, economics: 3}`
- `CHAIR_PROVIDERS: dict[Chair, tuple[str, ...]]`
- `class BudgetLedger(kv: KV, run_id: str)` with `async def spend(chair, provider) -> bool`
- `class LiveSearchClient(settings, kv)` implementing `SearchClient`, providers: `brave`, `tavily`, `exa`, `hn`, `reddit`, `wayback`, `playstore`

**Routing (PRD §16.1), and PRD §11.2 dec. 11's reason for it:** *"Precedent needs semantic find-similar (Exa); Market needs an independent index and direct page fetches (Brave); Customer needs domain APIs. Neither substitutes for the other."*

Total budget is **35** across all chairs (PRD §17.2) — and 8+8+10+6+3 = 35 exactly. A test asserts that.

**Keyless providers:** `hn` (HN Algolia) and `wayback` (CDX) work with no credential (spec §3.1) — so a missing key degrades a chair rather than disabling it.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/retrieval/test_budgets.py
from jury.retrieval.budgets import CHAIR_BUDGETS, CHAIR_PROVIDERS, BudgetLedger
from jury.schemas.enums import Chair
from jury.transport.kv import MemoryKV


def test_chair_budgets_match_the_prd_table():
    assert CHAIR_BUDGETS == {Chair.MARKET: 8, Chair.CUSTOMER: 8, Chair.PRECEDENT: 10,
                             Chair.DEPENDENCIES: 6, Chair.ECONOMICS: 3}


def test_the_budgets_sum_to_the_global_cap_of_35():
    """PRD §17.2: 35 search queries across all chairs."""
    assert sum(CHAIR_BUDGETS.values()) == 35


def test_every_chair_has_at_least_one_provider():
    assert set(CHAIR_PROVIDERS) == set(Chair)
    assert all(CHAIR_PROVIDERS[c] for c in Chair)


def test_customer_routes_to_keyless_hn_so_it_works_without_credentials():
    """Spec §3.1: HN Algolia is keyless and unlimited."""
    assert "hn" in CHAIR_PROVIDERS[Chair.CUSTOMER]


def test_precedent_routes_to_wayback_for_death_verification():
    """PRD §16.7: 'the single highest-value retrieval trick in the product'."""
    assert "wayback" in CHAIR_PROVIDERS[Chair.PRECEDENT]


def test_precedent_routes_to_exa_for_find_similar():
    assert "exa" in CHAIR_PROVIDERS[Chair.PRECEDENT]


async def test_a_chair_cannot_exceed_its_budget():
    ledger = BudgetLedger(MemoryKV(), run_id="r1")
    spent = [await ledger.spend(Chair.ECONOMICS, "brave") for _ in range(5)]
    assert spent == [True, True, True, False, False]


async def test_budgets_are_independent_per_chair():
    ledger = BudgetLedger(MemoryKV(), run_id="r1")
    for _ in range(3):
        await ledger.spend(Chair.ECONOMICS, "brave")
    assert await ledger.spend(Chair.MARKET, "brave") is True


async def test_budgets_are_independent_per_run():
    kv = MemoryKV()
    a, b = BudgetLedger(kv, "r1"), BudgetLedger(kv, "r2")
    for _ in range(3):
        await a.spend(Chair.ECONOMICS, "brave")
    assert await b.spend(Chair.ECONOMICS, "brave") is True
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement `budgets.py` and `search.py`**

`budgets.py` holds the two maps plus `BudgetLedger`, which uses `kv.incr_bucket(f"budget:{run_id}:{chair}", limit=CHAIR_BUDGETS[chair], window_s=3600)`.

`CHAIR_PROVIDERS`:
```python
CHAIR_PROVIDERS: dict[Chair, tuple[str, ...]] = {
    Chair.MARKET:       ("brave", "tavily"),
    Chair.CUSTOMER:     ("hn", "reddit", "playstore", "brave"),
    Chair.PRECEDENT:    ("exa", "brave", "wayback", "producthunt"),
    Chair.DEPENDENCIES: ("brave",),
    Chair.ECONOMICS:    ("brave",),
}
```

`search.py` implements one small async method per provider, each returning `list[SearchHit]`:
- `brave` — `GET https://api.search.brave.com/res/v1/web/search`, header `X-Subscription-Token`
- `tavily` — `POST https://api.tavily.com/search`
- `exa` — `POST https://api.exa.ai/findSimilar`, header `x-api-key`
- `hn` — `GET https://hn.algolia.com/api/v1/search?query=` — **no key**
- `reddit` — OAuth client-credentials token, then `GET https://oauth.reddit.com/search`
- `wayback` — `GET https://web.archive.org/cdx/search/cdx?url=<u>&output=json&limit=5` — **no key**
- `playstore` — `google-play-scraper` via `asyncio.to_thread`

`search()` dispatches on `provider`, returns `[]` when the provider's key is absent (a documented absence, per PRD §18 — never an exception), caches results in `kv` under `search:{provider}:{sha256(query)}` for 24h, and emits nothing to the ledger itself.

- [ ] **Step 4: Verify both pass**
- [ ] **Step 5: Commit** — `git commit -m "feat(retrieval): per-chair search routing with enforced budgets"`

---

### Task 3.6: Repositories

**Files:** Create `jury/db/repositories.py`; Test `tests/db/test_repositories.py`

**Interfaces:**
- `class SourceRepo(pool)`: `async def upsert(canonical_url, domain, tier, title, http_status, storage_path=None) -> str`
- `class EvidenceRepo(pool)`: `async def insert_verified(project_id, run_id, assumption_id, source_id, verified: VerifiedClaim) -> str | None` (returns `None` on dedup collision), `async def list_for_project(project_id) -> list[dict]`
- `class AssumptionRepo(pool)`: `create_many`, `list_for_project`, `update_status_and_strength`, `create_discovered`
- `class ConflictRepo`, `ModelRunRepo`, `ExperimentRepo`, `VerdictRepo`, `LedgerVersionRepo`

**This is the only module that writes SQL** (spec §6). P6 means `EvidenceRepo` exposes **no** update or delete method — and a test asserts that by introspection.

- [ ] **Step 1: Write the failing test**

Key cases:
```python
async def test_evidence_repo_exposes_no_mutation_methods():
    """P6: corrections supersede. A repo method that updates evidence would be
    a bug the database would then reject at runtime — better to not have it."""
    names = [n for n in dir(EvidenceRepo) if not n.startswith("_")]
    for banned in ("update", "delete", "upsert", "save", "set_confidence"):
        assert not any(banned in n for n in names), names


async def test_duplicate_dedup_hash_returns_none_rather_than_raising(pool):
    """P10 at the application boundary: the second insert is a no-op, not a crash.
    Two chairs finding the same pricing page is normal, not exceptional."""
    ...
    assert await repo.insert_verified(**args) is not None
    assert await repo.insert_verified(**args) is None


async def test_source_upsert_is_idempotent_on_canonical_url(pool):
    a = await repo.upsert("https://x.test/p", "x.test", 1, "T", 200)
    b = await repo.upsert("https://x.test/p", "x.test", 1, "T", 200)
    assert a == b


async def test_insert_verified_computes_the_dedup_hash_itself(pool):
    """The caller must not be able to supply a wrong hash and defeat P10."""
    ...
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Implement.** `insert_verified` derives `dedup_hash` from `(canonical_url, variable, scope)` via `engines.dedup.dedup_hash` — never from a caller argument — and catches `psycopg.errors.UniqueViolation` to return `None`.
- [ ] **Step 4: Verify it passes**
- [ ] **Step 5: Commit** — `git commit -m "feat(db): repositories with insert-only evidence access"`

---

### Task 3.7: The Market chair, end to end

**Files:** Create `jury/chairs/__init__.py`, `base.py`, `market.py`; Test `tests/chairs/test_market.py`

**Interfaces:**
- `class ChairContext` dataclass: `run_id`, `project_id`, `pitch`, `target_scope`, `assumptions: list[AssumptionRecord]`, `transports: Transports`, `budgets: BudgetLedger`, `domain_map`, `trace`, **`pool`**, **`embedder: Embedder`**
  (`pool` and `embedder` are required by Task 3.8's `persist_chunks`, which the shared pipeline calls once per source)
- `async def investigate(ctx: ChairContext) -> ChairResult`
- `ChairResult` dataclass: `inserted: list[str]`, `rejected: list[Rejection]`, `discovered: list[NewAssumption]`, `partial: bool`, `no_precedent_found: bool = False`
  (the last field is only ever set by the Precedent chair in Phase 4, but it lives on the shared dataclass so `ChairResult` has one definition across all five chairs)
- `jury.chairs.market.investigate` conforms to the same signature

**Shared pipeline in `base.py`** — every chair runs these steps, so a new chair is a query strategy plus a prompt, nothing more:
1. Build queries from the pitch + assumptions (chair-specific).
2. `budgets.spend(chair, provider)`; when refused, mark `partial=True` and stop searching. PRD §18: *"mark chair `partial` and reduce that chair's contribution, which lowers coverage and correctly pushes toward HUNG_JURY."*
3. Search → fetch → extract → chunk.
4. `structured_report(...)` against `ClaimRecord` (Phase 2's repair loop).
5. `verify_claim(...)` — P1 gate.
6. `SourceRepo.upsert` → `EvidenceRepo.insert_verified`.
7. Emit `run_events` rows at each `fetch` and `llm_call`.

**Critical ordering:** verification happens **before** persistence, never after. A test asserts no insert occurs for a rejected claim.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/chairs/test_market.py — key cases
async def test_market_emits_only_verified_claims(ctx_offline):
    result = await market.investigate(ctx_offline)
    assert result.inserted
    for eid in result.inserted:
        row = await fetch_evidence(eid)
        assert row["chair"] == "market"
        assert row["scope_geo"] and row["scope_segment"]


async def test_a_rejected_claim_never_reaches_the_database(ctx_with_fabricated_llm):
    """P1 is an ordering guarantee, not just a check."""
    result = await market.investigate(ctx_with_fabricated_llm)
    assert result.inserted == []
    assert result.rejected
    assert await count_evidence(ctx.project_id) == 0


async def test_exhausted_budget_marks_the_chair_partial_not_failed(ctx_zero_budget):
    """PRD §18: degrade to less evidence, never crash."""
    result = await market.investigate(ctx_zero_budget)
    assert result.partial is True
    assert result.inserted == []


async def test_the_chair_records_a_source_row_before_the_evidence_row():
    """FK ordering, and it means a rejected claim leaves no orphan source."""
    ...


async def test_a_new_assumption_from_the_chair_is_returned_not_silently_dropped():
    """PRD §7.3: investigators are permitted to emit new_assumption mid-run."""
    result = await market.investigate(ctx_with_new_assumption_llm)
    assert result.discovered and result.discovered[0].class_key


async def test_the_chair_writes_fetch_and_llm_rows_to_the_trace(ctx_offline):
    await market.investigate(ctx_offline)
    kinds = {r["event"] for r in ctx_offline.trace.rows}
    assert {"fetch", "llm_call"} <= kinds


async def test_the_chair_emits_no_prose_only_typed_records(ctx_offline):
    """PRD §6.1: no prose commentary is persisted or displayed except
    cross-examination transcripts."""
    result = await market.investigate(ctx_offline)
    assert all(isinstance(x, str) for x in result.inserted)


async def test_running_twice_inserts_no_duplicates(ctx_offline):
    """P10 end to end."""
    first = await market.investigate(ctx_offline)
    second = await market.investigate(ctx_offline)
    assert second.inserted == []
    assert first.inserted
```

- [ ] **Step 2: Verify it fails**
- [ ] **Step 3: Record the Market fixtures.** Create `tests/fixtures/search/*.json` and `tests/fixtures/fetch/*.json` for a demo pitch in a crowded category (PRD §22: *"Pick something in a crowded space where real contradictions and real corpses exist"*), plus `tests/fixtures/llm/*.json` with valid `ClaimRecord` JSON whose excerpts are **actually present** in the fetch fixtures. This last point is the whole test: a fixture whose excerpt is absent must be rejected, and one of the fixtures is deliberately built that way.
- [ ] **Step 4: Implement `base.py` then `market.py`**

Market's query strategy (PRD §6): competitor pricing pages, plan comparisons, competitor counts, funding facts, launch dates. Queries are templated from the pitch's nouns plus the founder's `asserted_variable` names, so a `price_monthly` assertion generates a `"<category> pricing"` query — which is what makes R3 fire in the demo.

- [ ] **Step 5: Verify it passes**
- [ ] **Step 6: Commit** — `git commit -m "feat(chairs): market chair end to end with verified claim pipeline"`

---

### Task 3.8: Embeddings into `source_chunks`

**Files:** Create `jury/retrieval/embed.py`; Test `tests/retrieval/test_embed.py`

**Interfaces:**
- `class Embedder(kv: KV)` with `async def embed(texts: list[str]) -> list[list[float]]`
- `EMBEDDING_DIM = 384`, `EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"`
- `async def persist_chunks(pool, source_id: str, text: str, embedder: Embedder) -> int`
- `async def similar_chunks(pool, project_id: str, query: str, embedder: Embedder, limit: int = 5) -> list[dict]`

**Why this exists:** PRD §7.4 — *"Every finding is fetched, extracted, chunked, embedded, and persisted."* The schema's `vector(384)` HNSW index is otherwise dead weight, and PRD §16.3's optional near-duplicate detection (*"use pgvector similarity to catch near-duplicate statements of the same variable under different names"*) has nothing to query.

**Why local fastembed is load-bearing, not optional (PRD §15.3):** Groq serves no embeddings API. PRD §11.2 dec. 10: *"the highest-volume call in the system. Local removes an entire class of rate-limit and network failure."* Budget is ~3000 chunks per run (PRD §17.2), cached by content hash.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/retrieval/test_embed.py
import pytest

from jury.retrieval.embed import (EMBEDDING_DIM, EMBEDDING_MODEL, Embedder,
                                  persist_chunks, similar_chunks)
from jury.transport.kv import MemoryKV


def test_the_dimension_matches_the_schema_column():
    """A mismatch here fails at insert with an opaque pgvector error."""
    assert EMBEDDING_DIM == 384
    assert "bge-small-en-v1.5" in EMBEDDING_MODEL


async def test_embedding_returns_one_vector_per_text_at_the_right_dimension():
    vecs = await Embedder(MemoryKV()).embed(["a price of 149 INR", "monthly churn"])
    assert len(vecs) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vecs)


async def test_embedding_is_deterministic_for_the_same_text():
    e = Embedder(MemoryKV())
    assert await e.embed(["same text"]) == await e.embed(["same text"])


async def test_identical_content_is_served_from_the_content_hash_cache():
    """PRD §15.3: cache embeddings in Redis keyed by content hash."""
    kv = MemoryKV()
    e = Embedder(kv)
    await e.embed(["cached text"])
    before = e.model_invocations
    await e.embed(["cached text"])
    assert e.model_invocations == before


async def test_a_mixed_batch_only_embeds_the_uncached_members():
    kv = MemoryKV()
    e = Embedder(kv)
    await e.embed(["one"])
    before = e.texts_embedded
    await e.embed(["one", "two"])
    assert e.texts_embedded == before + 1


async def test_an_empty_batch_makes_no_model_call():
    e = Embedder(MemoryKV())
    assert await e.embed([]) == []
    assert e.model_invocations == 0


async def test_persist_chunks_writes_one_row_per_chunk(pool, source_id):
    n = await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    assert n > 1
    assert await count_chunks(source_id) == n


async def test_chunk_index_is_dense_and_ordered(pool, source_id):
    await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    rows = await fetch_chunks(source_id)
    assert [r["chunk_index"] for r in rows] == list(range(len(rows)))


async def test_persisting_the_same_source_twice_does_not_duplicate_chunks(pool, source_id):
    a = await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    b = await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    assert b == 0
    assert await count_chunks(source_id) == a


async def test_chunks_cascade_when_their_source_is_deleted(pool, source_id):
    """on delete cascade: an embedding must never outlive the row it cites
    (PRD §11.2 dec. 3 — the whole reason pgvector is in the same database)."""
    await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    await delete_source(source_id)
    assert await count_chunks(source_id) == 0


async def test_similarity_search_ranks_the_relevant_chunk_first(pool, source_id):
    await persist_chunks(pool, source_id,
                         "Delivery costs 30 rupees per order. "
                         "Our office is in Bengaluru. "
                         "Monthly churn among SMB accounts is 8 percent.",
                         Embedder(MemoryKV()))
    hits = await similar_chunks(pool, project_id, "what is the churn rate",
                                Embedder(MemoryKV()), limit=1)
    assert "churn" in hits[0]["content"].lower()


async def test_similarity_search_respects_the_limit(pool, source_id):
    await persist_chunks(pool, source_id, LONG_TEXT, Embedder(MemoryKV()))
    assert len(await similar_chunks(pool, project_id, "price", Embedder(MemoryKV()),
                                    limit=3)) <= 3


async def test_the_embedding_budget_is_enforced():
    """PRD §17.2: ~3000 chunks per run."""
    from jury.retrieval.embed import MAX_CHUNKS_PER_RUN
    assert MAX_CHUNKS_PER_RUN == 3000


async def test_embedding_never_leaves_the_process():
    """PRD §11.2 dec. 10: local, so no rate limit and no network failure class."""
    import inspect

    from jury.retrieval import embed
    src = inspect.getsource(embed)
    for banned in ("httpx", "requests", "openai", "api.openai", "litellm"):
        assert banned not in src, f"embed.py references {banned}"
```

- [ ] **Step 2: Verify it fails** — `uv run pytest tests/retrieval/test_embed.py -v`

- [ ] **Step 3: Implement `jury/retrieval/embed.py`**

```python
"""Local embeddings. PRD §11.2 decision 10 and §15.3.

Groq serves no embeddings API, so local fastembed is load-bearing rather than
optional. It is also the highest-volume call in the system, and running it
locally removes an entire class of rate-limit and network failure.

The model is loaded once per process and warmed on container start; weights are
baked into the image at build time (Phase 7).
"""
import hashlib
import json

from fastembed import TextEmbedding

from jury.retrieval.extract import chunk
from jury.transport.protocols import KV

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384                  # must match source_chunks.embedding vector(384)
MAX_CHUNKS_PER_RUN = 3000            # PRD §17.2

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    """Module-level singleton: loading the weights per call would dominate runtime."""
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _model


def warm() -> None:
    """Called at container start so the first real request does not pay the load."""
    _get_model().embed(["warm"])


def _content_key(text: str) -> str:
    return "emb:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class Embedder:
    """Content-hash cached embedder. Counters exist so tests can assert on cache
    behaviour without reaching into the model."""

    def __init__(self, kv: KV) -> None:
        self._kv = kv
        self.model_invocations = 0
        self.texts_embedded = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        out: list[list[float] | None] = [None] * len(texts)
        misses: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            cached = await self._kv.get(_content_key(text))
            if cached is not None:
                out[i] = json.loads(cached)
            else:
                misses.append((i, text))

        if misses:
            self.model_invocations += 1
            self.texts_embedded += len(misses)
            vectors = list(_get_model().embed([t for _, t in misses]))
            for (i, text), vec in zip(misses, vectors, strict=True):
                as_list = [float(x) for x in vec]
                out[i] = as_list
                await self._kv.set(_content_key(text), json.dumps(as_list), 604_800)

        return [v for v in out if v is not None]


async def persist_chunks(pool, source_id: str, text: str,
                         embedder: Embedder) -> int:
    """Chunk, embed and store. Returns rows written; 0 if already present.

    Idempotent on source_id so a re-run does not duplicate chunks.
    """
    async with pool.connection() as conn:
        existing = await (await conn.execute(
            "select count(*) from source_chunks where source_id = %s",
            (source_id,))).fetchone()
        if existing and existing[0] > 0:
            return 0

    pieces = chunk(text)[:MAX_CHUNKS_PER_RUN]
    if not pieces:
        return 0
    vectors = await embedder.embed(pieces)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into source_chunks (source_id, chunk_index, content, embedding) "
                "values (%s, %s, %s, %s)",
                [(source_id, i, piece, str(vec))
                 for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True))])
    return len(pieces)


async def similar_chunks(pool, project_id: str, query: str, embedder: Embedder,
                         limit: int = 5) -> list[dict]:
    """Cosine nearest neighbours over this project's fetched sources.

    Supports PRD §16.3's optional pass: catching near-duplicate statements of
    the same variable under different names.
    """
    vec = (await embedder.embed([query]))[0]
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "select sc.id, sc.content, sc.source_id, "
            "       1 - (sc.embedding <=> %s::vector) as similarity "
            "from source_chunks sc "
            "join evidence_items e on e.source_id = sc.source_id "
            "where e.project_id = %s "
            "group by sc.id, sc.content, sc.source_id, sc.embedding "
            "order by sc.embedding <=> %s::vector "
            "limit %s",
            (str(vec), project_id, str(vec), limit))).fetchall()
    return [{"id": r[0], "content": r[1], "source_id": r[2], "similarity": r[3]}
            for r in rows]
```

- [ ] **Step 4: Wire it into `chairs/base.py`** — after a claim verifies and its source row is upserted, call `persist_chunks(pool, source_id, verified.extracted_text, embedder)`. Chunks hang off the source, so this happens once per source regardless of how many claims cite it.

- [ ] **Step 5: Verify it passes** — expect 14 passed

- [ ] **Step 6: Commit** — `git commit -m "feat(retrieval): local fastembed embeddings into pgvector source_chunks"`

---

### Task 3.9: Phase gate

- [ ] **Step 1: Run the gate**

```bash
cd apps/api && JURY_OFFLINE=1 uv run pytest tests/retrieval tests/chairs tests/db -q
```

- [ ] **Step 2: Report the hallucination-guard number explicitly**

```bash
cd apps/api && uv run pytest tests/retrieval/test_verify.py -k fabricated -q
```
Expected: **51 passed** (50 parametrised + the aggregate). Record the number in `CHANGELOG.md` — this is the claim that survives judging.

- [ ] **Step 3: Run the tier eval and record accuracy**

```bash
cd apps/api && uv run pytest tests/retrieval/test_tiers_eval.py -q -s
```

- [ ] **Step 4: Append to `CHANGELOG.md`, commit and push**

Record: hallucination guard result, tier accuracy against the 100-URL set, and the Playwright cut with its fallback chain.

---

## Phase 3 exit criteria

- [ ] SSRF guard blocks loopback, private ranges, metadata endpoints, decimal/hex-encoded loopback, credentials-in-URL, and non-http schemes
- [ ] A redirect to a private address is refused
- [ ] Tier assignment is rule-based and **overrides** the model's claimed tier
- [ ] Live pricing/API-doc paths reach tier 1 on unknown vendors; a news domain is not promoted
- [ ] Tier eval ≥95% on 100 labelled URLs (report the actual figure)
- [ ] Fetch degrades trafilatura → Jina Reader; non-2xx returns a rejected source, never an exception
- [ ] The same canonical URL is fetched once per 24h
- [ ] **Excerpt-present-in-extracted-text enforced; paraphrase rejected**
- [ ] **50/50 fabricated companies rejected at insert — 100%**
- [ ] `EvidenceRepo` exposes no mutation method; duplicate insert returns `None`
- [ ] `dedup_hash` is computed by the repo, never supplied by a caller
- [ ] Market chair inserts only verified claims; a rejected claim leaves **zero** rows
- [ ] Exhausted budget marks the chair `partial`, lowering coverage as PRD §18 requires
- [ ] Chair emits `fetch` and `llm_call` trace rows
- [ ] Re-running the chair inserts no duplicates
- [ ] Embeddings are 384-dim, content-hash cached, and never leave the process
- [ ] `source_chunks` rows are dense-indexed, idempotent per source, and cascade on source delete
- [ ] Similarity search ranks the relevant chunk first and respects its limit
