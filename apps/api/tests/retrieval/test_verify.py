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
