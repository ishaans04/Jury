"""The batch brief's `test_an_unresolvable_url_is_rejected` actually exercises an
*unmapped domain* (defaults to tier 3, accepted) rather than a genuinely
unresolvable one, despite its name -- see the batch report. This test closes
that gap.

`https://www./pricing` passes both ClaimRecord's `^https?://` pattern and the
SSRF guard (its host, "www.", is a syntactically ordinary non-empty,
non-private hostname as far as `is_fetch_allowed` is concerned -- there is no
DNS resolution to fail there). It is `assign_tier`'s own `www.`-stripping
normalisation that reduces the host to the empty string, so `assign_tier`
returns None and `verify_claim` must treat that as "unresolvable for tier
assignment", not silently default to tier 3.
"""
from jury.retrieval.verify import Rejection, verify_claim
from jury.schemas.claim import ClaimRecord
from jury.transport.protocols import FetchResult

MAP = {"x.test": 3}
PAGE = "Starter plan is priced at 149 INR per month."


def claim(url: str) -> ClaimRecord:
    return ClaimRecord.model_validate({
        "assumption_id": "a1", "direction": "supports", "variable": "price_monthly",
        "value_num": 149.0, "unit": "INR_per_month",
        "scope": {"geo": "IN", "segment": "smb"}, "confidence": 0.8,
        "source_url": url, "source_tier": 1,
        "excerpt": "Starter plan is priced at 149 INR per month", "chair": "market",
    })


class StubFetch:
    async def fetch(self, url):
        return FetchResult(url=url, status=200, text=PAGE)


async def test_a_url_assign_tier_cannot_resolve_is_rejected_not_defaulted():
    out = await verify_claim(claim("https://www./pricing"), StubFetch(), domain_map=MAP)
    assert isinstance(out, Rejection)
    assert "tier" in out.reason.lower()
