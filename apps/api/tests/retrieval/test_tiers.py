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


# --- Extra coverage beyond the brief, per the scrutiny items called out for
# this batch.

def test_a_domain_that_merely_ends_with_a_known_domain_does_not_inherit_it():
    """'notreddit.com' must not be treated as a subdomain of 'reddit.com' just
    because the string ends the same way -- domain-map matching must respect
    label boundaries, not do a substring/suffix character comparison."""
    assert assign_tier("https://notreddit.com/r/x", MAP) == DEFAULT_TIER
    assert assign_tier("https://evil-crunchbase.com/x", MAP) == DEFAULT_TIER


def test_a_corrupt_domain_map_entry_cannot_smuggle_tier_five_through():
    """The domain map is normally hand-seeded with tiers 1-4 (a DB check
    constraint enforces this in production), but assign_tier takes a plain
    dict and must not blindly trust it -- tier 5 (or any other out-of-range
    value) must never surface just because a caller's map contains one."""
    bad_map = {"evil-mapped.test": 5}
    assert assign_tier("https://evil-mapped.test/x", bad_map) == DEFAULT_TIER
    bad_map2 = {"weird.test": 0}
    assert assign_tier("https://weird.test/x", bad_map2) == DEFAULT_TIER
