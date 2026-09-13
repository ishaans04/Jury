"""Source tier assignment. PRD §16.2 — by rule, not by model.

A domain allowlist/tier map is seeded by hand (db/seed/002_domain_tiers.sql)
and extended as needed. Unknown domains default to tier 3.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_TIER = 3
_VALID_TIERS = frozenset({1, 2, 3, 4})

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
    """Exact match, then walk up the subdomain chain.

    Matching is by whole dot-separated label, never by raw substring/suffix
    comparison, so 'notreddit.com' can never resolve to the 'reddit.com'
    entry -- only 'notreddit.com' itself (and its own subdomains) can. The
    loop also deliberately stops one label short of the bare TLD, so a map
    can never be matched by 'com' alone.

    A tier value outside 1-4 is treated as absent: the domain map is
    normally hand-seeded and DB-constrained to 1-4, but this function takes
    a plain dict and must not blindly trust a caller's corrupt entry (tier 5
    is a model prior and must never be persisted, per PRD P1).
    """
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        tier = domain_map.get(candidate)
        if tier in _VALID_TIERS:
            return tier
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
        # Scope of this gate, recorded deliberately: it only fires on a
        # review-aggregate domain's *reviews* pages (path contains
        # "review"), demoting an aggregate rating claim to the default tier
        # when no sample size is visible to back it up -- an unsourced
        # rating is not more trustworthy just because the site hosting it
        # is generally reputable. A non-review page on the same domain
        # (a product/category listing, a pricing comparison) is still
        # structured third-party data and keeps tier 2 unconditionally;
        # extending the demotion to every page on the domain would wrongly
        # downgrade legitimate structured data that never claimed a rating
        # in the first place.
        if known == 2 and "review" in parts.path.lower() and not has_review_count:
            return DEFAULT_TIER
        return known

    return DEFAULT_TIER
