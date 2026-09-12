from jury.engines.dedup import canonicalise_url, dedup_hash
from jury.schemas.scope import Scope


def s(**kw) -> Scope:
    return Scope(**{"geo": "IN", "segment": "smb", **kw})


def test_same_source_variable_and_scope_hash_identically():
    """P10: two chairs finding the same pricing page cannot inflate confidence twice."""
    a = dedup_hash("https://x.test/pricing", "price_monthly", s(tier="entry"))
    b = dedup_hash("https://x.test/pricing", "price_monthly", s(tier="entry"))
    assert a == b


def test_different_variable_hashes_differently():
    a = dedup_hash("https://x.test/pricing", "price_monthly", s())
    b = dedup_hash("https://x.test/pricing", "churn_monthly", s())
    assert a != b


def test_different_scope_hashes_differently():
    a = dedup_hash("https://x.test/p", "price_monthly", s(geo="IN"))
    b = dedup_hash("https://x.test/p", "price_monthly", s(geo="US"))
    assert a != b


def test_period_is_excluded_from_the_hash():
    """PRD §12.1 lists exactly five components; period is not one of them."""
    a = dedup_hash("https://x.test/p", "price_monthly", s(period="2025"))
    b = dedup_hash("https://x.test/p", "price_monthly", s(period="2026"))
    assert a == b


def test_null_variable_is_stable():
    a = dedup_hash("https://x.test/p", None, s())
    b = dedup_hash("https://x.test/p", None, s())
    assert a == b and len(a) == 64


def test_tracking_params_are_stripped():
    assert (canonicalise_url("https://x.test/p?utm_source=twitter&utm_medium=x")
            == "https://x.test/p")


def test_real_query_params_are_kept_and_sorted():
    assert (canonicalise_url("https://x.test/p?b=2&a=1")
            == "https://x.test/p?a=1&b=2")


def test_fragment_and_trailing_slash_stripped():
    assert canonicalise_url("https://x.test/p/#pricing") == "https://x.test/p"


def test_host_is_lowercased_and_www_stripped():
    assert canonicalise_url("https://WWW.X.test/P") == "https://x.test/P"


def test_default_ports_are_stripped():
    assert canonicalise_url("https://x.test:443/p") == "https://x.test/p"


def test_canonicalisation_makes_dedup_catch_tracked_duplicates():
    """The whole point: a URL shared with tracking params is the same source."""
    a = dedup_hash(canonicalise_url("https://x.test/pricing?utm_campaign=a"), "price_monthly", s())
    b = dedup_hash(canonicalise_url("https://x.test/pricing"), "price_monthly", s())
    assert a == b
